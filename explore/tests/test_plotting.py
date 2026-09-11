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
        self.assertIn(f'data-key="dev/{PTID}/specs"', html)
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
