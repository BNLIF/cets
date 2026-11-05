"""Reset on the Shipping Workflows pane (#212): drops a box's CETS checklist
runs so the container can be used again; HWDB is never called.

    python manage.py test explore
"""

from __future__ import annotations

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from explore import views
from explore.models import ActivityEvent, BoxChecklist
from explore.models import HierarchyNode as H

BOX = "D00599800007-00128"
RESET = f"/hw/dev/part/{BOX}/box-reset/"


def _leaf():
    return H.objects.create(
        instance="dev", level=H.LEVEL_TYPE, system_id=5, system_name="Z.Sandbox",
        subsystem_id=998, subsystem_name="HWDBUnitTest", name="Test Type 007",
        part_type_id="D00599800007", full_name="x",
        tests_synced_at=timezone.now(), shipments_synced_at=timezone.now())


@override_settings(HWDB_WRITE_INSTANCES=["dev"])
class BoxResetTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("w", "w@w.io", "pw")
        self.client.force_login(self.user)
        _leaf()
        for wf, done in (("preshipping", True), ("shipping", True), ("receiving", True)):
            BoxChecklist.objects.create(
                instance="dev", part_id=BOX, workflow=wf, route="confirm_surf",
                current_scene=1, created_by="w",
                completed_at=timezone.now() if done else None)
        BoxChecklist.objects.create(  # another box's run must survive
            instance="dev", part_id="D00599800007-00001", workflow="preshipping",
            route="confirm_surf", current_scene=1, created_by="w")

    def test_reset_drops_the_boxs_three_runs_only_and_logs(self):
        with mock.patch("explore.views.mint_for", return_value="bearer"):
            resp = self.client.post(RESET)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], f"/hw/dev/part/{BOX}/")
        self.assertFalse(BoxChecklist.objects.filter(part_id=BOX).exists())
        self.assertEqual(BoxChecklist.objects.count(), 1)
        ev = ActivityEvent.objects.get(part_id=BOX)
        self.assertEqual(ev.kind, ActivityEvent.KIND_CHECKLIST)
        self.assertIn("reset", ev.summary)
        self.assertIn("Receiving", ev.summary)

    def test_nothing_to_reset_is_a_no_op(self):
        BoxChecklist.objects.filter(part_id=BOX).delete()
        with mock.patch("explore.views.mint_for", return_value="bearer"):
            resp = self.client.post(RESET)
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(ActivityEvent.objects.filter(part_id=BOX).exists())

    def test_get_is_refused(self):
        with mock.patch("explore.views.mint_for", return_value="bearer"):
            self.assertEqual(self.client.get(RESET).status_code, 405)

    def test_non_shipping_type_is_refused(self):
        with mock.patch("explore.views.mint_for", return_value="bearer"):
            resp = self.client.post("/hw/dev/part/D00599800099-00001/box-reset/")
        self.assertEqual(resp.status_code, 403)


class InstitutionPickerTest(TestCase):
    def test_id_0_never_lists(self):
        api = mock.MagicMock()
        api.get_institutions.return_value = {"data": [
            {"id": 0, "name": "IJCLAB Orsay", "country": {"code": "FR", "name": "France"}},
            {"id": 128, "name": "BNL", "country": {"code": "US", "name": "USA"}}]}
        self.assertEqual([o["id"] for o in views._institution_options(api)], [128])
