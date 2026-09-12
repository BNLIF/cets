"""Type-wide Plot view (#144): the live specifications sweep and its two views.

    python manage.py test explore.tests.test_plotting
"""

from __future__ import annotations

import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from explore import plotting
from explore.models import HierarchyNode as H, HwdbComponentEvent
from hwdb.fnal.bearer import FnalLinkRequired

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
        by = {tuple(x["path"]): x for x in self.client.get("/hw/dev/plot/T/tests/5/keys/").json()["keys"]}
        self.assertEqual(by[("TR", "Loc", "I")]["dims"], [{"seg": "TR", "n": 2}, {"seg": "Loc", "n": 2}, {"seg": "I", "n": 2}])
        self.assertNotIn("dims", by[("R",)])                                    # a scalar has no shape
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
