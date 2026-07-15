"""Tests for the Pre-Shipping checklist (issue #65): the scene engine's
Dashboard-matching validation, the byte-for-byte spec patch, and the
DB-backed resumable flow. HWDB is mocked.

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
PAGE = f"/hw/dev/part/{BOX}/preship/"


class _Post(dict):
    def get(self, k, d=None):
        return super().get(k, d)

    def getlist(self, k):
        v = super().get(k)
        return v if isinstance(v, list) else ([v] if v else [])


def _leaf():
    return H.objects.create(
        instance="dev", level=H.LEVEL_TYPE, system_id=5, system_name="Z.Sandbox",
        subsystem_id=998, subsystem_name="HWDBUnitTest", name="Test Type 007",
        part_type_id="D00599800007", full_name="x",
        tests_synced_at=timezone.now(), shipments_synced_at=timezone.now())


def _cl(route="confirm_surf", state=None, scene=1):
    return BoxChecklist.objects.create(
        instance="dev", part_id=BOX, workflow="preshipping", route=route,
        current_scene=scene, state=state or {})


def _api():
    api = mock.MagicMock()
    api.get_component.return_value = {"data": {
        "status": {"id": 120, "name": "QA/QC Tests - Passed All"},
        "certified_qaqc": True, "qaqc_uploaded": True,
        "serial_number": "SN-1", "comments": "a box",
        "manufacturer": {"id": 7, "name": "Acme"},
        "specifications": [{"DATA": {"Existing": "kept"}, "_meta": {"v": 1}}],
        "component_type": {"name": "Test Type 007"}}}
    api.get_images.return_value = {"data": [
        {"image_id": "es1", "image_name": f"ExecutiveSummary_{BOX}_x.pdf",
         "created": "2026-07-11T00:00:00", "creator": {"name": "Chao Zhang"}}]}
    api.get_subcomponents.return_value = {"data": [
        {"part_id": "D05700300001-00012", "type_name": "Analog Front End Board",
         "functional_position": "FEB1", "operation": "mount"}]}
    api.get_locations.return_value = {"data": []}
    api.whoami.return_value = {"data": {"full_name": "Chao Zhang", "roles": []}}
    api.get_qrcode_response.side_effect = RuntimeError("no qr in tests")
    api.post_component_image.return_value = {"status": "OK", "image_id": "sheet9"}
    api.patch_component.return_value = {"status": "OK"}
    return api


def _mocked(api):
    return (mock.patch("explore.views.mint_for", return_value="bearer"),
            mock.patch("explore.views.FnalDbApiClient", return_value=api))


SCENE_DATA = {
    2: {"qa_rep_name": "QA Rep", "qa_rep_email": "qa@x.org, qa2@x.org",
        "test_info": "RoomT QC"},
    3: {"approver_name": "POC", "approver_email": "poc@x.org"},
    4: {"shipping_service_type": "International", "hts_code": "8543.70",
        "shipment_origin": "BNL", "shipment_destination": "SURF",
        "dimension": "1x1x1 m", "weight": "40 kg"},
    5: {"freight_forwarder": "FF Inc", "mode_of_transportation": "ground",
        "expected_arrival_time": "2026-08-01"},
    6: {"confirm_email_contents": "on"},
    7: {"received_acknowledgement": "on", "acknowledged_by": "FD Log",
        "acknowledged_time": "2026-07-12 09:00", "damage_status": "no damage",
        "damage_description": ""},
}


class SceneValidationTest(TestCase):
    def test_gate_scene_needs_confirmation(self):
        _d, err = checklists.clean_scene(1, True, _Post())
        self.assertIn("Confirm", err)
        _d, err = checklists.clean_scene(1, True, _Post(confirm_list="on"))
        self.assertIsNone(err)

    def test_surf_requires_dimension_and_weight(self):
        post = _Post({**SCENE_DATA[4], "dimension": "", "weight": ""})
        _d, err = checklists.clean_scene(4, True, post)
        self.assertIn("Dimension and weight", err)
        _d, err = checklists.clean_scene(4, False, post)  # non-SURF: fine
        self.assertIsNone(err)

    def test_international_requires_hts(self):
        post = _Post({**SCENE_DATA[4], "hts_code": ""})
        _d, err = checklists.clean_scene(4, False, post)
        self.assertIn("HTS", err)

    def test_damage_requires_description(self):
        post = _Post({**SCENE_DATA[7], "damage_status": "damage"})
        _d, err = checklists.clean_scene(7, True, post)
        self.assertIn("damage", err)

    def test_transport_optional_for_non_surf(self):
        _d, err = checklists.clean_scene(5, False, _Post())
        self.assertIsNone(err)
        _d, err = checklists.clean_scene(5, True, _Post())
        self.assertIn("required for SURF", err)


class PatchBuildTest(TestCase):
    def _surf_checklist(self):
        state = {f"PreShipping{k}": v for k, v in
                 [("2", SCENE_DATA[2]), ("3", SCENE_DATA[3]),
                  ("4a", SCENE_DATA[4]), ("4b", SCENE_DATA[5]),
                  ("6", {**SCENE_DATA[7], "received_acknowledgement": True})]}
        return BoxChecklist(instance="dev", part_id=BOX, workflow="preshipping",
                            route="confirm_surf", state=state)

    def test_surf_dict_matches_dashboard_keys_verbatim(self):
        info = {"system_name": "S", "system_id": 5, "subsystem_name": "SS",
                "subsystem_id": 998, "part_type_name": "T", "part_type_id": "D00599800007",
                "subcomponents": {"0": {"Sub-component PID": "P-1",
                                        "Component Type Name": "FEB",
                                        "Functional Position Name": "FEB1"}}}
        d = checklists.build_checklist_dict(self._surf_checklist(), info, "img7")
        self.assertEqual(d["QA Rep Email"], ["qa@x.org", "qa2@x.org"])  # split list
        self.assertEqual(d["FD Logistics team acknoledgement (name)"], "FD Log")  # typo kept
        self.assertEqual(d["Visual Inspection (YES = no damage)"], "YES")
        self.assertEqual(d["HTS code"], "8543.70")       # International keeps it
        self.assertEqual(d["Image ID for this Shipping Sheet"], "img7")
        self.assertEqual(checklists.sub_pids(info), [{"FEB (FEB1)": "P-1"}])

    def test_domestic_hts_is_none(self):
        cl = self._surf_checklist()
        cl.state["PreShipping4a"] = {**SCENE_DATA[4],
                                     "shipping_service_type": "Domestic"}
        d = checklists.build_checklist_dict(cl, {"subcomponents": {}}, "i")
        self.assertIsNone(d["HTS code"])

    def test_csv_and_label(self):
        cl = self._surf_checklist()
        info = checklists.part_info(None, BOX, [
            {"part_id": "P-1", "type_name": "FEB", "functional_position": "FEB1"}])
        filename, text = checklists.build_csv(cl, info)
        self.assertRegex(filename, rf"^{BOX}-preshipping-.*\.csv$")
        self.assertIn("Freight Forwarder name,FF Inc", text)
        self.assertIn("DUNE PID," + BOX, text)
        self.assertIn("P-1,FEB,FEB1", text)
        pdf = checklists.build_label_pdf(BOX, "Test Type 007", "Development HWDB", None)
        self.assertTrue(pdf.startswith(b"%PDF"))


class ChecklistFlowTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("w", "w@w.io", "pw")
        self.client.force_login(self.user)
        _leaf()

    def _advance(self, data):
        return self.client.post(PAGE, {"action": "advance", **data})

    def test_full_surf_run_writes_dashboard_compatible_patch(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            self.client.post(PAGE, {"action": "start", "route": "confirm_surf"})
            self._advance({"confirm_list": "on"})                       # 1 gate
            for scene in (2, 3, 4, 5, 6, 7):
                self._advance(SCENE_DATA[scene])
            resp = self._advance({"confirm_patch_hwdb": "on"})          # 8 write

        # Shipping sheet uploaded with the Dashboard's comment string.
        (pid, fileobj, name), kwargs = api.post_component_image.call_args
        self.assertEqual(name, f"{BOX}-shipping-label.pdf")
        self.assertEqual(kwargs["comments"], "shipping sheet")
        self.assertTrue(fileobj.read().startswith(b"%PDF"))
        # The PATCH folds the checklist into the item's latest specs block.
        payload = api.patch_component.call_args.args[1]
        self.assertEqual(payload["part_id"], BOX)
        self.assertEqual(payload["manufacturer"], {"id": 7})
        data = payload["specifications"]["DATA"]
        self.assertEqual(data["Existing"], "kept")                      # preserved
        cl_map = {k: v for entry in data["Pre-Shipping Checklist"]
                  for k, v in entry.items()}
        self.assertEqual(cl_map["DUNE PID"], BOX)
        self.assertEqual(cl_map["QA Rep name"], "QA Rep")
        self.assertEqual(cl_map["Image ID for this Shipping Sheet"], "sheet9")
        self.assertIn("FD Logistics team acknoledgement (name)", cl_map)
        self.assertEqual(data["SubPIDs"],
                         [{"Analog Front End Board (FEB1)": "D05700300001-00012"}])
        self.assertEqual(payload["specifications"]["_meta"], {"v": 1})  # block kept

        cl = BoxChecklist.for_instance("dev").get(part_id=BOX)
        self.assertIsNotNone(cl.completed_at)
        self.assertRedirects(resp, PAGE, fetch_redirect_response=False)

    def test_gate_blocks_without_summary(self):
        api = _api()
        api.get_images.return_value = {"data": []}   # no exec summary
        m1, m2 = _mocked(api)
        with m1, m2:
            self.client.post(PAGE, {"action": "start", "route": "confirm_surf"})
            resp = self._advance({"confirm_list": "on"})
        cl = BoxChecklist.for_instance("dev").get(part_id=BOX)
        self.assertEqual(cl.current_scene, 1)        # did not advance
        with m1, m2:
            page = self.client.get(PAGE).content.decode()
        self.assertIn("create one", page)            # link to the summary page

    def test_resume_shows_saved_scene_and_back_works(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            self.client.post(PAGE, {"action": "start", "route": "confirm_surf"})
            self._advance({"confirm_list": "on"})
            self._advance(SCENE_DATA[2])
            html = self.client.get(PAGE).content.decode()
            self.assertIn("Step 3", html)
            self.client.post(PAGE, {"action": "back"})
            html = self.client.get(PAGE).content.decode()
        self.assertIn("Step 2", html)
        self.assertIn("QA Rep", html)                # saved value re-rendered

    def test_csv_download(self):
        api = _api()
        _cl(state={"PreShipping4a": SCENE_DATA[4], "PreShipping4b": SCENE_DATA[5]},
            scene=6)
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.get(PAGE, {"csv": "1"})
        self.assertEqual(resp["Content-Type"], "text/csv")
        self.assertIn("DUNE PID," + BOX, resp.content.decode())

    @override_settings(HWDB_WRITE_INSTANCES=["dev"])
    def test_prod_and_non_shipping_forbidden(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            prod = self.client.get("/hw/part/D08120200001-00001/preship/")
            nonship = self.client.get("/hw/dev/part/D05700200099-00007/preship/")
        self.assertEqual(prod.status_code, 403)
        self.assertEqual(nonship.status_code, 403)
