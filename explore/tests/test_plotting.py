"""Type-wide Plot view (#144): the live specifications sweep and its two views.

    python manage.py test explore.tests.test_plotting
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
import subprocess
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from explore import plotting
from explore.models import HierarchyNode as H, HwdbComponentEvent
from hwdb.fnal.bearer import FnalLinkRequired

STATIC = Path(__file__).resolve().parents[1] / "static" / "explore"
PLOT_CORE = STATIC / "plot-core.js"
PLOT_JS = PLOT_CORE.read_text() + (STATIC / "plot.js").read_text()   # #165: the page's script lives in static files
PTID = "D00599800007"


def _row(pid, specs=None, **over):
    row = {"part_id": pid, "serial_number": "SN-" + pid[-3:],
           "status": {"id": 100, "name": "Ready"},
           "creator": {"id": 1, "name": "Hajime M", "username": "hm"},
           "manufacturer": None, "institution": {"id": 5, "name": "BNL"},
           "created": "2026-01-02T10:00:00-05:00", "updated": "2026-03-04T11:00:00-05:00",
           "specifications": specs}
    row.update(over)
    return row


def _api(pages):
    """Fake client: ``pages`` is a list of row lists, one per page."""
    api = mock.MagicMock()

    def _get(method, endpoint, params=None, **kw):
        n = params["page"]
        return {"data": pages[n - 1], "pagination": {"pages": len(pages), "page": n}}
    api._make_request.side_effect = _get
    return api


class FlatRowTest(TestCase):
    def test_latest_spec_entry_data_wins(self):
        r = plotting.flat_row(_row(f"{PTID}-00001", specs=[
            {"DATA": {"R": 1}}, {"DATA": {"R": 2, "Nested": [{"a": 1}, {"a": 2}]}}]))
        self.assertEqual(r["data"], {"R": 2, "Nested": [{"a": 1}, {"a": 2}]})
        self.assertEqual(r["pid"], f"{PTID}-00001")
        self.assertEqual(r["status"], "Ready")
        self.assertEqual(r["creator"], "Hajime M")
        self.assertEqual(r["manufacturer"], "")
        self.assertEqual(r["institution"], "BNL")
        self.assertEqual((r["created"], r["updated"]), ("2026-01-02", "2026-03-04"))

    def test_entry_without_data_key_and_no_specs(self):
        self.assertEqual(plotting.flat_row(_row("x", specs=[{"k": 1}]))["data"], {"k": 1})
        self.assertEqual(plotting.flat_row(_row("x", specs=[]))["data"], {})
        self.assertEqual(plotting.flat_row(_row("x", specs=None))["data"], {})
        self.assertEqual(plotting.flat_row(_row("x", specs=[{}]))["data"], {})


class StreamSpecsTest(TestCase):
    def test_ndjson_shape_across_pages(self):
        api = _api([[_row(f"{PTID}-00001", [{"DATA": {"R": 1}}]), _row(f"{PTID}-00002", [{}])],
                    [_row(f"{PTID}-00003", [{"DATA": {"R": 3}}])]])
        lines = [json.loads(l) for l in plotting.stream_specs(api, PTID)]
        self.assertEqual(lines[0], {"pages": 2})
        self.assertEqual([l["pid"] for l in lines if "pid" in l],
                         [f"{PTID}-00001", f"{PTID}-00002", f"{PTID}-00003"])
        self.assertEqual([l["page"] for l in lines if "page" in l], [1, 2])
        self.assertEqual(lines[-1], {"done": 3})
        self.assertEqual(api._make_request.call_count, 2)
        self.assertEqual(api._make_request.call_args.kwargs["params"],
                         {"part_type_id": PTID, "page": 2, "size": plotting.PAGE_SIZE})

    def test_error_mid_sweep_ends_the_stream_with_an_error_line(self):
        api = mock.MagicMock()
        api._make_request.side_effect = [
            {"data": [_row("a", [{}])], "pagination": {"pages": 3}}, RuntimeError("boom")]
        lines = [json.loads(l) for l in plotting.stream_specs(api, PTID)]
        self.assertEqual(lines[-1], {"error": "RuntimeError: boom"})
        self.assertFalse(any("done" in l for l in lines))


class PlotViewsTest(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("p", "p@p.io", "pw"))
        self.leaf = H.objects.create(
            instance="dev", level=H.LEVEL_TYPE, system_id=5, system_name="HVS",
            subsystem_id=998, subsystem_name="UnitTest", name="Test Type 007",
            part_type_id=PTID, n_components=153, tests_synced_at=timezone.now())

    def test_page_renders_with_mirror_count_and_data_url(self):
        for i in range(3):
            HwdbComponentEvent.objects.create(instance="dev", part_type_id=PTID, part_id=f"{PTID}-0000{i}")
        html = self.client.get(f"/hw/dev/plot/{PTID}/").content.decode()
        self.assertIn(f'data-key="dev/{PTID}"', html)
        self.assertIn(f'data-url="/hw/dev/plot/{PTID}/data/"', html)
        self.assertIn('data-n="3"', html)          # mirror count wins over n_components

    def test_embed_mode_and_checklist_entries(self):
        # #160: inside a checklist's plot field — chrome hidden, the hash's
        # `ids` (PIDs or serial numbers) select every series' items
        resp = self.client.get(f"/hw/dev/plot/{PTID}/?embed=1")
        self.assertEqual(resp["X-Frame-Options"], "SAMEORIGIN")   # the fill page's iframe may show it
        html = resp.content.decode()
        self.assertIn('data-embed="1"', html)
        self.assertIn(".eh-header, .eh-devbanner, .eh-foot, .ex-side, .pl-head, .pl-tabs, .pl-panel", html)
        self.assertIn(".pl-bar .right > :not(#zoom-reset):not(#png-btn) { display: none !important; }", html)   # Reset zoom stays
        # no status strip (it collided with the axis title); the stats box is drawn in a narrow embed, below the buttons
        self.assertIn(".pl-status { display: none; }", html)
        self.assertIn(".pl-plotwrap > canvas { position: absolute; inset: 0; }", html)
        self.assertIn("y = a.top + 6 + (EMBED ? 26 : 0)", PLOT_JS)
        self.assertIn("if (!EMBED && aw < 480) return;", PLOT_JS)
        # Anselmo 2026-09-21: a plot in one of four grid columns (150-280 px) still gets its stats — a compact box, top-left
        self.assertIn("if (EMBED && aw < 240) {", PLOT_JS)
        self.assertIn("w = Math.min(140, aw - 8); h = 50; fs = 9.5; x = a.left + 4;", PLOT_JS)
        self.assertIn("if (aw < 120) return;", PLOT_JS)
        self.assertIn("function pidFilter(s) { if (IDS) return idsFilter();", PLOT_JS)
        self.assertIn("(bySn[normSn(it.serial)] = bySn[normSn(it.serial)] || []).push(it.pid);", PLOT_JS)   # #168: every holder
        self.assertIn('d.replace(/^0+(?=\\d)/, "")', PLOT_JS)          # HPK19843 finds HPK019843
        self.assertIn('window.addEventListener("hashchange"', PLOT_JS)
        self.assertIn('if (IDS && !EMBED) { var pf = idsFilter(); series.forEach(function (s) { s.item = ""; s.pid = pf; }); IDS = null; }', PLOT_JS)
        # points name the item, its serial and the value's place in the array; a
        # histogram bin lists what sits in it; drag-selecting a row's text is not a pick
        self.assertIn('function who(pid) { var it = itemByPid[pid]; return pid + (it && it.serial ? " · " + it.serial : ""); }', PLOT_JS)
        self.assertIn('t: who(it.pid), ix: idxLabel(s.x, s, srcIdx(arr, j))', PLOT_JS)
        self.assertIn('(d[l].seg || "level " + (l + 1)) + "[" + f(x) + "]"; }).join(" › ")', PLOT_JS)   # Test Results[7] › SiPM[5]
        self.assertIn("free[k].at = rest % free[k].n; rest = Math.floor(rest / free[k].n);", PLOT_JS)   # flat → [m, n]
        self.assertIn("afterBody: function (cs) {", PLOT_JS)
        self.assertIn("if (String(window.getSelection && window.getSelection()).length) return;", PLOT_JS)
        plain = self.client.get(f"/hw/dev/plot/{PTID}/").content.decode()
        self.assertNotIn('data-embed="1"', plain)
        self.assertNotIn(".pl-panel, .pl-vsplit, .pl-bar, .pl-split, .pl-grid { display: none", plain)

    def test_page_falls_back_to_n_components_and_404s_unknown_type(self):
        html = self.client.get(f"/hw/dev/plot/{PTID}/").content.decode()
        self.assertIn('data-n="153"', html)
        self.assertEqual(self.client.get("/hw/dev/plot/NOPE/").status_code, 404)
        self.assertEqual(self.client.get(f"/hw/plot/{PTID}/").status_code, 404)  # prod has no such leaf

    def test_data_view_streams_ndjson_on_the_urls_instance(self):
        api = _api([[_row(f"{PTID}-00001", [{"DATA": {"R": 1}}])]])
        with mock.patch("explore.views.mint_for", return_value="bearer"), \
             mock.patch("explore.views.FnalDbApiClient", return_value=api) as cls:
            resp = self.client.post(f"/hw/dev/plot/{PTID}/data/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/x-ndjson")
        lines = [json.loads(l) for l in b"".join(resp.streaming_content).decode().splitlines()]
        self.assertEqual(lines[0], {"pages": 1})
        self.assertEqual(lines[1]["data"], {"R": 1})
        self.assertEqual(lines[-1], {"done": 1})
        self.assertIn("cdbdev", cls.call_args.args[0])

    def test_data_view_requires_post_and_redirects_to_link_when_unlinked(self):
        self.assertEqual(self.client.get(f"/hw/dev/plot/{PTID}/data/").status_code, 405)
        with mock.patch("explore.views.mint_for", side_effect=FnalLinkRequired()):
            resp = self.client.post(f"/hw/dev/plot/{PTID}/data/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("next=%2Fhw%2Fdev%2Fplot%2F", resp["Location"])


class PlotsTabTest(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("q", "q@q.io", "pw"))

    def _leaf(self, inst, ptid, n, name="T", sub="SS"):
        return H.objects.create(instance=inst, level=H.LEVEL_TYPE, system_id=5, system_name="HVS",
                                subsystem_id=1, subsystem_name=sub, name=name, part_type_id=ptid, n_components=n)

    def test_lists_types_with_items_on_the_instance_grouped(self):
        self._leaf("dev", "D1", 12, "Alpha", "S1"), self._leaf("dev", "D2", 0, "Empty", "S1")
        self._leaf("dev", "D3", 3, "Beta", "S2"), self._leaf("prod", "P1", 9, "ProdOnly")
        html = self.client.get("/hw/dev/plots/").content.decode()
        self.assertIn("/hw/dev/plot/D1/", html)
        self.assertIn("/hw/dev/plot/D3/", html)
        self.assertNotIn("/hw/dev/plot/D2/", html)     # no items → no plot
        self.assertNotIn("ProdOnly", html)             # other instance
        self.assertIn("2 types with items", html)
        self.assertLess(html.index("S1"), html.index("S2"))
        self.assertIn("12 items", html)

    def test_nav_tab_is_active_and_sits_after_shipments(self):
        html = self.client.get("/hw/dev/plots/").content.decode()
        self.assertIn('class="eh-nav-item active" href="/hw/dev/plots/">Plots</a>', html)
        self.assertLess(html.index('>Shipments</a>'), html.index('>Plots</a>'))
        self.assertLess(html.index('>Plots</a>'), html.index('>Activities</a>'))


# ---- test_data source (#143) -------------------------------------------------

from explore import events
from explore.models import HwdbTestData


def _td(inst, ptid, pid, ttid, name, data, created="2026-02-03T10:00:00+00:00"):
    """A mirrored record + its per-key value rows (what store_test_data writes)."""
    from explore.models import HwdbTestValue
    row = HwdbTestData.objects.create(
        instance=inst, part_type_id=ptid, part_id=pid, test_type_id=ttid, test_type_name=name,
        test_id=1, created=created, test_data=data)
    HwdbTestValue.objects.bulk_create(plotting.value_rows(inst, ptid, pid, ttid, data))
    return row


class WalkAndValuesTest(TestCase):
    def test_flatten_matches_walk_and_values_at(self):
        d = {"A": 1, "L": [{"b": 1}, {"b": [2, 3]}, {"c": 4}], "S": [1, 2, 3], "N": {"x": {"y": 0}}, "E": [], "Z": None}
        flat = plotting.flatten(d)
        acc = {}; plotting.walk_keys(d, (), acc)
        # same keys, except those with no values at all (E is empty, Z is None):
        # the walk lists them, the value table has no row for them
        self.assertEqual({k for k, v in flat.items() if v}, {k for k in acc if plotting.values_at(d, list(k))})
        for path, vals in flat.items():
            self.assertEqual(vals, plotting.values_at(d, list(path)), path)
        self.assertEqual(flat[("L", "b")], [1, 2, 3])

    def test_value_rows_one_per_key_with_counts(self):
        rows = plotting.value_rows("dev", "T", "T-1", 5, {"R": 5, "Ch": [1, 2, 3], "E": []})
        self.assertEqual({(r.path, r.nv, tuple(r.values)) for r in rows},
                         {('["R"]', 1, (5,)), ('["Ch"]', 3, (1, 2, 3))})

    def test_walk_explodes_lists_of_dicts_and_counts_once_per_item(self):
        acc = {}
        plotting.walk_keys({"A": 1, "L": [{"b": 1}, {"b": 2, "c": 3}], "S": [1, 2, 3], "N": {"x": {"y": 0}}}, (), acc)
        self.assertEqual(acc, {("A",): 1, ("L", "b"): 1, ("L", "c"): 1, ("S",): 1, ("N", "x", "y"): 1})

    def test_values_at_flattens_lists_and_skips_containers(self):
        d = {"L": [{"b": 1}, {"b": [2, 3]}, {"c": 4}], "S": [1, 2], "D": {"k": 1}}
        self.assertEqual(plotting.values_at(d, ["L", "b"]), [1, 2, 3])
        self.assertEqual(plotting.values_at(d, ["S"]), [1, 2])
        self.assertEqual(plotting.values_at(d, ["D"]), [])          # a dict is not a leaf
        self.assertEqual(plotting.values_at(d, ["nope"]), [])


class NestedValuesTest(TestCase):
    """#154: value rows keep the list structure; one index per level can be pinned."""
    # a SiPM-like record: runs (with a header entry) × SiPM entries (with a header) × sweep
    REC = {"TR": [{"_meta": True},
                  {"Loc": [{"_meta": True}, {"i": 1, "I": [1, 2]}, {"i": 2, "I": [3, 4]}], "T": "cold"},
                  {"Loc": [{"i": 1, "I": [5, 6]}, {"i": 2, "I": [7, 8]}], "T": "warm"}],
           "R": 5, "Ch": [1, 2, 3], "L": [{"b": 1}, {"b": [2, 3]}, {"c": 4}]}

    def test_nested_flattens_to_values_at(self):
        for p in plotting.flatten(self.REC):
            self.assertEqual(plotting.leaves(plotting.nested(self.REC, list(p))),
                             plotting.values_at(self.REC, list(p)), p)
        self.assertEqual(plotting.nested(self.REC, ["TR", "Loc", "I"]), [[[1, 2], [3, 4]], [[5, 6], [7, 8]]])
        self.assertEqual(plotting.nested(self.REC, ["TR", "T"]), ["cold", "warm"])
        self.assertEqual(plotting.nested(self.REC, ["R"]), 5)
        self.assertEqual(plotting.nested(self.REC, ["L", "b"]), [1, [2, 3]])

    def test_dims_labels_and_select(self):
        v = plotting.nested(self.REC, ["TR", "Loc", "I"])
        self.assertEqual(plotting.dims(v), [2, 2, 2])
        self.assertEqual(plotting.dim_labels(self.REC, ["TR", "Loc", "I"]), ["TR", "Loc", "I"])
        self.assertEqual(plotting.dims([5]), [1])
        self.assertEqual(plotting.dims(plotting.nested(self.REC, ["L", "b"])), [2, 2])
        self.assertEqual(plotting.select(v, [None, 1, None]), [3, 4, 7, 8])     # SiPM #2 of every run
        self.assertEqual(plotting.select(v, [0, None, None]), [1, 2, 3, 4])     # first run
        self.assertEqual(plotting.select(v, [None, None, 0]), [1, 3, 5, 7])     # first sweep point
        self.assertEqual(plotting.select(v, [None, 5, None]), [])               # past the end
        self.assertEqual(plotting.select(v, []), [1, 2, 3, 4, 5, 6, 7, 8])
        self.assertEqual(plotting.select([1, 2, 3], [1]), [2])                  # a flat (pre-#154) row

    def test_value_rows_keep_structure_and_count_leaves(self):
        rows = {r.path: r for r in plotting.value_rows("dev", "T", "T-1", 5, self.REC)}
        self.assertEqual(rows['["TR", "Loc", "I"]'].values, [[[1, 2], [3, 4]], [[5, 6], [7, 8]]])
        self.assertEqual(rows['["TR", "Loc", "I"]'].nv, 8)
        self.assertEqual((rows['["R"]'].values, rows['["Ch"]'].values), ([5], [1, 2, 3]))

    def test_keys_report_shape_and_values_take_idx(self):
        self.client.force_login(get_user_model().objects.create_user("n", "n@n.io", "pw"))
        _td("dev", "T", "T-00001", 5, "A", self.REC)
        _td("dev", "T", "T-00002", 5, "A", {"TR": [{"Loc": [{"i": 1, "I": [9]}]}], "R": 6})
        # one run with the longest sweep — the biggest row, yet not the shape of the type (#160 follow-up)
        _td("dev", "T", "T-00003", 5, "A", {"TR": [{"Loc": [{"i": 1, "I": list(range(40))}]}]})
        by = {tuple(x["path"]): x for x in self.client.get("/hw/dev/plot/T/tests/5/keys/").json()["keys"]}
        self.assertEqual(by[("TR", "Loc", "I")]["dims"], [{"seg": "TR", "n": 2}, {"seg": "Loc", "n": 2}, {"seg": "I", "n": 40}])
        self.assertNotIn("dims", by[("R",)])                                    # a scalar has no shape
        from explore.models import HwdbTestValue
        HwdbTestValue.objects.filter(part_id="T-00003").delete()
        HwdbTestData.objects.filter(part_id="T-00003").delete()
        url, key = "/hw/dev/plot/T/tests/5/values/", json.dumps(["TR", "Loc", "I"])
        self.assertEqual(self.client.get(url, {"key": key}).json()["values"],
                         {"T-00001": [1, 2, 3, 4, 5, 6, 7, 8], "T-00002": [9]})    # flat, as before
        self.assertEqual(self.client.get(url, {"key": key, "idx": "[null, 1, null]"}).json()["values"],
                         {"T-00001": [3, 4, 7, 8]})                              # T-00002 has no SiPM #2
        self.assertEqual(self.client.get(url, {"key": key, "idx": "[0, 0, 0]", "pid": "00002..00002"}).json()["values"],
                         {"T-00002": [9]})
        self.assertEqual(self.client.get(url, {"key": key, "idx": "[-1]"}).status_code, 400)
        with mock.patch.object(plotting, "MAX_VALUES", 3):
            self.assertEqual(self.client.get(url, {"key": key}).status_code, 413)
            self.assertEqual(self.client.get(url, {"key": key, "idx": "[null, 1, null]"}).status_code, 413)   # 4 > 3
            self.assertEqual(self.client.get(url, {"key": key, "idx": "[0, 1, null]"}).status_code, 200)     # 2


class TestDataMirrorTest(TestCase):
    def test_registry_sync_stores_latest_record_per_test_type(self):
        from django.conf import settings
        ptid = settings.HWDB_PROFILES["prod"]["larasic_part_type"]
        H.objects.create(instance="prod", level=H.LEVEL_TYPE, system_id=81, system_name="CE",
                         subsystem_id=1, subsystem_name="ASIC", name="LArASIC", part_type_id=ptid)
        client = mock.MagicMock()

        def _make_request(method, endpoint, params=None, **kw):
            if endpoint.endswith("/components"):
                return {"data": [{"part_id": f"{ptid}-00001"}], "pagination": {"pages": 1}}
            return {"data": {"part_id": f"{ptid}-00001", "created": "2026-01-01T00:00:00+00:00",
                             "updated": "2026-01-02T00:00:00+00:00"}}
        client._make_request.side_effect = _make_request
        client.get_test_types.return_value = {"data": [{"name": "RoomT QC Test", "id": 38}]}
        client.get_tests.return_value = {"data": [
            {"id": 7, "created": "2026-01-05T00:00:00+00:00", "test_data": {"Test Date": "2026/01/05", "Noise": 1.5}},
            {"id": 9, "created": "2026-01-09T00:00:00+00:00", "test_data": {"Test Date": "2026/01/09", "Noise": 1.7}},
        ]}
        with mock.patch("explore.events.FnalDbApiClient", return_value=client), \
             mock.patch("explore.events.sweep_enabled", return_value=0):
            log = "".join(events.sync_test_events("https://x", "b", ptid))
        self.assertIn("1 latest test record(s) mirrored", log)
        row = HwdbTestData.objects.get(instance="prod", part_id=f"{ptid}-00001", test_type_id=38)
        self.assertEqual((row.test_id, row.test_data["Noise"]), (9, 1.7))   # the newer record wins

    def test_store_replaces_only_the_pairs_given(self):
        _td("dev", "T", "T-1", 5, "A", {"v": 1}); _td("dev", "T", "T-1", 6, "B", {"v": 2}); _td("prod", "T", "T-1", 5, "A", {"v": 3})
        events.store_test_data("dev", "T", [{"part_id": "T-1", "test_type_id": 5, "test_type_name": "A",
                                             "test_id": 2, "created": None, "test_data": {"v": 10}}])
        vals = {(r.instance, r.test_type_id): r.test_data["v"] for r in HwdbTestData.objects.all()}
        self.assertEqual(vals, {("dev", 5): 10, ("dev", 6): 2, ("prod", 5): 3})
        from explore.models import HwdbTestValue
        self.assertEqual({(r.instance, r.test_type_id, r.values[0]) for r in HwdbTestValue.objects.all()},
                         {("dev", 5, 10), ("dev", 6, 2), ("prod", 5, 3)})

    def test_sync_test_data_incremental_skips_items_already_mirrored(self):
        _td("dev", "T", "T-00001", 5, "A", {"v": 1})
        client = mock.MagicMock()
        client.get_test_types.return_value = {"data": [{"name": "A", "id": 5}, {"name": "B", "id": 6}]}
        client._make_request.return_value = {"data": [{"part_id": "T-00001"}, {"part_id": "T-00002"}], "pagination": {"pages": 1}}
        client.get_tests.side_effect = lambda pid, test_type_id=None, history=False: {
            "data": [{"id": 1, "created": "2026-03-01T00:00:00+00:00", "test_data": {"v": test_type_id}}]}
        with mock.patch("explore.events.FnalDbApiClient", return_value=client):
            log = "".join(events.sync_test_data("https://x", "b", "T", instance="dev", workers=2))
        self.assertIn("1 item(s) × 2 test type(s) = 2 call(s)", log)
        self.assertIn("2 record(s) stored, 3 total", log)
        self.assertEqual(sorted(HwdbTestData.objects.filter(part_id="T-00002").values_list("test_type_id", flat=True)), [5, 6])
        with mock.patch("explore.events.FnalDbApiClient", return_value=client):
            log = "".join(events.sync_test_data("https://x", "b", "T", instance="dev", mode="full", workers=2))
        self.assertIn("2 item(s) × 2 test type(s)", log)
        self.assertEqual(HwdbTestData.objects.filter(instance="dev", part_type_id="T").count(), 4)



# #162: the Draw-expression block of plot.html, run in node against a small key inventory.
DRAW_HARNESS = r"""
var keys = [
  { path: ["Test Results", "SiPM", "Result"], dims: [{ seg: "Test Results", n: 8 }, { seg: "SiPM", n: 6 }] },
  { path: ["Test Results", "SiPM Location", "Result"], dims: [{ seg: "Test Results", n: 8 }, { seg: "SiPM Location", n: 6 }] },
  { path: ["Test Results", "R_eff"], dims: [] }, { path: ["Test Results", "R_cable"], dims: [] },
  { path: ["x"], dims: [] }, { path: ["X"], dims: [] }, { path: ["Only Lower"], dims: [] }, { path: ["Loc"], dims: [] },
  { path: ["Test Results", "SiPM", "V"], dims: [{ seg: "Test Results", n: 6 }, { seg: "SiPM", n: 6 }, { seg: "V", n: 300 }] },
].map(function (k) { return { p: JSON.stringify(k.path), segs: k.path, dims: function () { return k.dims; } }; });
function comp(t) { var res = []; var c = exprCompile(t, function (tok) { var r = tok.t === "attr" ? { attr: tok.v } : exprResolve(tok, keys), k = r.attr ? "$" + r.attr : r.p + JSON.stringify(r.ix); for (var i = 0; i < res.length; i++) if ((res[i].attr ? "$" + res[i].attr : res[i].p + JSON.stringify(res[i].ix)) === k) return i; res.push(r); return res.length - 1; }); return { fn: c.fn, ids: res }; }   // one slot per key+pins / field, as exprMeta does
function ids(t) { try { return comp(t).ids.map(function (i) { return i.attr ? ["$" + i.attr] : [JSON.parse(i.p).join("."), i.ix]; }); } catch (e) { return "ERR " + e.message; } }
function sel(t, arr, arrays) { var m = exprEval(comp(t).fn, arrays), r = exprSelect(arr, m); return [r, r.src]; }
function ev(t, arrays) { var c = comp(t), r = exprEval(c.fn, arrays); return [r, r.src]; }
console.log(JSON.stringify({
  pin_leaf: ids("SiPM.Result[3]"), pin_seg: ids("SiPM[5].Result"), pin_skip: ids("SiPM.Result[][5]"), pin_two: ids('"Test Results".SiPM.Result[2][1]'),
  leaf_names_level: ids("SiPM.V[0][1]"), leaf_three: ids("V[0][1][7]"), inner_and_leaf: ids("SiPM[2].V[0]"), leaf_too_many: ids("V[0][1][2][3]"),
  loose_case: ids("test_results.sipm.result"), exact_x: ids("x"), exact_X: ids("X"), loose_only: ids("only_lower"),
  ambiguous: ids("Result"), unknown: ids("nope"), past_end: ids("SiPM.Result[9]"), binning: ids("x>>(1,2,3)"), not_list: ids("R_eff[1]"),
  two_ids: ids("R_eff/R_cable"),
  broadcast: ev("R_eff/R_cable", [[10], [2, 4]]), neg_pow: ev("-x^2", [[3]]), pow_neg: ev("2^-1", []), cmp: ev("x>2", [[1, 3]]),
  drops: ev("x*1", [["q", 2, null, 4]]), funcs: ev("sqrt(x)+min(x,X)", [[9], [1, 2]]), consts: ev("pi*2", []), div0: ev("x/0", [[1]]),
  logic: ev("!x && 1 || 0", [[0, 1]]), empty_id: ev("x+X", [[], [1]]),
  split: [exprSplit("f(a):b"), exprSplit('"a:b"'), exprSplit("SiPM.Result[3]"), exprSplit("a : b")],
  // #163: text, regex, item fields, the selection mask
  attr_ids: ids("$serial =~ 'a' && SiPM.Result[3] > 1"), bad_field: ids("$foo"), bad_pattern: ids("x =~ '('"),
  re_hit: ev("$serial =~ '^hpk'", [["HPK19901"]]), re_miss: ev("$serial =~ '^hpk'", [["SMB1"]]), text_eq: ev("Loc == 'BNL'", [["BNL", "CERN"]]),
  text_lt: ev("Loc < 'C'", [["BNL", "CERN"]]), num_text: ev("x + 1", [["3"]]), not_text: ev("!Loc", [["", "x"]]),
  mixed: ev("x > 50 && $status == 'Unknown'", [[49, 51, 52], ["Unknown"]]),
  // #164: the trailing ">> name(nx,lo,hi,…)"
  bin_1d: exprBinning("SiPM.Result[3] >> (20,49,53)"), bin_2d: exprBinning("y:x >> h(30,49,53,10,0,0.1)"), bin_n: exprBinning("a>>(20)"), bin_name: exprBinning("a >> h"),
  bin_blank: exprBinning("a >> (20,,53)"), bin_none: exprBinning("a + b"), bin_bad: [(function () { try { exprBinning("a >> (20,49)"); } catch (e) { return e.message; } })(), (function () { try { exprBinning("a >> (1)"); } catch (e) { return e.message; } })(), (function () { try { exprBinning("a >> (20,5,1)"); } catch (e) { return e.message; } })()],
  opt: [exprOption("colz"), exprOption("cum logy nostats"), exprOption(""), (function () { try { exprOption("foo"); } catch (e) { return e.message; } })()],
  sel_entries: sel("x > 50", [10, 20, 30], [[49, 51, 52]]), sel_item_out: sel("$status == 'Ready'", [10, 20, 30], [["Unknown"]]), sel_item_in: sel("$status == 'Unknown'", [10, 20, 30], [["Unknown"]]),
}));
"""


class TestDataEndpointsTest(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("t", "t@t.io", "pw"))
        H.objects.create(instance="dev", level=H.LEVEL_TYPE, system_id=5, system_name="S", subsystem_id=1,
                         subsystem_name="SS", name="T", part_type_id="T", n_components=2)
        HwdbComponentEvent.objects.create(instance="dev", part_type_id="T", part_id="T-1", status="Ready", created_by="hm")
        _td("dev", "T", "T-1", 5, "A", {"Noise": 1.5, "Ch": [1, 2, 3]})
        _td("dev", "T", "T-2", 5, "A", {"Noise": 2.5})
        _td("dev", "T", "T-1", 6, "B", {"Gain": 9})

    def test_sources_keys_items_values(self):
        j = self.client.get("/hw/dev/plot/T/sources/").json()
        self.assertEqual(j["tests"], [{"id": 5, "name": "A", "n": 2}, {"id": 6, "name": "B", "n": 1}])
        k = self.client.get("/hw/dev/plot/T/tests/5/keys/").json()
        self.assertEqual(k["n_items"], 2)
        self.assertEqual(k["keys"], [{"path": ["Noise"], "n": 2, "nv": 2, "big": False},
                                     {"path": ["Ch"], "n": 1, "nv": 3, "big": False,
                                      "dims": [{"seg": "Ch", "n": 3}]}])   # 3/item is not an array key; #154 shape
        it = self.client.get("/hw/dev/plot/T/tests/5/items/").json()["items"]
        self.assertEqual([(i["pid"], i["status"], i["creator"], i["tested"]) for i in it],
                         [("T-1", "Ready", "hm", "2026-02-03"), ("T-2", "", "", "2026-02-03")])
        v = self.client.get("/hw/dev/plot/T/tests/5/values/", {"key": json.dumps(["Ch"])}).json()
        self.assertEqual(v, {"values": {"T-1": [1, 2, 3]}})
        self.assertEqual(self.client.get("/hw/dev/plot/T/tests/5/values/", {"key": "nope"}).status_code, 400)
        self.assertEqual(self.client.get("/hw/plot/T/sources/").json(), {"tests": []})   # other instance

    def test_page_has_the_index_pin_row(self):
        html = self.client.get("/hw/dev/plot/T/").content.decode()
        self.assertIn('id="idx-row"', html)
        self.assertIn('id="xidx"', html)

    def test_draw_expression_block_runs_in_node(self):
        # #162: ROOT-style Draw — plot-core.js (tokenizer, parser, resolver, evaluator) exercised in node
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not installed")
        pre = "var C = require(" + json.dumps(str(PLOT_CORE)) + "); var exprCompile = C.exprCompile, exprResolve = C.exprResolve, exprEval = C.exprEval, exprSplit = C.exprSplit, exprSelect = C.exprSelect, exprBinning = C.exprBinning, exprOption = C.exprOption;\n"
        run = subprocess.run([node, "-e", pre + DRAW_HARNESS], capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stderr)
        r = json.loads(run.stdout)
        K = "Test Results.SiPM.Result"
        self.assertEqual(r["pin_leaf"], [[K, [3, None]]])          # leaf [i] pins the first level (ROOT order)
        self.assertEqual(r["pin_seg"], [[K, [None, 5]]])           # [i] on the segment naming a level pins that level
        self.assertEqual(r["pin_skip"], [[K, [None, 5]]])          # [] skips a level
        self.assertEqual(r["pin_two"], [[K, [2, 1]]])
        V = "Test Results.SiPM.V"
        self.assertEqual(r["leaf_names_level"], [[V, [0, 1, None]]])   # the leaf names the innermost list, its brackets still count from the first
        self.assertEqual(r["leaf_three"], [[V, [0, 1, 7]]])
        self.assertEqual(r["inner_and_leaf"], [[V, [0, 2, None]]])     # SiPM[2] pins the SiPM level, V[0] the first
        self.assertIn("“V” has 3 indexes, not 4", r["leaf_too_many"])
        self.assertEqual(r["loose_case"], [[K, None]])             # case and space/underscore ignored …
        self.assertEqual((r["exact_x"], r["exact_X"]), ([["x", None]], [["X", None]]))   # … unless keys differ only by case
        self.assertEqual(r["loose_only"], [["Only Lower", None]])
        self.assertIn("matches 2 keys: Test Results.SiPM.Result, Test Results.SiPM Location.Result", r["ambiguous"])
        self.assertIn("no key named “nope”", r["unknown"])
        self.assertIn("index 9 is past the end of Test Results (8 entries)", r["past_end"])
        self.assertIn("binning goes at the end: expr >> (nx,lo,hi)", r["binning"])   # ">>" inside an expression
        self.assertIn("“R_eff” is not a list", r["not_list"])
        self.assertEqual(r["two_ids"], [["Test Results.R_eff", None], ["Test Results.R_cable", None]])
        self.assertEqual(r["broadcast"], [[5, 2.5], [0, 1]])       # a single value repeats along the list
        self.assertEqual(r["neg_pow"], [[-9], [0]])                # -x^2 = -(x^2)
        self.assertEqual(r["pow_neg"], [[0.5], [0]])
        self.assertEqual(r["cmp"], [[0, 1], [0, 1]])
        self.assertEqual(r["drops"], [[2, 4], [1, 3]])             # non-numeric entries drop; src keeps the entry index
        self.assertEqual(r["funcs"], [[4, 5], [0, 1]])
        self.assertAlmostEqual(r["consts"][0][0], 6.283185307179586)
        self.assertEqual(r["div0"], [[], []])                      # non-finite results drop
        self.assertEqual(r["logic"], [[1, 0], [0, 1]])
        self.assertEqual(r["empty_id"], [[], []])                  # an identifier with no values gives nothing
        self.assertEqual(r["split"], [["f(a)", "b"], ['"a:b"'], ["SiPM.Result[3]"], ["a", "b"]])
        # #163: text in 'single quotes', =~ regex, $fields, and the per-entry selection mask
        self.assertEqual(r["attr_ids"], [["$serial"], [K, [3, None]]])
        self.assertIn("no item field “$foo” — one of $pid $serial $status $creator $institution $manufacturer", r["bad_field"])
        self.assertIn("bad pattern “(”", r["bad_pattern"])
        self.assertEqual((r["re_hit"], r["re_miss"]), ([[1], [0]], [[0], [0]]))
        self.assertEqual(r["text_eq"], [[1, 0], [0, 1]])
        self.assertEqual(r["text_lt"], [[1, 0], [0, 1]])
        self.assertEqual(r["num_text"], [[4], [0]])                # a numeric string is a number
        self.assertEqual(r["not_text"], [[1, 0], [0, 1]])          # empty text is false
        self.assertEqual(r["mixed"], [[0, 1, 1], [0, 1, 2]])       # the item field repeats along the entries
        self.assertEqual(r["sel_entries"], [[20, 30], [1, 2]])     # kept entries keep their source positions
        self.assertEqual(r["sel_item_out"], [[], []])              # an all-scalar false mask drops the item …
        self.assertEqual(r["sel_item_in"], [[10, 20, 30], None])   # … a true one keeps it whole (a plain array, no src)
        # #164: ">>" binning forms
        self.assertEqual(r["bin_1d"], {"expr": "SiPM.Result[3]", "name": "", "bins": {"nx": 20, "lo": 49, "hi": 53, "ny": None, "lo2": None, "hi2": None}})
        self.assertEqual(r["bin_2d"], {"expr": "y:x", "name": "h", "bins": {"nx": 30, "lo": 49, "hi": 53, "ny": 10, "lo2": 0, "hi2": 0.1}})
        self.assertEqual(r["bin_n"]["bins"]["nx"], 20)
        self.assertEqual((r["bin_name"]["name"], r["bin_name"]["bins"]), ("h", None))
        self.assertEqual((r["bin_blank"]["bins"]["lo"], r["bin_blank"]["bins"]["hi"]), (None, 53))
        self.assertEqual(r["bin_none"], {"expr": "a + b", "name": "", "bins": None})
        self.assertEqual(r["opt"], [{"m2": "heat"}, {"m1": "cum", "logy": True, "stats": False}, {}, "unknown option “foo” — hist cum line · scat line colz · logy liny nostats stats"])
        self.assertEqual(r["bin_bad"], ["binning: (nx), (nx,lo,hi), (nx,lo,hi,ny) or (nx,lo,hi,ny,lo2,hi2)", "binning: at least 2 bins", "binning: lo must be below hi"])

    def test_page_has_the_draw_box(self):
        html = self.client.get("/hw/dev/plot/T/").content.decode()
        # ROOT's Draw(expression, selection, option) on the Data pane, above the key pickers: two text areas and an option line
        self.assertNotIn('data-tab="expr"', html)
        self.assertIn("ROOT's <code>TTree::Draw(expression, selection, option)</code> over the keys below.", html)
        self.assertLess(html.index('<textarea id="draw"'), html.index('id="xfield"'))
        self.assertIn('<textarea id="draw" rows="2" placeholder="y : x >> (nx,lo,hi)   e.g. SiPM.Result[3]  or  Result_Err[3] : Result[3]"', html)
        self.assertIn('<input type="text" id="dopt" placeholder="hist · cum · line · scat · colz · logy · nostats"', html)
        self.assertIn('<button type="button" class="pl-btn primary sm" id="draw-apply">Draw</button><button type="button" class="pl-btn sm" id="draw-help" title="Draw syntax">? syntax</button>', html)
        self.assertIn('if (o.m1) $("mode1d").value = o.m1;', PLOT_JS)
        self.assertIn('$("logy").checked = !!o.logy; $("showstats").checked = o.stats !== false;', PLOT_JS)   # switches left out are off
        self.assertIn('return { scatter: "scat", line: "line", heat: "colz" }[$("mode2d").value] || "scat";', PLOT_JS)
        self.assertIn('if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); applyDraw(); }', PLOT_JS)
        self.assertIn('<div class="pl-pop" id="dpop" hidden>', html)
        self.assertIn("<b>y : x</b><span>two axes — the first is Y, as in ROOT</span>", html)
        self.assertIn('/docs/plots/#draw" target="_blank" rel="noopener" style="margin-left: auto;">Full guide with examples &#x2197;</a></div>', html)   # the popover's foot opens the full guide in a new tab
        # an expression is a virtual key: "=expr" in the series' x / y, restored from the hash, evaluated per item, fetched by its identifiers
        self.assertIn('function isExpr(p) { return typeof p === "string" && p.charAt(0) === "="; }', PLOT_JS)
        self.assertIn('s.x = h.x && (isExpr(h.x) || acc.has(h.x)) ? h.x : ""; s.y = h.y && (isExpr(h.y) || acc.has(h.y)) ? h.y : "";', PLOT_JS)
        self.assertIn("var arr = isExpr(p) ? exprValues(item, p, s) : slotValues(item, p, idxOf(p, s), s);", PLOT_JS)
        self.assertIn("function seriesSpecs(s) {", PLOT_JS)
        self.assertIn("function pairValues(it, s) {", PLOT_JS)        # X–Y pairing by entry when an expression dropped some
        self.assertIn("items = newItems; pathCounts = counts; specDims = {}; exprCache = {};", PLOT_JS)
        self.assertIn('if (exprErr(a)) { clear("Draw: " + exprErr(a)); return; }', PLOT_JS)
        self.assertIn("function keyAsName(p, ix) {", PLOT_JS)         # the box shows a picked key as a name with its pins
        self.assertIn('got[ax] = toks.length === 1 && toks[0].t === "id" && m.ids.length === 1 ? { p: m.ids[0].p, ix: m.ids[0].ix } : { p: "=" + side[ax], ix: null };', PLOT_JS)
        # #163: the Select box — per-entry selection stored as `sel` on the series, applied to every value the series reads
        self.assertIn('<textarea id="dsel" rows="2" placeholder="entries to keep, e.g. Result_Err[3] &lt; 0.1 &amp;&amp; $serial =~ \'HPK\'"', html)
        self.assertIn('<span class="pl-err" id="sel-err" hidden></span>', html)
        self.assertIn("<b>select</b><span>a second expression, true (non-zero) keeps the entry", html)
        self.assertIn("if (s.sel && !exprMeta(s.sel).err) arr = exprSelect(arr, exprValues(item, s.sel, s));", PLOT_JS)
        self.assertIn('function idValues(item, id, s) { return id.attr ? [item[id.attr] === null || item[id.attr] === undefined ? "" : item[id.attr]] : slotValues(item, id.p, id.ix, s); }', PLOT_JS)
        self.assertIn("sel: s.sel || undefined,", PLOT_JS)
        self.assertIn('s.sel = typeof h.sel === "string" ? h.sel : "";', PLOT_JS)
        self.assertIn('if (s.sel) { var ms = exprMeta(s.sel); if (!ms.err) ms.ids.forEach(function (id) { if (!id.attr) out.push({ p: id.p, ix: id.ix }); }); }', PLOT_JS)
        self.assertIn('function selErr(s) { return s.sel && exprMeta(s.sel).err ? "selection: " + exprMeta(s.sel).err : null; }', PLOT_JS)
        # #164: ">>" sets Bins, the range boxes and the 2D Y bins; the box shows it back; the hash carries the Y bins as `by`
        self.assertIn("var bn; try { bn = exprBinning(text); } catch (e) { return fail(e.message); }", PLOT_JS)
        self.assertIn('$("bins").value = b.nx; set("xmin", b.lo); set("xmax", b.hi);', PLOT_JS)
        self.assertIn("binsY = b.ny && b.ny !== b.nx ? b.ny : null;", PLOT_JS)
        self.assertIn("function binSuffix(s) {", PLOT_JS)
        self.assertIn('by = binSetup(pts.map(function (q) { return q.y; }), binsY, "y")', PLOT_JS)
        # an explicit range is the binning range: edges follow it, entries outside fall in no bin
        self.assertIn('var lo = r[0] !== null ? r[0] : Math.min.apply(null, nums), hi = r[1] !== null ? r[1] : Math.max.apply(null, nums)', PLOT_JS)
        self.assertIn("nums.forEach(function (v) { if (v < lo || v > hi) return;", PLOT_JS)
        self.assertIn("by: binsY || undefined,", PLOT_JS)
        self.assertIn("<b>binning</b><span><code>expr &gt;&gt; (nx)</code>", html)

    def test_page_has_a_serial_filter(self):
        # Chao 2026-09-17: a distribution over a PID range should take HPK.* boards only, not SMB.*
        html = self.client.get("/hw/dev/plot/T/").content.decode()
        self.assertIn('<div class="pl-f"><span>Serial</span><input type="text" id="snf" placeholder="contains / regex"', html)
        self.assertIn('var snf = (s.sn || "").trim(), snre = null;', PLOT_JS)
        self.assertIn('if (snf && !(snre ? snre.test(it.serial || "") : (it.serial || "").toLowerCase().indexOf(snf.toLowerCase()) >= 0)) return false;', PLOT_JS)
        self.assertIn("sn: s.sn || undefined,", PLOT_JS)         # rides in the hash …
        self.assertIn('s.sn = h.sn || "";', PLOT_JS)              # … and comes back from it
        self.assertIn('$("snf").addEventListener("input", function () { S().sn = $("snf").value; changed(); });', PLOT_JS)

    def test_page_has_tolerance_limits(self):
        # Anselmo 2026-09-22: SiPMs beyond the supercell's tolerance should show at a glance — two dotted
        # lines (low / high) on the value axis, the axis stretched to show them; they ride in the hash as `lim`
        html = self.client.get("/hw/dev/plot/T/").content.decode()
        self.assertIn('<span>Limits</span><div class="pl-range"><input type="number" step="any" id="limmin" placeholder="low"><span>–</span><input type="number" step="any" id="limmax" placeholder="high"></div>', html)
        self.assertIn('var limitLines = { id: "limitLines",', PLOT_JS)
        self.assertIn('if (sc.options.min === undefined && lo - pad < sc.min) sc.min = lo - pad;', PLOT_JS)   # a range box or a zoom pins the axis
        self.assertIn('ctx.setLineDash([3, 3]);', PLOT_JS)
        self.assertIn('cfg.plugins = [statsBox, limitLines];', PLOT_JS)
        self.assertIn('var lim = withLimits(o1, "x", numsOf[used.indexOf(a)] || []), ovx = ov.map(function (q) { return q.x; });', PLOT_JS)   # histogram: vertical, in the X range
        self.assertIn('lim: rangeOf("lim") || undefined,', PLOT_JS)
        self.assertIn('[["x", "xr"], ["y", "yr"], ["lim", "lim"]].forEach(', PLOT_JS)
        # Anselmo 2026-09-22 (2): the limits may be offsets from the highlighted series' mean, an amount or a percentage; `limm` in the hash
        self.assertIn('<select id="limmode" title="absolute values, or offsets from the highlighted series\' mean"><option value="abs">absolute</option><option value="mean">mean ± value</option><option value="pct">mean ± %</option></select>', html)
        self.assertIn('var x = mode === "pct" ? m * (1 + sign * d / 100) : m + sign * d;', PLOT_JS)
        self.assertIn('withLimits(oL, "y", numsOf[used.indexOf(a)] || []);', PLOT_JS)
        self.assertIn('limm: $("limmode").value !== "abs" ? $("limmode").value : undefined,', PLOT_JS)
        self.assertIn('$("limmode").value = ["mean", "pct"].indexOf(cfg.limm) >= 0 ? cfg.limm : "abs"; limitPlaceholders();', PLOT_JS)

    def test_page_takes_a_pasted_list_of_pids_or_serials(self):
        # Chao 2026-09-17: PID / Serial filters from a pasted list — resolved to an exact PID filter
        html = self.client.get("/hw/dev/plot/T/").content.decode()
        self.assertIn('<div class="pl-f"><span>List</span><button type="button" class="pl-btn sm" id="list-btn"', html)
        self.assertIn('<dialog id="list-dlg" class="pl-dlg">', html)
        self.assertIn('function listEntries() { return lta.value.split(/[\\s,;]+/).filter(Boolean); }', PLOT_JS)
        self.assertIn('s.pid = listEntries().length ? pidAlternation(r.pids) : ""; s.item = "";', PLOT_JS)
        self.assertIn('" · no item: " + r.missing.join(", ")', PLOT_JS)
        # #168: a serial several items carry selects all of them — named with its PIDs (Chao)
        self.assertIn('if (s.length > 1) shared.push(id + " → " + s.join(", "));', PLOT_JS)
        self.assertIn('" · shared serial, all taken: " + r.shared.join("; ")', PLOT_JS)
        self.assertIn('" · shared serial, all taken: " + rid.shared.join("; ")', PLOT_JS)
        self.assertIn("var m = /^\\^\\((.*)\\)\\$$/.exec(S().pid || \"\");", PLOT_JS)

    def test_page_carries_the_test_endpoints(self):
        html = self.client.get("/hw/dev/plot/T/").content.decode()
        self.assertIn('data-sources-url="/hw/dev/plot/T/sources/"', html)
        self.assertIn('data-tests-base-url="/hw/dev/plot/T/tests"', html)
        self.assertIn('data-tests-sync-url="/hw/dev/plot/T/test-data/"', html)

    def test_sync_view_streams_and_takes_mode(self):
        with mock.patch("explore.views.mint_for", return_value="bearer"), \
             mock.patch("explore.views.events.sync_test_data", return_value=iter(["hello\n"])) as m:
            resp = self.client.post("/hw/dev/plot/T/test-data/", {"mode": "full"})
            body = b"".join(resp.streaming_content)     # the generator runs on consumption
        self.assertEqual(body, b"hello\n")
        self.assertEqual(m.call_args.kwargs, {"instance": "dev", "mode": "full"})


class ValuesCapAndFilterTest(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("v", "v@v.io", "pw"))
        _td("dev", "T", "T-00001", 5, "A", {"IV": {"I": [1, 2, 3], "V": [10, 20, 30]}, "R": 5})
        _td("dev", "T", "T-00002", 5, "A", {"IV": {"I": [4, 5]}, "R": 6})

    def test_keys_report_value_counts_for_arrays(self):
        k = self.client.get("/hw/dev/plot/T/tests/5/keys/").json()
        by = {tuple(x["path"]): x for x in k["keys"]}
        self.assertEqual((by[("IV", "I")]["n"], by[("IV", "I")]["nv"]), (2, 5))
        self.assertEqual((by[("R",)]["n"], by[("R",)]["nv"]), (2, 2))
        self.assertEqual(k["max_values"], plotting.MAX_VALUES)

    def test_pid_filter_regex_then_substring_fallback(self):
        v = self.client.get("/hw/dev/plot/T/tests/5/values/", {"key": json.dumps(["IV", "I"]), "pid": "^T-00002$"}).json()
        self.assertEqual(v, {"values": {"T-00002": [4, 5]}})
        v = self.client.get("/hw/dev/plot/T/tests/5/values/", {"key": json.dumps(["IV", "I"]), "pid": "0001("}).json()  # bad regex → substring
        self.assertEqual(list(v["values"]), [])
        v = self.client.get("/hw/dev/plot/T/tests/5/values/", {"key": json.dumps(["IV", "I"]), "pid": "0001"}).json()
        self.assertEqual(list(v["values"]), ["T-00001"])

    def test_pid_range_syntax(self):
        # #155: numeric-suffix ranges, full form, open ends; a lone ".." is not a range
        self.assertEqual(plotting.pid_range("120..6000"), ("00120", "06000"))
        self.assertEqual(plotting.pid_range(" D00400300001-00120 .. 06000 "), ("00120", "06000"))
        self.assertEqual(plotting.pid_range("00120.."), ("00120", None))
        self.assertEqual(plotting.pid_range("..06000"), (None, "06000"))
        for bad in ("..", "a..b", "0001", "^T-00002$", "", None):
            self.assertIsNone(plotting.pid_range(bad), bad)
        get = lambda pid: list(self.client.get("/hw/dev/plot/T/tests/5/values/",
                                               {"key": json.dumps(["IV", "I"]), "pid": pid}).json()["values"])
        self.assertEqual(get("00002..00002"), ["T-00002"])
        self.assertEqual(get("2..2"), ["T-00002"])
        self.assertEqual(get("..00001"), ["T-00001"])
        self.assertEqual(get("00001.."), ["T-00001", "T-00002"])
        self.assertEqual(get("00003.."), [])

    def test_cap_returns_413_and_a_filter_gets_under_it(self):
        with mock.patch.object(plotting, "MAX_VALUES", 4):
            r = self.client.get("/hw/dev/plot/T/tests/5/values/", {"key": json.dumps(["IV", "I"])})
            self.assertEqual(r.status_code, 413)
            self.assertIn("exceed", r.json()["error"])
            r = self.client.get("/hw/dev/plot/T/tests/5/values/", {"key": json.dumps(["IV", "I"]), "pid": "00001"})
            self.assertEqual(r.json(), {"values": {"T-00001": [1, 2, 3]}})
