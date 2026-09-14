"""#150 (Hajime): a consortium checklist flagged ``shipping`` is linked from
the box's pack page (with its submission state) and must be confirmed
complete in step 1 of the pre-shipping checklist.

    python manage.py test explore.tests.test_shipping_checklists
"""

from __future__ import annotations

import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from explore import checklistforms
from explore.models import BoxChecklist
from explore.tests.test_box_pack import _api, _mocked, BOX, PACK
from explore.tests.test_preship import _api as _preship_api, PAGE as PRESHIP

PTID = BOX.rsplit("-", 1)[0]
PACKING = {"name": "PDS module packing", "test_type_name": "Packing", "shipping": True,
           "sections": [{"title": "S", "fields": [{"type": "steps", "label": "Steps",
                                                    "steps": ["Aluminized bag", "Desiccant pouch"]}]}]}
RECEPTION = {"name": "Reception", "test_type_name": "Reception",
             "sections": [{"title": "S", "fields": [{"type": "check", "label": "Ok"}]}]}


def _with_checklists(api, submitted=True):
    api.get_component_type_images.return_value = {"data": [
        {"image_id": "p1", "image_name": f"Checklist_{PTID}_PDS_module_packing.json", "created": "2026-09-01"},
        {"image_id": "r1", "image_name": f"Checklist_{PTID}_Reception.json", "created": "2026-09-01"}]}
    api.get_image_response.side_effect = lambda iid: mock.Mock(
        content=json.dumps(PACKING if iid == "p1" else RECEPTION).encode())
    api.get_tests.return_value = {"data": [
        {"test_type": "Packing", "created": "2026-09-13T10:00:00"}] if submitted else []}
    return api


class ShippingFlagTest(TestCase):
    def test_normalize_keeps_the_flag(self):
        self.assertTrue(checklistforms.normalize(PACKING, "p")["shipping"])
        self.assertFalse(checklistforms.normalize(RECEPTION, "r")["shipping"])
        self.assertFalse(checklistforms.normalize({**PACKING, "shipping": 0}, "p")["shipping"])


class PackPageTest(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("p", "p@p.io", "pw"))

    def test_flagged_checklists_are_linked_with_their_submission_state(self):
        m1, m2 = _mocked(_with_checklists(_api()))
        with m1, m2:
            html = self.client.get(PACK).content.decode()
        self.assertIn("Packing / shipping checklists", html)
        self.assertIn(f'<a href="/hw/dev/part/{BOX}/checklist/PDS_module_packing/">&#9745; PDS_module_packing</a>', html)
        self.assertIn("submitted 2026-09-13", html)
        self.assertNotIn("checklist/Reception/", html)   # not flagged

    def test_any_type_with_positions_gets_the_links(self):
        """An assembly's "Link items into" page lists them too (Chao 2026-09-14)."""
        api = _with_checklists(_api())
        item = "D08100100005-00001"   # not a shipping type; its type has positions
        api.get_component_type.return_value = {"status": "OK", "data": {
            "part_type_id": "D08100100005", "connectors": {"A": "D08100100004"}}}
        api.get_component_type_images.return_value["data"][0]["image_name"] = "Checklist_D08100100005_Assembly.json"
        api.get_subcomponents.return_value = {"data": []}
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(f"/hw/dev/part/{item}/pack/").content.decode()
        self.assertIn("Link items into", html)
        self.assertIn("Assembly checklists", html)
        self.assertIn(f'href="/hw/dev/part/{item}/checklist/Assembly/"', html)

    def test_unsubmitted_and_absent(self):
        m1, m2 = _mocked(_with_checklists(_api(), submitted=False))
        with m1, m2:
            html = self.client.get(PACK).content.decode()
        self.assertIn("not submitted yet", html)
        m1, m2 = _mocked(_api())   # a type without any checklist
        with m1, m2:
            html = self.client.get(PACK).content.decode()
        self.assertNotIn("Packing / shipping checklists", html)


class PreshipStepOneTest(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("w", "w@w.io", "pw"))

    def test_step_1_requires_every_flagged_checklist_confirmed(self):
        api = _with_checklists(_preship_api(), submitted=False)
        m1, m2 = _mocked(api)
        with m1, m2:
            self.client.post(PRESHIP, {"action": "start", "route": "confirm_surf"})
            html = self.client.get(PRESHIP).content.decode()
            self.assertIn(f'href="/hw/dev/part/{BOX}/checklist/PDS_module_packing/"', html)
            self.assertIn('name="checklist_done" value="PDS_module_packing" required>', html)
            self.assertIn("not submitted yet", html)
            r = self.client.post(PRESHIP, {"action": "advance", "confirm_list": "on"}, follow=True)
            self.assertIn("Confirm that the “PDS_module_packing” checklist is complete.", r.content.decode())
            self.assertEqual(BoxChecklist.for_instance("dev").get(part_id=BOX).current_scene, 1)
            self.client.post(PRESHIP, {"action": "advance", "confirm_list": "on",
                                       "checklist_done": "PDS_module_packing"})
        cl = BoxChecklist.for_instance("dev").get(part_id=BOX)
        self.assertEqual(cl.current_scene, 2)
        self.assertEqual(cl.state["PreShipping1"]["checklists_done"], ["PDS_module_packing"])
        with m1, m2:   # back to step 1: the tick is remembered
            self.client.post(PRESHIP, {"action": "back"})
            html = self.client.get(PRESHIP).content.decode()
        self.assertIn('value="PDS_module_packing" required checked>', html)

    def test_editor_offers_the_flag(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(f"/hw/dev/checklist-config/{PTID}/").content.decode()
        self.assertIn('id="f-shipping"', html)
        self.assertIn("cfg.shipping = true", html)
