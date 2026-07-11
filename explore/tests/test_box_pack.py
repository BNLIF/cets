"""Tests for packing a shipping box (issue #63): the box page's contents card
(unlink), the Add-items picker page, and the auto-assigning subcomponents
PATCH. Positions come from the type's connectors — users pick items, the
server picks slots. HWDB is mocked.

    python manage.py test explore
"""

from __future__ import annotations

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from explore.models import HwdbComponentEvent, ShipmentItem

BOX = "D00599800007-00128"          # dev-curated shipping type
CHILD_TYPE = "D08100100004"         # dev LArASIC
DOC_TYPE = "D08100200001"
IN_BOX = f"{CHILD_TYPE}-00001"
GOOD = f"{CHILD_TYPE}-00002"
BAD_QC = f"{CHILD_TYPE}-00003"
PAGE = f"/hw/dev/part/{BOX}/"
PACK = f"/hw/dev/part/{BOX}/pack/"


def _api():
    api = mock.MagicMock()
    api.get_component.return_value = {"data": {
        "serial_number": "SN", "status": "Passed",
        "component_type": {"name": "Test Type 007"},
        "specifications": [{"DATA": {}}]}}
    api.get_component_type.return_value = {"status": "OK", "data": {
        "part_type_id": "D00599800007",
        "connectors": {"Slot 1": CHILD_TYPE, "Slot 2": CHILD_TYPE,
                       "Doc": DOC_TYPE}}}
    api.get_subcomponents.return_value = {"data": [
        {"part_id": IN_BOX, "type_name": "LArASIC",
         "functional_position": "Slot 1", "operation": "mount"}]}
    api.get_locations.return_value = {"data": []}
    api.get_images.return_value = {"data": []}
    api.get_test_types.return_value = {"data": []}
    api.get_tests.return_value = {"data": []}
    api.get_institutions.return_value = {"data": [
        {"id": 128, "name": "BNL", "country": {"code": "US"}}]}
    api.patch_subcomponents.return_value = {"status": "OK", "data": "Updated"}
    return api


def _mocked(api):
    return (mock.patch("explore.views.mint_for", return_value="bearer"),
            mock.patch("explore.views.FnalDbApiClient", return_value=api))


def _mirror_items():
    HwdbComponentEvent.objects.create(
        instance="dev", part_type_id=CHILD_TYPE, part_id=IN_BOX,
        status="All passed", qaqc_uploaded=True, certified_qaqc=True)
    HwdbComponentEvent.objects.create(
        instance="dev", part_type_id=CHILD_TYPE, part_id=GOOD,
        status="All passed", institution="BNL",
        qaqc_uploaded=True, certified_qaqc=True)
    HwdbComponentEvent.objects.create(
        instance="dev", part_type_id=CHILD_TYPE, part_id=BAD_QC,
        status="", qaqc_uploaded=False, certified_qaqc=None)


class PackingCardRenderTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("k", "k@k.io", "pw")
        self.client.force_login(self.user)
        _mirror_items()

    def test_card_shows_slot_schema_occupants_and_add_items_link(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(PAGE).content.decode()
        self.assertIn("Packing", html)
        self.assertIn('value="Slot 1"', html)             # unlink button
        self.assertIn(f">{IN_BOX}</a>", html)             # occupant link
        self.assertIn("Slot 2", html)                     # empty slot listed too
        self.assertIn("pk-empty-slot", html)
        self.assertIn(CHILD_TYPE, html)                   # accepted type shown
        self.assertIn(DOC_TYPE, html)
        self.assertIn(f'href="{PACK}"', html)             # Add items… page link
        self.assertIn("2 of 3 positions free", html)

    def test_card_absent_on_prod_box_page(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get("/hw/part/D08120200001-00001/").content.decode()
        self.assertNotIn("Packing", html)
        api.get_component_type.assert_not_called()

    def test_item_page_shows_which_box_holds_it(self):
        HwdbComponentEvent.objects.filter(part_id=GOOD).update(parent_part_id=BOX)
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(f"/hw/dev/part/{GOOD}/").content.decode()
        self.assertIn("Inside", html)
        self.assertIn(f">{BOX}</a>", html)

    def test_item_page_prefers_live_container_over_mirror(self):
        api = _api()
        api.get_container.return_value = {"status": "OK", "data": [
            {"part_id": GOOD, "operation": "mount", "created": "2026-07-10T00:00:00",
             "functional_position": "My Sub Comp 2",
             "container": {"part_id": BOX,
                           "component_type": {"name": "Test Type 007"}}}]}
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(f"/hw/dev/part/{GOOD}/").content.decode()
        self.assertIn("Inside", html)
        self.assertIn(f">{BOX}</a>", html)
        self.assertIn("My Sub Comp 2", html)

    def test_item_page_without_a_box_shows_nothing(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(f"/hw/dev/part/{GOOD}/").content.decode()
        self.assertNotIn("In shipping box", html)

    def test_type_with_no_connectors_says_so(self):
        api = _api()
        api.get_component_type.return_value = {"status": "OK", "data": {"connectors": {}}}
        api.get_subcomponents.return_value = {"data": []}
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(PAGE).content.decode()
        self.assertIn("defines no functional positions", html)


class PackPageTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("k", "k@k.io", "pw")
        self.client.force_login(self.user)
        _mirror_items()

    def test_picker_groups_by_type_with_qc_flags(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(PACK).content.decode()
        self.assertIn(f'value="{GOOD}"', html)            # pickable candidate
        self.assertIn(f'value="{BAD_QC}"', html)
        self.assertNotIn(f'value="{IN_BOX}"', html)       # already in the box
        self.assertIn("pk-qc-ok", html)                   # QC marks rendered
        self.assertIn("pk-qc-bad", html)
        self.assertIn(DOC_TYPE, html)                     # second type group
        self.assertIn('name="manual"', html)              # add-by-PID box
        # per-type sync button targets that type's node sync endpoint
        self.assertIn(f'data-sync-url="/hw/dev/sync-tests/{CHILD_TYPE}/"', html)
        self.assertIn(f'data-sync-url="/hw/dev/sync-tests/{DOC_TYPE}/"', html)

    def test_items_inside_another_box_are_hidden(self):
        HwdbComponentEvent.objects.filter(part_id=GOOD).update(
            parent_part_id="D00599800007-00150")
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(PACK).content.decode()
        self.assertNotIn(f'value="{GOOD}"', html)   # packed elsewhere → hidden
        self.assertIn(f'value="{BAD_QC}"', html)    # still free → offered

    def test_not_yet_enabled_items_are_hidden(self):
        HwdbComponentEvent.objects.filter(part_id=GOOD).update(enabled=False)
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(PACK).content.decode()
        self.assertNotIn(f'value="{GOOD}"', html)   # unapproved → hidden
        self.assertIn(f'value="{BAD_QC}"', html)    # enabled unknown → offered

    def test_uncertified_items_stay_listed(self):
        # certified_qaqc does NOT gate packing (an uncertified FEB was found
        # linked in a dev box) — the picker must not hide these.
        HwdbComponentEvent.objects.filter(part_id=GOOD).update(certified_qaqc=False)
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(PACK).content.decode()
        self.assertIn(f'value="{GOOD}"', html)

    def test_picker_is_forbidden_on_prod(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.get("/hw/part/D08120200001-00001/pack/")
        self.assertEqual(resp.status_code, 403)


class PackPostTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("k", "k@k.io", "pw")
        self.client.force_login(self.user)
        _mirror_items()

    def test_add_auto_assigns_a_free_slot_and_sends_complete_dict(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post(PACK, {"pid": [GOOD]})
        self.assertRedirects(resp, PAGE, fetch_redirect_response=False)
        api.patch_subcomponents.assert_called_once_with(BOX, {
            "component": {"part_id": BOX},
            "subcomponents": {"Slot 1": IN_BOX, "Slot 2": GOOD, "Doc": None}})
        self.assertTrue(ShipmentItem.for_instance("dev").filter(part_id=BOX).exists())
        # refresh_box stamped the member's parent (mocked manifest re-fetch)
        row = HwdbComponentEvent.for_instance("dev").get(part_id=IN_BOX)
        self.assertEqual(row.parent_part_id, BOX)

    def test_already_in_use_rejection_reads_cleanly(self):
        import requests as _rq
        resp = mock.Mock()
        resp.json.return_value = {
            "data": "The component 'D00599800003-00044' is already in use",
            "status": "ERROR"}
        api = _api()
        api.patch_subcomponents.side_effect = _rq.exceptions.HTTPError(
            "404 NOT FOUND for …/subcomponents: {…}", response=resp)
        api.get_container.return_value = {"status": "OK", "data": [
            {"part_id": GOOD, "operation": "mount", "created": "2026-07-10T00:00:00",
             "container": {"part_id": "D00599800005-00003",
                           "component_type": {"name": "Test Type 005"}}}]}
        m1, m2 = _mocked(api)
        with m1, m2:
            page = self.client.post(PACK, {"pid": [GOOD]}, follow=True)
        html = page.content.decode()
        self.assertIn("was not added", html)
        self.assertIn("is already in use", html)
        self.assertIn("it is inside D00599800005-00003", html)  # from /container
        self.assertNotIn("404 NOT FOUND", html)   # raw dump replaced by detail

    def test_refusal_without_a_parent_reports_hwdb_status_flags(self):
        import requests as _rq
        resp = mock.Mock()
        resp.json.return_value = {
            "data": f"Component '{GOOD}' is not yet available", "status": "ERROR"}
        api = _api()
        api.patch_subcomponents.side_effect = _rq.exceptions.HTTPError(
            "404", response=resp)
        api.get_container.return_value = {"status": "OK", "data": []}
        api.get_component_status.return_value = {"status": "OK", "data": {
            "status": {"id": 1, "name": "Available"}, "enabled": False}}
        m1, m2 = _mocked(api)
        with m1, m2:
            page = self.client.post(PACK, {"pid": [GOOD]}, follow=True)
        html = page.content.decode()
        self.assertIn("is not yet available", html)
        self.assertIn("HWDB status: status=Available, enabled=False", html)

    def test_one_refused_item_does_not_block_the_rest(self):
        import requests as _rq
        DOC = f"{DOC_TYPE}-00009"
        resp = mock.Mock()
        resp.json.return_value = {
            "data": f"The component '{GOOD}' is already in use", "status": "ERROR"}
        api = _api()
        api.patch_subcomponents.side_effect = [
            _rq.exceptions.HTTPError("404", response=resp),   # GOOD refused
            {"status": "OK", "data": "Updated"},              # DOC lands
        ]
        m1, m2 = _mocked(api)
        with m1, m2:
            page = self.client.post(PACK, {"pid": [GOOD], "manual": DOC},
                                    follow=True)
        html = page.content.decode()
        self.assertIn(f"Added 1 item(s): {DOC}", html)
        self.assertIn(f"{GOOD} was not added", html)
        # The second PATCH must not carry the refused item.
        second = api.patch_subcomponents.call_args_list[1].args[1]
        self.assertEqual(second["subcomponents"],
                         {"Slot 1": IN_BOX, "Slot 2": None, "Doc": DOC})

    def test_manual_pids_work_like_picked_ones(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            self.client.post(PACK, {"manual": f" {GOOD} "})
        payload = api.patch_subcomponents.call_args.args[1]
        self.assertEqual(payload["subcomponents"]["Slot 2"], GOOD)

    def test_more_items_than_free_slots_is_rejected(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post(PACK, {"pid": [GOOD, BAD_QC]}, follow=True)
        api.patch_subcomponents.assert_not_called()
        self.assertIn("No free positions left", resp.content.decode())

    def test_type_without_positions_is_rejected(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post(PACK, {"manual": "D05700200099-00007"}, follow=True)
        api.patch_subcomponents.assert_not_called()
        self.assertIn("no positions for", resp.content.decode())

    def test_item_already_in_the_box_is_rejected(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post(PACK, {"pid": [IN_BOX]}, follow=True)
        api.patch_subcomponents.assert_not_called()
        self.assertIn("already in this box", resp.content.decode())

    def test_malformed_pid_is_rejected(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post(PACK, {"manual": "not-a-pid"}, follow=True)
        api.patch_subcomponents.assert_not_called()
        self.assertIn("doesn’t look like a PID", resp.content.decode())

    def test_nothing_picked_is_rejected(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post(PACK, {}, follow=True)
        api.patch_subcomponents.assert_not_called()
        self.assertIn("Pick at least one item", resp.content.decode())

    def test_unlink_empties_only_that_position(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post(PACK, {"unlink": "Slot 1"}, follow=True)
        api.patch_subcomponents.assert_called_once_with(BOX, {
            "component": {"part_id": BOX},
            "subcomponents": {"Slot 1": None, "Slot 2": None, "Doc": None}})
        self.assertIn(f"Unlinked {IN_BOX}", resp.content.decode())

    def test_unlink_empty_position_is_rejected(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post(PACK, {"unlink": "Slot 2"}, follow=True)
        api.patch_subcomponents.assert_not_called()
        self.assertIn("nothing to unlink", resp.content.decode())

    def test_prod_and_non_shipping_are_forbidden(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            prod = self.client.post("/hw/part/D08120200001-00001/pack/",
                                    {"pid": [GOOD]})
            nonship = self.client.post("/hw/dev/part/D05700200099-00007/pack/",
                                       {"pid": [GOOD]})
        self.assertEqual(prod.status_code, 403)
        self.assertEqual(nonship.status_code, 403)
        api.patch_subcomponents.assert_not_called()

    def test_app_level_error_surfaces_on_the_picker(self):
        api = _api()
        api.patch_subcomponents.return_value = {
            "status": "ERROR", "data": "subcomponent already attached elsewhere"}
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post(PACK, {"pid": [GOOD]}, follow=True)
        html = resp.content.decode()
        self.assertIn(f"{GOOD} was not added", html)
        self.assertIn("already attached elsewhere", html)
