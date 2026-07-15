"""Tests for the Shipping checklist (issue #66): document uploads with the
Dashboard's comment strings, the SURF-route Shipping Checklist patch, and
the In-Transit location post. HWDB is mocked.

    python manage.py test explore
"""

from __future__ import annotations

from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from explore import checklists
from explore.models import BoxChecklist
from explore.models import HierarchyNode as H

BOX = "D00599800007-00128"
PAGE = f"/hw/dev/part/{BOX}/shipping/"

PRESHIP_SPEC = {"Pre-Shipping Checklist": [
    {"POC name": "POC Person"}, {"POC Email": ["poc@x.org"]},
    {"HTS code": "8543.70"}]}


def _leaf():
    return H.objects.create(
        instance="dev", level=H.LEVEL_TYPE, system_id=5, system_name="Z.Sandbox",
        subsystem_id=998, subsystem_name="HWDBUnitTest", name="Test Type 007",
        part_type_id="D00599800007", full_name="x",
        tests_synced_at=timezone.now(), shipments_synced_at=timezone.now())


def _api(spec=PRESHIP_SPEC):
    api = mock.MagicMock()
    api.get_component.return_value = {"data": {
        "status": {"id": 120, "name": "QA/QC Tests - Passed All"},
        "serial_number": "SN-1", "comments": "a box",
        "manufacturer": {"id": 7, "name": "Acme"},
        "specifications": [{"DATA": {**spec, "Existing": "kept"}}],
        "component_type": {"name": "Test Type 007"}}}
    api.get_subcomponents.return_value = {"data": [
        {"part_id": "D05700300001-00012", "type_name": "FEB",
         "functional_position": "FEB1", "operation": "mount"}]}
    api.get_locations.return_value = {"data": []}
    api.whoami.return_value = {"data": {"full_name": "Chao Zhang",
                                        "email": "chao@bnl.gov", "roles": []}}
    api.post_component_image.return_value = {"status": "OK", "image_id": "doc1"}
    api.patch_component.return_value = {"status": "OK"}
    api.post_location.return_value = {"status": "OK"}
    return api


def _mocked(api):
    return (mock.patch("explore.views.mint_for", return_value="bearer"),
            mock.patch("explore.views.FnalDbApiClient", return_value=api))


def _pdf(name):
    return SimpleUploadedFile(name, b"%PDF-1.4", content_type="application/pdf")


class ShippingEngineTest(TestCase):
    def test_service_type_from_preshipping_spec(self):
        self.assertEqual(checklists.shipping_service_type(PRESHIP_SPEC), "International")
        self.assertEqual(checklists.shipping_service_type(
            {"Pre-Shipping Checklist": [{"HTS code": None}]}), "Domestic")
        self.assertEqual(checklists.shipping_service_type({}), "Domestic")

    def test_poc_falls_back_to_hwdb_spec(self):
        name, email = checklists.poc_from(None, PRESHIP_SPEC)
        self.assertEqual((name, email), ("POC Person", "poc@x.org"))
        name, email = checklists.poc_from(
            {"PreShipping3": {"approver_name": "Local", "approver_email": "l@x.org"}},
            PRESHIP_SPEC)
        self.assertEqual((name, email), ("Local", "l@x.org"))

    def test_surf_checklist_dict_keys_verbatim(self):
        cl = BoxChecklist(instance="dev", part_id=BOX, workflow="shipping",
                          route="confirm_surf", state={
                              "Shipping2": {"bol_info": {"image_id": "b1"},
                                            "proforma_info": {"image_id": "p1"}},
                              "Shipping4": {"approval_info": {"image_id": "a1"},
                                            "approved_by": "FD Log",
                                            "approved_time": "2026-07-12 09:00",
                                            "confirm_attached_sheet": True,
                                            "confirm_insured": True}})
        d = checklists.build_shipping_checklist_dict(
            cl, {"system_name": "S", "system_id": 5, "subsystem_name": "SS",
                 "subsystem_id": 998, "part_type_name": "T",
                 "part_type_id": "D00599800007"}, "POC Person", "poc@x.org")
        self.assertEqual(d["Image ID for BoL"], "b1")
        self.assertEqual(d["FD Logistics team final approval (date in CST)"],
                         "2026-07-12 09:00")
        self.assertEqual(d["POC Email"], ["poc@x.org"])
        self.assertTrue(d["This shipment has been adequately insured for transit"])


class ShippingFlowTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("w", "w@w.io", "pw")
        self.client.force_login(self.user)
        _leaf()

    def _run_to_scene(self, api, scene):
        self.client.post(PAGE, {"action": "start", "route": "confirm_surf"})
        if scene >= 2:
            self.client.post(PAGE, {"action": "advance", "confirm_list": "on"})
        if scene >= 3:
            self.client.post(PAGE, {"action": "advance",
                                    "bol_file": _pdf("bol.pdf"),
                                    "proforma_file": _pdf("proforma.pdf")})
        if scene >= 4:
            self.client.post(PAGE, {"action": "advance",
                                    "confirm_email_contents": "on"})

    def test_document_uploads_use_dashboard_comments(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            self._run_to_scene(api, 3)
        comments = [c.kwargs["comments"] for c in api.post_component_image.call_args_list]
        self.assertEqual(comments, ["shipping_bol", "shipping_proforma"])
        names = [c.args[2] for c in api.post_component_image.call_args_list]
        self.assertRegex(names[0], rf"^{BOX}-shipping-bol-.*\.pdf$")
        cl = BoxChecklist.for_instance("dev").get(part_id=BOX)
        self.assertEqual(cl.state["Shipping2"]["bol_info"]["image_id"], "doc1")

    def test_missing_bol_blocks_surf_scene2(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            self._run_to_scene(api, 2)
            resp = self.client.post(PAGE, {"action": "advance"}, follow=True)
        self.assertIn("Bill of Lading", resp.content.decode())
        self.assertEqual(BoxChecklist.for_instance("dev").get(part_id=BOX).current_scene, 2)

    def test_scene4_patches_shipping_checklist(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            self._run_to_scene(api, 4)
            self.client.post(PAGE, {
                "action": "advance", "received_approval": "on",
                "approved_by": "FD Log", "approved_time": "2026-07-12T09:00",
                "confirm_attached_sheet": "on", "confirm_insured": "on",
                "approval_file": _pdf("appr.pdf")})
        payload = api.patch_component.call_args.args[1]
        data = payload["specifications"]["DATA"]
        self.assertEqual(data["Existing"], "kept")
        cl_map = {k: v for e in data["Shipping Checklist"] for k, v in e.items()}
        self.assertEqual(cl_map["POC name"], "POC Person")   # from the HWDB spec
        self.assertEqual(cl_map["Image ID for the final approval message"], "doc1")
        self.assertEqual(cl_map["FD Logistics team final approval (date in CST)"],
                         "2026-07-12 09:00")                 # T normalized to space

    def test_scene5_posts_in_transit_and_refreshes(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            self._run_to_scene(api, 4)
            self.client.post(PAGE, {
                "action": "advance", "received_approval": "on",
                "approved_by": "FD Log", "approved_time": "2026-07-12T09:00",
                "confirm_attached_sheet": "on", "confirm_insured": "on",
                "approval_file": _pdf("appr.pdf")})
            self.client.post(PAGE, {
                "action": "advance", "shipment_time": "2026-07-13T08:00",
                "comments": "off it goes", "affirm_shipment": "on"})
        api.post_location.assert_called_once_with(BOX, {
            "location": {"id": 0}, "arrived": "2026-07-13 08:00",
            "comments": "off it goes"})
        # scene 6 wraps up
        with m1, m2:
            self.client.post(PAGE, {"action": "advance"})
        cl = BoxChecklist.for_instance("dev").get(part_id=BOX)
        self.assertIsNotNone(cl.completed_at)

    def test_route_defaults_from_preshipping_run(self):
        BoxChecklist.objects.create(instance="dev", part_id=BOX,
                                    workflow="preshipping",
                                    route="confirm_non_surf", current_scene=8,
                                    completed_at=timezone.now())
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            self.client.post(PAGE, {"action": "start"})
        cl = BoxChecklist.for_instance("dev").get(part_id=BOX, workflow="shipping")
        self.assertEqual(cl.route, "confirm_non_surf")

    def test_non_surf_skips_patch_but_still_goes_in_transit(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            self.client.post(PAGE, {"action": "start", "route": "confirm_non_surf"})
            self.client.post(PAGE, {"action": "advance", "confirm_list": "on"})
            self.client.post(PAGE, {"action": "advance"})                  # 2: no docs needed
            self.client.post(PAGE, {"action": "advance"})                  # 3: no confirm needed
            self.client.post(PAGE, {"action": "advance"})                  # 4: no approval needed
            self.client.post(PAGE, {"action": "advance",
                                    "shipment_time": "2026-07-13T08:00",
                                    "affirm_shipment": "on"})              # 5
        api.patch_component.assert_not_called()
        api.post_location.assert_called_once()

    @override_settings(HWDB_WRITE_INSTANCES=["dev"])
    def test_prod_is_forbidden(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.get("/hw/part/D08120200001-00001/shipping/")
        self.assertEqual(resp.status_code, 403)
