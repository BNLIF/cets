"""Tests for the generic part detail page (ADR-0014).

The engine (parts.py) and the view for a *non-shipping* part — the shipping-box
case is exercised in test_shipments.py (is_shipping=True). HWDB fetch is mocked.

    python manage.py test explore
"""

from __future__ import annotations

import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from explore import navigation, parts
from explore.models import HierarchyNode as H
from explore.models import HwdbComponentEvent
from hwdb.fnal.bearer import FnalLinkRequired


class SpecSectionsTest(TestCase):
    def test_scalars_fold_into_one_specifications_card(self):
        blob = {"Operating Voltage": "48V", "Channels": 64, "Notes": ""}
        secs = parts.spec_sections(blob)
        self.assertEqual([s["title"] for s in secs], ["Specifications"])
        labels = {f["label"]: f["value"] for f in secs[0]["fields"]}
        self.assertEqual(labels, {"Operating Voltage": "48V", "Channels": "64"})

    def test_nested_keys_become_their_own_cards_with_image_peeling(self):
        blob = {
            "Calibration": [{"gain": "1.2", "Image ID for the trace": "img-7"}],
            "Serial scan": {"barcode": "ABC123"},
        }
        secs = {s["title"]: s for s in parts.spec_sections(blob)}
        self.assertEqual(secs["Calibration"]["fields"], [{"label": "gain", "value": "1.2"}])
        self.assertEqual(secs["Calibration"]["attachments"], [{"label": "trace", "image_id": "img-7"}])
        self.assertEqual(secs["Serial scan"]["fields"], [{"label": "barcode", "value": "ABC123"}])

    def test_empty_blob(self):
        self.assertEqual(parts.spec_sections(None), [])

    def test_bare_list_blob_folds_into_one_card(self):
        secs = parts.spec_sections([{"a": "1"}, {"b": "2"}])
        self.assertEqual(secs[0]["title"], "Specifications")
        self.assertEqual({f["label"]: f["value"] for f in secs[0]["fields"]},
                         {"a": "1", "b": "2"})

    def test_non_dict_blob_is_ignored(self):
        self.assertEqual(parts.spec_sections("a string"), [])


class TestSummaryTest(TestCase):
    def test_latest_record_per_type_wins(self):
        recs = [
            {"test_type": "HV", "status": "Pass", "created": "2026-01-01T00:00:00"},
            {"test_type": "HV", "status": "Fail", "created": "2026-05-01T00:00:00"},  # newer
            {"test_type": "Cold", "status": "Pass", "created": "2026-03-01T00:00:00"},
        ]
        summary = {r["test_type"]: r for r in parts.test_summary(recs)}
        self.assertEqual(summary["HV"]["status"], "Fail")          # newest HV
        self.assertEqual([r["test_type"] for r in parts.test_summary(recs)], ["Cold", "HV"])

    def test_handles_missing_fields(self):
        self.assertEqual(parts.test_summary(None), [])

    def test_unwraps_nested_test_type_and_status_refs(self):
        # HWDB returns test_type/status as {id, name} refs for some parts —
        # must not be used as an unhashable dict key.
        recs = [{"test_type": {"id": 7, "name": "HV"},
                 "status": {"name": "Pass"}, "created": "2026-01-01T00:00:00"}]
        summary = parts.test_summary(recs)
        self.assertEqual(summary[0]["test_type"], "HV")
        self.assertEqual(summary[0]["status"], "Pass")


class EnrichTestDataTest(TestCase):
    """The list endpoint omits the test oid + status; we backfill them from the
    per-type endpoint so the FNAL data link works."""

    def _api(self):
        api = mock.MagicMock()
        api.get_component.return_value = {"data": {"specifications": []}}
        api.get_locations.return_value = {"data": []}
        api.get_subcomponents.return_value = {"data": []}
        api.get_images.return_value = {"data": []}
        api.get_test_types.return_value = {"data": [{"name": "HV QC Test", "id": 42}]}

        def get_tests(pid, test_type_id=None, history=False):
            if test_type_id is None:  # list endpoint — no id, no status, no files
                return {"data": [{"test_type": {"name": "HV QC Test"},
                                  "created": "2026-05-29T00:00:00", "comments": "Cold"}]}
            return {"data": [{"id": 15023, "status": {"name": "Passed"},
                              "created": "2026-05-29T00:00:00",
                              "test_data": {"DATA": {"gain": 1.2}},
                              "images": [{"image_id": "z", "image_name": "hv.csv"}]}]}
        api.get_tests.side_effect = get_tests
        return api

    def test_oid_status_and_has_data_backfilled_from_per_type(self):
        d = parts.part_detail(self._api(), "D08100100003-00226", is_shipping=False)
        t = d["tests"][0]
        self.assertEqual(t["test_id"], 15023)    # → FNAL component_test data link
        self.assertEqual(t["test_type_id"], 42)  # → our test_data JSON download
        self.assertEqual(t["status"], "Passed")  # real status, not the empty list value
        self.assertTrue(t["has_data"])           # embedded files → show the link
        self.assertTrue(t["has_test_data"])      # test_data present → JSON download

    def test_no_files_means_no_data_link(self):
        api = self._api()

        def get_tests(pid, test_type_id=None, history=False):
            if test_type_id is None:
                return {"data": [{"test_type": {"name": "HV QC Test"},
                                  "created": "2026-05-29T00:00:00"}]}
            return {"data": [{"id": 15023, "status": {"name": "Passed"},
                              "created": "2026-05-29T00:00:00"}]}  # no images
        api.get_tests.side_effect = get_tests
        t = parts.part_detail(api, "D08100100003-14194", is_shipping=False)["tests"][0]
        self.assertEqual(t["test_id"], 15023)
        self.assertFalse(t["has_data"])          # no files → link hidden


class PartFactsTest(TestCase):
    def test_skips_blanks_and_unwraps_named_refs(self):
        comp = {
            "serial_number": "SN-9",
            "component_type": {"name": "ColdADC"},
            "institution": {"name": "BNL"},
            "manufacturer": "",                 # blank → skipped
            "status": {"id": 3, "name": "QA/QC Tests - Passed All"},  # nested ref
            "created": "2026-04-02T11:00:00",
            "creator": {"name": "Chao Zhang"},  # nested ref
        }
        facts = {f["label"]: f["value"] for f in parts.part_facts(comp)}
        self.assertEqual(facts["Serial number"], "SN-9")
        self.assertEqual(facts["Type"], "ColdADC")
        self.assertEqual(facts["Institution"], "BNL")
        self.assertEqual(facts["Status"], "QA/QC Tests - Passed All")  # name only, not the dict
        self.assertEqual(facts["Created"], "2026-04-02")
        self.assertEqual(facts["Created by"], "Chao Zhang")  # name only, not the dict
        self.assertNotIn("Manufacturer", facts)

    def test_qc_flags_render_yes_no_and_skip_absent(self):
        # False is meaningful (→ "No"); only a missing field is skipped.
        comp = {"serial_number": "SN-9", "is_installed": False,
                "qaqc_uploaded": True}  # certified_qaqc absent
        facts = {f["label"]: f["value"] for f in parts.part_facts(comp)}
        self.assertEqual(facts["Installed"], "No")
        self.assertEqual(facts["QA/QC Uploaded"], "Yes")
        self.assertNotIn("Certified QA/QC", facts)


class AssemblyTreeTest(TestCase):
    """parts.assembly_children — one level of the assembly tree with QC status
    (ADR-0015)."""

    def _api(self, status_by_pid):
        api = mock.MagicMock()
        api.get_subcomponents.return_value = {"data": [
            {"part_id": "P1", "type_name": "FEMB", "functional_position": "Slot 1",
             "operation": "mount"},
            {"part_id": "P2", "type_name": "FEMB", "functional_position": "Slot 2",
             "operation": "unmount"},  # excluded by current_manifest
        ]}
        api.get_component.side_effect = lambda pid: {"data": status_by_pid.get(pid, {})}
        return api

    def test_children_carry_status(self):
        api = self._api({"P1": {"status": {"name": "Passed"}}})
        kids = parts.assembly_children(api, "B1")
        self.assertEqual([k["part_id"] for k in kids], ["P1"])     # unmount filtered
        self.assertEqual(kids[0]["status"], "Passed")              # nested ref unwrapped

    def test_failed_status_fetch_degrades_to_none(self):
        api = self._api({})
        api.get_component.side_effect = RuntimeError("502")
        self.assertIsNone(parts.assembly_children(api, "B1")[0]["status"])

    def test_status_fetch_capped(self):
        api = mock.MagicMock()
        api.get_subcomponents.return_value = {"data": [
            {"part_id": f"P{i}", "operation": "mount"} for i in range(parts._STATUS_FETCH_CAP + 5)]}
        api.get_component.return_value = {"data": {"status": "Passed"}}
        kids = parts.assembly_children(api, "B1")
        self.assertEqual(api.get_component.call_count, parts._STATUS_FETCH_CAP)  # capped
        self.assertEqual(kids[0]["status"], "Passed")
        self.assertIsNone(kids[-1]["status"])  # beyond the cap → listed, no status


class AssemblyViewTest(TestCase):
    """The lazy-expand endpoint /hw/assembly/<pid>/."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("a", "a@a.io", "pw")
        self.client.force_login(self.user)

    def test_returns_children_with_part_urls(self):
        api = mock.MagicMock()
        api.get_subcomponents.return_value = {"data": [
            {"part_id": "C1", "type_name": "ColdADC", "operation": "mount"}]}
        api.get_component.return_value = {"data": {"status": "Available"}}
        with mock.patch("explore.views.mint_for", return_value="bearer"), \
             mock.patch("explore.views.FnalDbApiClient", return_value=api):
            resp = self.client.get("/hw/assembly/B1/")
        self.assertEqual(resp.status_code, 200)
        child = json.loads(resp.content)["children"][0]
        self.assertEqual(child["part_id"], "C1")
        self.assertEqual(child["url"], "/hw/part/C1/")
        self.assertEqual(child["status"], "Available")

    def test_fnal_link_required_returns_409(self):
        with mock.patch("explore.views.mint_for", side_effect=FnalLinkRequired()):
            resp = self.client.get("/hw/assembly/B1/")
        self.assertEqual(resp.status_code, 409)


class PartViewTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("p", "p@p.io", "pw")
        self.client.force_login(self.user)
        self.url = "/hw/part/D05700600099-00007/"  # not a curated shipping type

    def _api(self):
        api = mock.MagicMock()
        api.get_component.return_value = {"data": {
            "serial_number": "SN-7", "status": "Passed",
            "component_type": {"name": "ColdADC"},
            "specifications": [{"DATA": {"Channels": 64}}]}}
        api.get_locations.return_value = {"data": []}            # most parts have none
        api.get_subcomponents.return_value = {"data": []}
        api.get_images.return_value = {"data": [{"image_id": "i9", "image_name": "photo.jpg"}]}
        api.get_test_types.return_value = {"data": [{"name": "RoomT", "id": 7}]}

        def get_tests(pid, test_type_id=None, history=False):
            if test_type_id is None:
                return {"data": [{"test_type": {"name": "RoomT"},
                                  "created": "2026-02-02T00:00:00"}]}
            return {"data": [{"id": 15023, "status": {"name": "Pass"},
                              "created": "2026-02-02T00:00:00",
                              "images": [{"image_id": "z", "image_name": "t.csv"}]}]}
        api.get_tests.side_effect = get_tests
        return api

    def test_a_failing_aux_endpoint_does_not_break_the_page(self):
        # A part with no /tests (endpoint raises) must still render — the
        # section just degrades to empty, not a 502 (ADR-0014 hardening).
        api = self._api()
        api.get_tests.side_effect = RuntimeError("404 from HWDB")
        d = parts.part_detail(api, "X-1", is_shipping=False)
        self.assertEqual(d["tests"], [])
        self.assertEqual(d["facts"][0]["label"], "Serial number")  # rest still built

    def test_renders_generic_part(self):
        with mock.patch("explore.views.mint_for", return_value="bearer"), \
             mock.patch("explore.views.FnalDbApiClient", return_value=self._api()):
            resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("SN-7", body)             # item fact
        self.assertIn("RoomT", body)            # test summary
        self.assertIn("/view/images/component_test/15023", body)  # per-test data link to FNAL
        self.assertIn("photo.jpg", body)        # downloadable attachment
        self.assertIn("Specifications", body)   # generic spec card
        self.assertNotIn("In Transit", body)    # no shipping framing for a normal part

    def test_shipment_url_redirects_to_part(self):
        resp = self.client.get("/hw/shipment/D05700600099-00007/")
        self.assertEqual(resp.status_code, 301)
        self.assertEqual(resp["Location"], self.url)


class TestDataDownloadTest(TestCase):
    """Per-test test_data JSON download (the dashboard's test-data export)."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("td", "t@d.io", "pw")
        self.client.force_login(self.user)
        self.url = "/hw/test-data/D08100100003-00226/42/"

    def _api(self):
        api = mock.MagicMock()
        api.get_tests.return_value = {"data": [
            {"created": "2026-05-29T00:00:00", "test_data": {"DATA": {"gain": 1.2}}}]}
        return api

    def test_renders_test_data_as_inline_json_text(self):
        with mock.patch("explore.views.mint_for", return_value="bearer"), \
             mock.patch("explore.views.FnalDbApiClient", return_value=self._api()):
            resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "text/plain; charset=utf-8")
        self.assertNotIn("Content-Disposition", resp)        # inline, not a download
        self.assertEqual(json.loads(resp.content), {"DATA": {"gain": 1.2}})
        self.assertIn(b"\n", resp.content)                   # pretty-printed

    def test_fnal_link_required_returns_409(self):
        with mock.patch("explore.views.mint_for", side_effect=FnalLinkRequired()):
            resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 409)


def _comp_leaf(ptid="D05700600099"):
    """A synced non-shipping leaf under FD CE (so leaf_path_for resolves)."""
    sys, _ = H.objects.get_or_create(
        level=H.LEVEL_SYSTEM, system_id=81, subsystem_id=None, part_type_id="",
        defaults={"system_name": "FD CE", "name": "FD CE"})
    sub, _ = H.objects.get_or_create(
        level=H.LEVEL_SUBSYSTEM, system_id=81, subsystem_id=300, part_type_id="",
        defaults={"parent": sys, "system_name": "FD CE",
                  "subsystem_name": "ColdADC", "name": "ColdADC"})
    return H.objects.create(
        level=H.LEVEL_TYPE, parent=sub, system_id=81, system_name="FD CE",
        subsystem_id=300, subsystem_name="ColdADC", name="ColdADC",
        part_type_id=ptid, n_components=55,
        full_name="D.FD CE.ColdADC.ColdADC", tests_synced_at=timezone.now())


class LeafPartsTableTest(TestCase):
    """The paginated parts table on a synced component-type leaf page."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("lp", "l@p.io", "pw")
        self.client.force_login(self.user)
        self.leaf = _comp_leaf()
        for i in range(55):
            HwdbComponentEvent.objects.create(
                part_type_id=self.leaf.part_type_id,
                part_id=f"{self.leaf.part_type_id}-{i:05d}", created=timezone.now(),
                serial_number=f"SN-{i:05d}", created_by="Alex Wagner")
        self.url = navigation.leaf_path_for("prod", self.leaf.part_type_id)

    def test_lists_parts_paginated_50_with_part_links(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn("Components (55)", html)
        # 55 rows → 50 on page 1 (newest first), 5 on page 2.
        self.assertIn(f"/hw/part/{self.leaf.part_type_id}-00054/", html)  # row → part page
        self.assertIn('target="_blank"', html)                                 # opens new tab
        self.assertIn("SN-00054", html)                                        # serial column
        self.assertIn("<th>Serial number</th>", html)
        self.assertIn("<th>Created by</th>", html)                             # creator column
        self.assertIn("Alex Wagner", html)
        self.assertNotIn("<th>Created</th>", html)                             # created date dropped
        self.assertIn("Page 1 of 2", html)
        self.assertIn("Last »", html)                                          # first/last links
        self.assertIn("?page=2", html)                                         # Last → page 2
        self.assertNotIn(f"/hw/part/{self.leaf.part_type_id}-00000/", html)

    def test_second_page_has_first_and_prev_links(self):
        html = self.client.get(self.url + "?page=2").content.decode()
        self.assertIn("Page 2 of 2", html)
        self.assertIn(f"/hw/part/{self.leaf.part_type_id}-00000/", html)  # tail row
        self.assertIn("« First", html)
        self.assertIn('href="?page=1"', html)                                  # First → page 1

    def test_component_breakdown_panel_when_facets_present(self):
        # Mirror-only breakdown bar charts appear once components carry a facet.
        HwdbComponentEvent.objects.filter(part_type_id=self.leaf.part_type_id).update(
            status="QA/QC Passed", manufacturer="BNL")
        html = self.client.get(self.url).content.decode()
        self.assertIn("Component breakdown", html)
        self.assertIn('id="breakdown-config"', html)
        self.assertIn("QA/QC Passed", html)
        self.assertIn("BNL", html)


class SearchTest(TestCase):
    """Instant mirror search → component-type leaf or part page."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("sx", "s@x.io", "pw")
        self.client.force_login(self.user)
        self.leaf = _comp_leaf()  # ColdADC, D05700600099, under browsable FD CE
        HwdbComponentEvent.objects.create(
            part_type_id="D05700600099", part_id="D05700600099-00001",
            created=timezone.now(), serial_number="2502-18564")

    def test_page_renders(self):
        resp = self.client.get("/hw/search/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Advanced search")  # the future-seam note

    def test_api_finds_component_type_by_name_with_leaf_path(self):
        d = self.client.get("/hw/search/api/", {"q": "ColdADC"}).json()
        match = next(t for t in d["types"] if t["part_type_id"] == "D05700600099")
        self.assertTrue(match["path"])  # reachable leaf page

    def test_api_finds_mirrored_part_and_flags_direct_pid(self):
        d = self.client.get("/hw/search/api/", {"q": "D05700600099-00001"}).json()
        self.assertEqual(d["direct_part"], "D05700600099-00001")
        self.assertTrue(any(p["part_id"] == "D05700600099-00001" for p in d["parts"]))

    def test_api_finds_part_by_serial_number(self):
        d = self.client.get("/hw/search/api/", {"q": "2502-18564"}).json()
        match = next(p for p in d["parts"] if p["part_id"] == "D05700600099-00001")
        self.assertEqual(match["serial_number"], "2502-18564")

    def test_short_query_returns_empty(self):
        d = self.client.get("/hw/search/api/", {"q": "a"}).json()
        self.assertEqual(d, {"types": [], "parts": [], "direct_part": None})
