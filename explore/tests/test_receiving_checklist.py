"""Tests for the Receiving checklist (issue #67): the arrival-location
fan-out to the box and every subcomponent, the detach patch that opens the
box, and the transshipping branch that keeps contents linked. HWDB is
mocked.

    python manage.py test explore
"""

from __future__ import annotations

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from explore import checklists
from explore.models import BoxChecklist
from explore.models import HierarchyNode as H

BOX = "D00599800007-00128"
PAGE = f"/hw/dev/part/{BOX}/receiving/"

PRESHIP_SPEC = {"Pre-Shipping Checklist": [
    {"POC name": "POC Person"}, {"POC Email": ["poc@x.org"]}]}

MANIFEST = [
    {"part_id": "D05700300001-00012", "type_name": "FEB",
     "functional_position": "FEB1"},
    {"part_id": "D05700300001-00013", "type_name": "FEB",
     "functional_position": "FEB2"},
]

PAYLOAD = {"location": {"id": 128}, "arrived": "2026-07-14 09:30",
           "comments": "arrived intact"}


def _leaf():
    return H.objects.create(
        instance="dev", level=H.LEVEL_TYPE, system_id=5, system_name="Z.Sandbox",
        subsystem_id=998, subsystem_name="HWDBUnitTest", name="Test Type 007",
        part_type_id="D00599800007", full_name="x",
        tests_synced_at=timezone.now(), shipments_synced_at=timezone.now())


def _api():
    api = mock.MagicMock()
    api.get_component.return_value = {"data": {
        "status": {"id": 120, "name": "QA/QC Tests - Passed All"},
        "serial_number": "SN-1", "comments": "a box",
        "manufacturer": {"id": 7, "name": "Acme"},
        "specifications": [{"DATA": PRESHIP_SPEC}],
        "component_type": {"name": "Test Type 007"}}}
    api.get_subcomponents.return_value = {"data": [
        {"part_id": m["part_id"], "type_name": m["type_name"],
         "functional_position": m["functional_position"], "operation": "mount"}
        for m in MANIFEST]}
    api.get_locations.return_value = {"data": []}
    api.get_institutions.return_value = {"data": [
        {"id": 128, "name": "Brookhaven National Laboratory",
         "country": {"code": "US"}}]}
    api.whoami.return_value = {"data": {"full_name": "Chao Zhang",
                                        "email": "chao@bnl.gov", "roles": []}}
    api.post_location.return_value = {"status": "OK"}
    api.patch_subcomponents.return_value = {"status": "OK"}
    return api


def _mocked(api):
    return (mock.patch("explore.views.mint_for", return_value="bearer"),
            mock.patch("explore.views.FnalDbApiClient", return_value=api))


def _cl(route="confirm_surf", state=None):
    return BoxChecklist(instance="dev", part_id=BOX, workflow="receiving",
                        route=route, state=state or {
                            "Receiving2": {"location": {"institution_id": 128,
                                                        "institution_name": "BNL"},
                                           "arrived": "2026-07-14 09:30",
                                           "comments": "arrived intact"}})


class ReceivingEngineTest(TestCase):
    def test_receive_box_fans_out_and_detaches(self):
        api = _api()
        err = checklists.receive_box(api, _cl(), MANIFEST)
        self.assertIsNone(err)
        posted = [c.args for c in api.post_location.call_args_list]
        self.assertEqual(posted, [(BOX, PAYLOAD),
                                  ("D05700300001-00012", PAYLOAD),
                                  ("D05700300001-00013", PAYLOAD)])
        api.patch_subcomponents.assert_called_once_with(BOX, {
            "component": {"part_id": BOX},
            "subcomponents": {"FEB1": None, "FEB2": None}})

    def test_transshipping_posts_box_only(self):
        api = _api()
        err = checklists.receive_box(api, _cl(route="confirm_transshipping"), MANIFEST)
        self.assertIsNone(err)
        api.post_location.assert_called_once_with(BOX, PAYLOAD)
        api.patch_subcomponents.assert_not_called()

    def test_empty_box_skips_detach(self):
        api = _api()
        err = checklists.receive_box(api, _cl(), [])
        self.assertIsNone(err)
        api.post_location.assert_called_once_with(BOX, PAYLOAD)
        api.patch_subcomponents.assert_not_called()

    def test_child_failure_reports_its_pid(self):
        api = _api()
        api.post_location.side_effect = [
            {"status": "OK"}, {"status": "ERROR", "data": "nope"}]
        err = checklists.receive_box(api, _cl(), MANIFEST)
        self.assertIn("D05700300001-00012", err)
        api.patch_subcomponents.assert_not_called()

    def test_arrival_email_verbatim(self):
        html = checklists.receiving_email_html(
            BOX, "POC Person", "poc@x.org", "Chao Zhang", "chao@bnl.gov",
            "Brookhaven National Laboratory", "2026-07-14 09:30")
        self.assertIn(f"Final Reciving checklist for shipment {BOX}", html)
        self.assertIn("has arrived at <b>Brookhaven National Laboratory</b>", html)
        self.assertIn("<b>July 14, 2026</b> at <b>09:30 AM</b> (Central Time)", html)


class ReceivingFlowTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("w", "w@w.io", "pw")
        self.client.force_login(self.user)
        _leaf()

    def _receive_scene2(self):
        return self.client.post(PAGE, {
            "action": "advance", "location_id": "128",
            "arrived": "2026-07-14T09:30", "comments": "arrived intact",
            "affirm_update": "on"})

    def test_full_run_detaches_and_completes(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            self.client.post(PAGE, {"action": "start", "route": "confirm_surf"})
            self.client.post(PAGE, {"action": "advance", "confirm_list": "on"})
            self._receive_scene2()
        posted = [c.args[0] for c in api.post_location.call_args_list]
        self.assertEqual(posted, [BOX, "D05700300001-00012", "D05700300001-00013"])
        self.assertEqual(api.post_location.call_args_list[0].args[1], PAYLOAD)
        api.patch_subcomponents.assert_called_once_with(BOX, {
            "component": {"part_id": BOX},
            "subcomponents": {"FEB1": None, "FEB2": None}})
        cl = BoxChecklist.for_instance("dev").get(part_id=BOX, workflow="receiving")
        self.assertEqual(cl.current_scene, 3)
        self.assertEqual(cl.state["Receiving2"]["location"],
                         {"institution_id": 128,
                          "institution_name": "Brookhaven National Laboratory"})
        with m1, m2:  # scene 3: POC email (fallback from the HWDB spec)
            resp = self.client.get(PAGE)
            self.assertIn("POC Person", resp.content.decode())
            self.client.post(PAGE, {"action": "advance",
                                    "confirm_email_contents": "on"})
        cl.refresh_from_db()
        self.assertIsNotNone(cl.completed_at)

    def test_missing_affirm_blocks_scene2(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            self.client.post(PAGE, {"action": "start", "route": "confirm_surf"})
            self.client.post(PAGE, {"action": "advance", "confirm_list": "on"})
            self.client.post(PAGE, {"action": "advance", "location_id": "128",
                                    "arrived": "2026-07-14T09:30"})
        api.post_location.assert_not_called()
        cl = BoxChecklist.for_instance("dev").get(part_id=BOX, workflow="receiving")
        self.assertEqual(cl.current_scene, 2)

    def test_write_failure_keeps_scene(self):
        api = _api()
        api.post_location.return_value = {"status": "ERROR", "data": "no such location"}
        m1, m2 = _mocked(api)
        with m1, m2:
            self.client.post(PAGE, {"action": "start", "route": "confirm_surf"})
            self.client.post(PAGE, {"action": "advance", "confirm_list": "on"})
            resp = self.client.post(PAGE, follow=True, data={
                "action": "advance", "location_id": "128",
                "arrived": "2026-07-14T09:30", "affirm_update": "on"})
        self.assertIn("no such location", resp.content.decode())
        cl = BoxChecklist.for_instance("dev").get(part_id=BOX, workflow="receiving")
        self.assertEqual(cl.current_scene, 2)
        api.patch_subcomponents.assert_not_called()

    def test_transshipping_flow_keeps_children(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            self.client.post(PAGE, {"action": "start", "route": "confirm_transshipping"})
            self.client.post(PAGE, {"action": "advance", "confirm_list": "on"})
            self._receive_scene2()
        api.post_location.assert_called_once_with(BOX, PAYLOAD)
        api.patch_subcomponents.assert_not_called()

    def test_route_defaults_from_shipping_run(self):
        BoxChecklist.objects.create(instance="dev", part_id=BOX,
                                    workflow="shipping",
                                    route="confirm_non_surf", current_scene=6,
                                    completed_at=timezone.now())
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            self.client.post(PAGE, {"action": "start"})
        cl = BoxChecklist.for_instance("dev").get(part_id=BOX, workflow="receiving")
        self.assertEqual(cl.route, "confirm_non_surf")

    @override_settings(HWDB_WRITE_INSTANCES=["dev"])
    def test_prod_is_forbidden(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.get("/hw/part/D08120200001-00001/receiving/")
        self.assertEqual(resp.status_code, 403)
