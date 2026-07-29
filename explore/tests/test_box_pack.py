"""Tests for packing a shipping box (issue #63): the box page's contents card
(unlink), the Add-items picker page, and the auto-assigning subcomponents
PATCH. Positions come from the type's connectors — users pick items, the
server picks slots. HWDB is mocked.

    python manage.py test explore
"""

from __future__ import annotations

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

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
    # The picker GET's enabled sweep pages the raw listing; unless a test
    # overrides this, it fails → a no-op (mirror flags untouched).
    api._make_request.side_effect = RuntimeError("no listing in tests")
    return api


def _mocked(api):
    return (mock.patch("explore.views.mint_for", return_value="bearer"),
            mock.patch("explore.views.FnalDbApiClient", return_value=api))


def _mirror_items():
    # Procedure-linkable statuses (120/110) — only those four are selectable
    # in the picker (#84); per-test overrides exercise the rest.
    HwdbComponentEvent.objects.create(
        instance="dev", part_type_id=CHILD_TYPE, part_id=IN_BOX,
        status="All passed", status_id=120,
        qaqc_uploaded=True, certified_qaqc=True)
    HwdbComponentEvent.objects.create(
        instance="dev", part_type_id=CHILD_TYPE, part_id=GOOD,
        status="All passed", status_id=120, institution="BNL",
        qaqc_uploaded=True, certified_qaqc=True)
    HwdbComponentEvent.objects.create(
        instance="dev", part_type_id=CHILD_TYPE, part_id=BAD_QC,
        status="", status_id=110, qaqc_uploaded=False, certified_qaqc=None)


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

    @override_settings(HWDB_WRITE_INSTANCES=["dev"])
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
        # The two QC flags shown as separate columns (Hajime 2026-07-28).
        self.assertIn("<th>Uploaded</th>", html)
        self.assertIn("<th>Certified</th>", html)
        self.assertIn(DOC_TYPE, html)                     # second type group
        self.assertIn('name="manual"', html)              # add-by-PID box
        # per-type sync button targets that type's node sync endpoint
        self.assertIn(f'data-sync-url="/hw/dev/sync-tests/{CHILD_TYPE}/"', html)
        self.assertIn(f'data-sync-url="/hw/dev/sync-tests/{DOC_TYPE}/"', html)
        # both sync tiers offered: new-items only, and the full re-sync that
        # refreshes QC flags/status of already-mirrored items
        self.assertIn('data-mode="incremental"', html)
        self.assertIn('data-mode="components"', html)
        # each candidate links to its part page (new tab, next to the label)
        self.assertIn(f'class="pk-open" href="/hw/dev/part/{GOOD}/"', html)
        # uncurated type → header falls back to plain text, no dead link
        self.assertIn(f'<span class="mono">{CHILD_TYPE}</span>', html)

    def test_picker_groups_show_free_functional_positions(self):
        # Shippers reference sub-components by Functional Position name (#74):
        # each group lists the free positions its picks will land in. Slot 1
        # is occupied, so only Slot 2 (and Doc, in its own group) appear.
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(PACK).content.decode()
        self.assertIn("Free positions:", html)
        self.assertIn('<span class="pk-pos">Slot 2</span>', html)
        self.assertIn('<span class="pk-pos">Doc</span>', html)
        self.assertNotIn('<span class="pk-pos">Slot 1</span>', html)  # occupied

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

    def test_get_sweeps_enabled_flags_live(self):
        # A stale mirror offered items HWDB refuses at write time ("not yet
        # available"). The picker GET now runs one enabled=false listing per
        # child type and stamps the mirror's flags before rendering.
        api = _api()
        api._make_request.side_effect = None
        api._make_request.return_value = {
            "data": [{"part_id": BAD_QC}], "pagination": {"pages": 1}}
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(PACK).content.decode()
        self.assertNotIn(f'value="{BAD_QC}"', html)  # disabled upstream → hidden
        self.assertIn(f'value="{GOOD}"', html)
        flags = dict(HwdbComponentEvent.objects.filter(
            part_type_id=CHILD_TYPE).values_list("part_id", "enabled"))
        self.assertEqual(flags, {IN_BOX: True, GOOD: True, BAD_QC: False})

    def test_get_sweeps_parents_live(self):
        # HWDB refused D00599800003-00012 ("already in use — inside another
        # box") because the mirror's parent link was stale: the picker GET
        # re-stamps parent_part_id from the type's full listing rows.
        api = _api()

        def listing(method, path, params=None):
            if (params or {}).get("enabled") == "false":
                return {"data": [], "pagination": {"pages": 1}}
            return {"data": [
                {"part_id": GOOD, "parent_part_id": "D00599800001-00010",
                 "status": {"id": 120, "name": "QA/QC Tests - Passed All"}},
                {"part_id": BAD_QC}], "pagination": {"pages": 1}}
        api._make_request.side_effect = listing
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(PACK).content.decode()
        self.assertNotIn(f'value="{GOOD}"', html)   # boxed elsewhere → hidden
        self.assertIn(f'value="{BAD_QC}"', html)
        row = HwdbComponentEvent.objects.get(part_id=GOOD)
        self.assertEqual(row.parent_part_id, "D00599800001-00010")
        self.assertEqual(row.status, "QA/QC Tests - Passed All")
        self.assertEqual(row.status_id, 120)
        # A row with no status in the listing keeps its mirrored one.
        self.assertEqual(HwdbComponentEvent.objects.get(part_id=IN_BOX).status,
                         "All passed")

    def test_failed_sweep_keeps_the_mirror_as_is(self):
        api = _api()  # _make_request raises → the sweep is a no-op
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(PACK).content.decode()
        self.assertIn(f'value="{BAD_QC}"', html)     # unknown still passes
        self.assertIsNone(
            HwdbComponentEvent.objects.get(part_id=GOOD).enabled)

    def test_default_lists_only_procedure_linkable_statuses(self):
        # #84: the default view keeps the clutter down — just the four
        # statuses the Shipping Procedure allows to be linked (100/110/120/
        # 140); legacy and NULL-status rows hide until "show all items".
        HwdbComponentEvent.objects.filter(part_id=GOOD).update(
            status="Permanently Unavailable", status_id=3)   # obsolete id
        HwdbComponentEvent.objects.create(
            instance="dev", part_type_id=CHILD_TYPE,
            part_id=f"{CHILD_TYPE}-00004", status="")        # status_id NULL
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(PACK).content.decode()
        self.assertNotIn(f'href="/hw/dev/part/{GOOD}/"', html)   # hidden
        self.assertNotIn(f"{CHILD_TYPE}-00004", html)            # NULL hidden
        self.assertIn(f'value="{BAD_QC}"', html)                 # 110 stays
        self.assertIn('id="pk-show-all"', html)                  # the toggle
        self.assertNotIn('<input type="hidden" name="show_all"',
                         html)                                   # off = no state field

    def test_show_all_lists_the_rest_display_only(self):
        # #84 (Hajime 2026-07-29): with the toggle on, every free item is
        # shown, but only the procedure's four statuses get a checkbox —
        # legacy/unknown/NULL rows are display-only.
        HwdbComponentEvent.objects.filter(part_id=GOOD).update(
            status="Permanently Unavailable", status_id=3)   # obsolete id
        HwdbComponentEvent.objects.create(
            instance="dev", part_type_id=CHILD_TYPE,
            part_id=f"{CHILD_TYPE}-00004", status="")        # status_id NULL
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(f"{PACK}?show_all=1").content.decode()
        self.assertNotIn(f'value="{GOOD}"', html)             # no checkbox…
        self.assertIn(f'href="/hw/dev/part/{GOOD}/"', html)   # …but listed
        self.assertNotIn(f'value="{CHILD_TYPE}-00004"', html)  # NULL: display-only
        self.assertIn(f"{CHILD_TYPE}-00004", html)
        self.assertIn(f'value="{BAD_QC}"', html)              # 110 pickable
        self.assertIn('class="pk-noadd"', html)
        # Obsolete ids display as Unknown BY ID — id 3 shares its name with
        # the modern id 170, so the raw name must not leak through.
        self.assertNotIn("Permanently Unavailable", html)
        self.assertIn("<td>Unknown</td>", html)
        # State survives htmx swaps: checkbox re-renders checked, and every
        # form carries the hidden field so POST re-renders keep the mode.
        self.assertIn("checked", html)
        self.assertIn('<input type="hidden" name="show_all" value="1">', html)

    def test_add_keeps_show_all_mode(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.post(
                PACK, {"pid": [GOOD], "show_all": "1"},
                HTTP_HX_REQUEST="true").content.decode()
        self.assertIn("Added 1 item(s)", html)
        self.assertIn('<input type="hidden" name="show_all" value="1">', html)

    def test_uncertified_items_stay_listed(self):
        # certified_qaqc does NOT gate packing (an uncertified FEB was found
        # linked in a dev box) — the picker must not hide these.
        HwdbComponentEvent.objects.filter(part_id=GOOD).update(certified_qaqc=False)
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(PACK).content.decode()
        self.assertIn(f'value="{GOOD}"', html)

    def test_htmx_get_returns_body_partial(self):
        # The scan poller refreshes the two-column body after a phone scan
        # lands in the box — a cheap partial, no sweeps. Its ?added= pids
        # get the highlight class in the contents table.
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(f"{PACK}?added={IN_BOX}",
                                   HTTP_HX_REQUEST="true").content.decode()
        self.assertIn('id="pk-body"', html)
        self.assertNotIn("<html", html)
        self.assertIn('class="pk-added"', html)
        api._make_request.assert_not_called()  # no listing sweeps

    @override_settings(HWDB_WRITE_INSTANCES=["dev"])
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

    def test_disallowed_status_is_refused_locally(self):
        # HWDB's REST API doesn't enforce the procedure's four-statuses rule
        # (2026-07-29 probe; Web UI does, fix requested) — the add path
        # checks the mirrored status itself (#84), so tampered checkboxes
        # and typed/scanned PIDs are covered too.
        HwdbComponentEvent.objects.filter(part_id=GOOD).update(
            status="QA/QC Tests - Non-conforming", status_id=130)
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            page = self.client.post(PACK, {"pid": [GOOD]}, follow=True)
        html = page.content.decode()
        api.patch_subcomponents.assert_not_called()
        self.assertIn(f"{GOOD} was not added", html)
        self.assertIn("not one the Shipping Procedure allows", html)

    def test_null_status_add_passes_through_for_hwdb_to_arbitrate(self):
        # The picker shows NULL-status rows display-only (Re-sync fetches
        # the status), but an explicit typed/scanned add still goes to HWDB.
        HwdbComponentEvent.objects.filter(part_id=GOOD).update(status_id=None)
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            self.client.post(PACK, {"manual": GOOD})
        api.patch_subcomponents.assert_called_once()

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

    @override_settings(HWDB_WRITE_INSTANCES=["dev"])
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

    def test_picker_shows_box_contents_column(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(PACK).content.decode()
        self.assertIn("pk-contents", html)
        self.assertIn("1 of 3 positions filled", html)
        self.assertIn(f">{IN_BOX}</a>", html)             # occupant linked
        self.assertIn("pk-slot-empty", html)              # free slots listed too
        self.assertIn("<th>Type</th>", html)              # type name column
        self.assertIn(f"<td>{CHILD_TYPE}</td>", html)     # uncurated → id fallback

    def test_htmx_add_rerenders_the_body_in_place(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post(PACK, {"pid": [GOOD]}, HTTP_HX_REQUEST="true")
        self.assertEqual(resp.status_code, 200)           # partial, not redirect
        html = resp.content.decode()
        self.assertIn('id="pk-body"', html)
        self.assertIn("Added 1 item(s)", html)            # flash inline
        self.assertIn("2 of 3 positions filled", html)
        self.assertIn(f">{GOOD}</a>", html)               # now in the box column
        self.assertIn('class="pk-added"', html)           # …highlighted
        self.assertNotIn(f'value="{GOOD}"', html)         # no longer a candidate

    def test_contents_pane_offers_unlink(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(PACK).content.decode()
        self.assertIn('name="unlink" value="Slot 1"', html)   # occupied slot
        self.assertNotIn('name="unlink" value="Slot 2"', html)  # empty slot

    def test_htmx_unlink_rerenders_the_body_in_place(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post(PACK, {"unlink": "Slot 1"},
                                    HTTP_HX_REQUEST="true")
        api.patch_subcomponents.assert_called_once_with(BOX, {
            "component": {"part_id": BOX},
            "subcomponents": {"Slot 1": None, "Slot 2": None, "Doc": None}})
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('id="pk-body"', html)
        self.assertIn(f"Unlinked {IN_BOX}", html)
        self.assertIn("0 of 3 positions filled", html)

    def test_htmx_rejection_rerenders_with_the_error(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post(PACK, {"manual": "not-a-pid"},
                                    HTTP_HX_REQUEST="true")
        api.patch_subcomponents.assert_not_called()
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('id="pk-body"', html)
        self.assertIn("doesn’t look like a PID", html)
        self.assertIn("1 of 3 positions filled", html)    # state unchanged

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
