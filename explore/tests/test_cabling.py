"""The Cable connections page (#226–#229): one endpoint device, its positions
that take a cable, where each connected cable goes, connecting and
removing on the working side, the type's picture, the device location and
the labels. HWDB is mocked with rows
shaped as dev answers them since 2026-11-20, the client having taken the
country / institution codes off.

    python manage.py test explore.tests.test_cabling
"""

from __future__ import annotations

import json
from unittest import mock

import requests
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from explore import cabling
from explore.models import HierarchyNode as H

FLANGE = "Z00100300064-00004"
WARM, BUNDLE4, BOARD = "Z00100300073", "Z00100300035", "D08100100004"
INSTALLED, ONE_END, MANY = f"{WARM}-00020", f"{WARM}-00021", f"{BUNDLE4}-00001"
SHIELD, FCT, FILTER = "Z00100300061-00001", "Z00100300066-00003", "Z00100300068-00012"
TRAY, FREE = "Z00100300072-00004", f"{WARM}-00022"
PAGE = f"/hw/dev/part/{FLANGE}/cables/"


def _api():
    """A flange with five positions: one cable connected at both its ENDs,
    one connected here alone, one 4-END cable going to two other devices,
    one free cable position, and a position that takes a board. A bundle
    holds the two warm cables and a third, unconnected one."""
    types = {
        "Z00100300064": {"category": "generic", "connectors": {
            "ISH": WARM, "OSH": WARM, "FCT.T": BUNDLE4, "ICO": WARM, "Board": BOARD}},
        WARM: {"category": "cable", "full_name": "Z.Sandbox.Test.Top CRP bias warm cable",
               "connectors": {"FCP Flange:1": None, "HVS PS:1": None}},
        BUNDLE4: {"category": "cable", "full_name": "Z.Sandbox.Test.HVS Test Bundle 4 Ends",
                  "connectors": {"Flange:7": None, "FC Termination:1": None, "Inner CRP:1": None, "Outer CRP:1": None}},
        BOARD: {"category": "generic", "full_name": "D.FD CE.Chips.LArASIC", "connectors": {}},
        "Z00100300072": {"category": "generic", "full_name": "Z.Sandbox.Test.Top CRP bias warm cable bundle",
                         "connectors": {"Inner (SH)": WARM, "Outer (SH)": WARM, "Outer (CO)": WARM}},
    }
    rows = {
        FLANGE: [
            {"part_id": f"{INSTALLED}.FCP Flange:1", "type_name": "Top CRP bias warm cable",
             "functional_position": "ISH", "operation": "mount"},
            {"part_id": f"{ONE_END}.FCP Flange:1", "type_name": "Top CRP bias warm cable",
             "functional_position": "OSH", "operation": "mount"},
            {"part_id": f"{MANY}.Flange:7", "type_name": "HVS Test Bundle 4 Ends",
             "functional_position": "FCT.T", "operation": "mount"},
            {"part_id": f"{BOARD}-00009", "type_name": "LArASIC",
             "functional_position": "Board", "operation": "mount"}],
        INSTALLED: [
            {"part_id": f"{FLANGE}.ISH", "type_name": "Bias FT flange", "cable_connector": "FCP Flange:1", "operation": "mount"},
            {"part_id": f"{SHIELD}.CH01.2", "type_name": "CRP Shield (slot 4)", "cable_connector": "HVS PS:1", "operation": "mount"}],
        ONE_END: [
            {"part_id": f"{FLANGE}.OSH", "type_name": "Bias FT flange", "cable_connector": "FCP Flange:1", "operation": "mount"}],
        MANY: [
            {"part_id": f"{FLANGE}.FCT.T", "type_name": "Bias FT flange", "cable_connector": "Flange:7", "operation": "mount"},
            {"part_id": f"{FCT}.IN", "type_name": "FC termination board", "cable_connector": "FC Termination:1", "operation": "mount"},
            {"part_id": f"{FILTER}.FB2", "type_name": "Filter box", "cable_connector": "Inner CRP:1", "operation": "mount"}],
        TRAY: [{"part_id": pid, "type_name": "Top CRP bias warm cable", "functional_position": pos, "operation": "mount"}
               for pid, pos in ((INSTALLED, "Inner (SH)"), (ONE_END, "Outer (SH)"), (FREE, "Outer (CO)"))],
    }
    api = mock.MagicMock()
    api.get_container.side_effect = lambda pid: {"data": [{
        "container": {"part_id": TRAY, "component_type": {"name": "Top CRP bias warm cable bundle"}},
        "functional_position": "Inner (SH)", "operation": "mount", "created": "2026-07-19"}]
        if pid in (INSTALLED, ONE_END, FREE) else []}
    api.patch_subcomponents.return_value = {"status": "OK", "data": "Updated"}
    api.get_component_type_images.return_value = {"data": []}             # no picture of the type
    api.post_component_type_image.return_value = {"status": "OK", "image_id": "777"}
    api.get_component.side_effect = lambda pid: {"data": {
        "category": "cable" if pid.rsplit("-", 1)[0] in (WARM, BUNDLE4) else "generic",
        "component_type": {"name": "Bias FT flange" if pid == FLANGE else "Top CRP bias warm cable"}}}
    api.get_component_type.side_effect = lambda t: {"data": types[t]}
    api.get_subcomponents.side_effect = lambda pid: {"data": rows.get(pid, [])}
    return api


def _with_picture(api, slots=None):
    """The flange's type gets a picture (image 55) with a marker per slot —
    two versions of the file on the type, the newer one the one read."""
    slots = slots if slots is not None else [
        {"label": "ISH", "x": 10, "y": 20}, {"label": "ICO", "x": 55.5, "y": 80},
        {"label": "Gone", "x": 1, "y": 1}, {"label": "Board", "x": 2, "y": 2}]
    api.get_component_type_images.return_value = {"data": [
        {"image_id": "90", "image_name": "Cable_map_Z00100300064.json", "created": "2026-11-01T10:00:00"},
        {"image_id": "91", "image_name": "Cable_map_Z00100300064.json", "created": "2026-11-20T10:00:00"},
        {"image_id": "55", "image_name": "ChecklistImage_Z00100300064_x.jpg", "created": "2026-11-20T09:00:00"}]}
    files = {"91": {"image_id": "55", "slots": slots, "updated_by": "k"}, "90": {"image_id": "1", "slots": []}}
    api.get_image_response.side_effect = lambda image_id: mock.Mock(content=json.dumps(files[image_id]).encode())
    return api


class DeviceConnectionsTest(TestCase):
    def setUp(self):
        self.api = _api()
        self.device = cabling.device_connections(self.api, "dev", FLANGE)
        self.rows = {r["position"]: r for r in self.device["rows"]}

    def test_one_row_per_position_taking_a_cable_in_the_types_order(self):
        self.assertEqual([(r["n"], r["position"]) for r in self.device["rows"]],
                         [(1, "ISH"), (2, "OSH"), (3, "FCT.T"), (4, "ICO")])      # "Board" takes no cable
        self.assertEqual(self.device["type_name"], "Bias FT flange")
        self.assertFalse(self.device["is_cable"])

    def test_a_free_position_names_what_it_expects(self):
        free = self.rows["ICO"]
        self.assertEqual((free["status"], free["cable"], free["expected"]),
                         ("available", None, ["Top CRP bias warm cable"]))

    def test_a_connected_row_names_the_cable_its_end_and_the_other_side(self):
        r = self.rows["ISH"]
        self.assertEqual((r["cable"], r["end"], r["cable_type"]),
                         (INSTALLED, "FCP Flange:1", "Top CRP bias warm cable"))
        self.assertEqual(r["others"], [{"part_id": SHIELD, "type_name": "CRP Shield (slot 4)", "here": False, "location": "",
                                        "connections": [{"position": "CH01.2", "end": "HVS PS:1"}]}])

    def test_installed_means_every_connector_of_the_cable_is_connected(self):
        self.assertEqual(self.rows["ISH"]["status"], "installed")       # 2 of 2
        self.assertEqual(self.rows["OSH"]["status"], "connected")       # 1 of 2, no other side yet
        self.assertEqual(self.rows["OSH"]["others"], [])
        self.assertEqual((self.rows["FCT.T"]["status"], self.rows["FCT.T"]["connected"],
                          self.rows["FCT.T"]["connectors"]), ("connected", 3, 4))
        self.assertEqual(self.device["n_connected"], 3)

    def test_a_cable_with_several_other_connections_lists_them_all(self):
        self.assertEqual([(o["part_id"], o["connections"][0]["position"]) for o in self.rows["FCT.T"]["others"]],
                         [(FCT, "IN"), (FILTER, "FB2")])

    def test_the_other_side_is_the_cables_other_ends(self):
        """Connectors of one END sit at the same end of the cable: a bundle's
        Flange:1…3 on this device and Flange:4 on a neighbour are not the
        other side of Flange:1 — what its far END plugs into is, each device
        once with its positions. A short cable may have both ENDs here."""
        api = _api()
        rows = {
            FLANGE: [{"part_id": f"{MANY}.Flange:{n}", "functional_position": pos, "operation": "mount"}
                     for n, pos in ((1, "ISH"), (2, "OSH"), (3, "FCT.T"))]
                    + [{"part_id": f"{ONE_END}.FCP Flange:1", "functional_position": "ICO", "operation": "mount"}],
            MANY: [{"part_id": f"{FLANGE}.{pos}", "cable_connector": f"Flange:{n}", "operation": "mount"}
                   for n, pos in ((1, "ISH"), (2, "OSH"), (3, "FCT.T"))]
                  + [{"part_id": f"{FCT}.B", "cable_connector": "Flange:4", "operation": "mount"},
                     {"part_id": f"{FILTER}.FB1", "type_name": "Filter box", "cable_connector": "Inner CRP:1", "operation": "mount"},
                     {"part_id": f"{FILTER}.FB2", "type_name": "Filter box", "cable_connector": "Inner CRP:2", "operation": "mount"}],
            ONE_END: [{"part_id": f"{FLANGE}.ICO", "cable_connector": "FCP Flange:1", "operation": "mount"},
                      {"part_id": f"{FLANGE}.Board", "cable_connector": "HVS PS:1", "operation": "mount"}],
        }
        api.get_subcomponents.side_effect = lambda pid: {"data": rows.get(pid, [])}
        device = cabling.device_connections(api, "dev", FLANGE)
        by = {r["position"]: r for r in device["rows"]}
        self.assertEqual(by["ISH"]["others"], [{"part_id": FILTER, "type_name": "Filter box", "here": False, "location": "", "connections": [
            {"position": "FB1", "end": "Inner CRP:1"}, {"position": "FB2", "end": "Inner CRP:2"}]}])
        self.assertEqual([(o["here"], o["connections"]) for o in by["ICO"]["others"]],
                         [(True, [{"position": "Board", "end": "HVS PS:1"}])])
        self.assertEqual([o["part_id"] for o in device["others"]], [FILTER])     # not the device itself

    def test_the_other_side_devices_with_how_many_cables_go_there(self):
        self.assertEqual([(o["part_id"], o["type_name"], o["cables"]) for o in self.device["others"]],
                         [(SHIELD, "CRP Shield (slot 4)", 1), (FCT, "FC termination board", 1), (FILTER, "Filter box", 1)])

    def test_reads_are_bounded_by_the_device(self):
        """Its record, its positions, each connected cable's rows once, a type
        record per type, the record of each other-side device for its
        location (#229) — no listing."""
        self.assertEqual(sorted(c.args[0] for c in self.api.get_component.call_args_list),
                         sorted([FLANGE, SHIELD, FCT, FILTER]))
        self.assertEqual(sorted(c.args[0] for c in self.api.get_subcomponents.call_args_list),
                         sorted([FLANGE, INSTALLED, ONE_END, MANY]))
        self.assertLessEqual(self.api.get_component_type.call_count, 6)   # the device's, three accepted, two cable types
        self.api._make_request.assert_not_called()

    def test_the_mirror_spares_the_type_reads_for_names_and_categories(self):
        for tid, name, cat in ((WARM, "Top CRP bias warm cable", "cable"), (BUNDLE4, "HVS Test Bundle 4 Ends", "cable"),
                               (BOARD, "LArASIC", "generic")):
            H.objects.create(instance="dev", level=H.LEVEL_TYPE, system_id=1, system_name="S", subsystem_id=3,
                             subsystem_name="SS", name=name, part_type_id=tid, category=cat)
        api = _api()
        device = cabling.device_connections(api, "dev", FLANGE)
        self.assertEqual([r["position"] for r in device["rows"]], ["ISH", "OSH", "FCT.T", "ICO"])
        self.assertEqual(api.get_component_type.call_count, 3)            # the device's and the two cable types' connectors

    def test_a_connected_row_lists_every_connector_of_its_cable(self):
        """#234: in the type's order, connected or free — the one at this row,
        those elsewhere on this device, and those on other devices."""
        slots = self.rows["FCT.T"]["slots"]
        self.assertEqual([(s["name"], s["end"], s["n"], s["part_id"]) for s in slots],
                         [("Flange:7", "Flange", ":7", FLANGE), ("FC Termination:1", "FC Termination", ":1", FCT),
                          ("Inner CRP:1", "Inner CRP", ":1", FILTER), ("Outer CRP:1", "Outer CRP", ":1", None)])
        self.assertEqual([(s["this"], s["here"], s["position"]) for s in slots[:3]],
                         [(True, True, "FCT.T"), (False, False, "IN"), (False, False, "FB2")])
        self.assertEqual([s["name"] for s in self.rows["OSH"]["slots"] if not s["part_id"]], ["HVS PS:1"])   # the free end
        self.assertNotIn("slots", self.rows["ICO"])                       # nothing connected: nothing to list

    def test_connectors_of_one_end_on_this_and_on_another_device_are_listed_with_their_location(self):
        api = _api()
        many = [{"part_id": f"{FLANGE}.FCT.T", "cable_connector": "Flange:7", "operation": "mount"},
                {"part_id": f"{FLANGE}.ISH", "cable_connector": "Inner CRP:1", "operation": "mount"},
                {"part_id": f"{FCT}.B", "cable_connector": "Odd:9", "operation": "mount"}]     # a name the type lacks
        inner_s, inner_c = api.get_subcomponents.side_effect, api.get_component.side_effect
        api.get_subcomponents.side_effect = lambda pid: {"data": many} if pid == MANY else inner_s(pid)
        api.get_component.side_effect = lambda pid: {"data": {**inner_c(pid)["data"], "specifications": [
            {"DATA": {cabling.LOCATION_KEY: "FCT_3"}}] if pid == FCT else []}}
        slots = {r["position"]: r for r in cabling.device_connections(api, "dev", FLANGE)["rows"]}["FCT.T"]["slots"]
        self.assertEqual([(s["name"], s["part_id"], s.get("this"), s.get("here"), s.get("location")) for s in slots],
                         [("Flange:7", FLANGE, True, True, ""), ("FC Termination:1", None, None, None, None),
                          ("Inner CRP:1", FLANGE, False, True, ""), ("Outer CRP:1", None, None, None, None),
                          ("Odd:9", FCT, False, False, "FCT_3")])           # still shown, after the type's own

    def test_a_cable_linked_without_an_end_is_not_a_connection(self):
        api = _api()
        rows = [{"part_id": ONE_END, "type_name": "Top CRP bias warm cable",
                 "functional_position": "ICO", "operation": "mount"}]
        api.get_subcomponents.side_effect = lambda pid: {"data": rows if pid == FLANGE else []}
        device = cabling.device_connections(api, "dev", FLANGE)
        r = {r["position"]: r for r in device["rows"]}["ICO"]
        self.assertEqual((r["status"], r["cable"], r["end"]), ("noend", ONE_END, None))
        self.assertEqual(device["n_connected"], 0)

    def test_a_row_names_the_cables_bundle_and_the_other_rows_of_the_same_one(self):
        self.assertEqual(self.rows["ISH"]["bundle"],
                         {"part_id": TRAY, "type_name": "Top CRP bias warm cable bundle", "also": [2], "label": ""})
        self.assertEqual(self.rows["OSH"]["bundle"]["also"], [1])
        self.assertIsNone(self.rows["FCT.T"]["bundle"])                   # in no bundle
        self.assertIsNone(self.rows["ICO"]["bundle"])
        self.assertEqual(sorted(c.args[0] for c in self.api.get_container.call_args_list),
                         sorted([INSTALLED, ONE_END, MANY]))              # each connected cable once

    def test_a_cable_this_device_holds_as_its_tray_has_no_bundle_column(self):
        api = _api()
        rows = [{"part_id": ONE_END, "type_name": "Top CRP bias warm cable", "functional_position": "ICO", "operation": "mount"}]
        api.get_subcomponents.side_effect = lambda pid: {"data": rows if pid == FLANGE else []}
        api.get_container.side_effect = lambda pid: {"data": [{"container": {"part_id": FLANGE}, "operation": "mount"}]}
        device = cabling.device_connections(api, "dev", FLANGE)
        self.assertIsNone({r["position"]: r for r in device["rows"]}["ICO"]["bundle"])

    def test_a_scanned_bundle_offers_its_cables_at_the_free_positions(self):
        bundle = cabling.offer_bundle(self.api, "dev", self.device, TRAY)
        self.assertEqual((bundle["part_id"], bundle["type_name"]), (TRAY, "Top CRP bias warm cable bundle"))
        self.assertEqual([(c["part_id"], c["held_at"], c["connected"], c["connectors"], c["here"], c["open"])
                          for c in bundle["cables"]],
                         [(INSTALLED, "Inner (SH)", 2, 2, [1], False), (ONE_END, "Outer (SH)", 1, 2, [2], False),
                          (FREE, "Outer (CO)", 0, 2, [], True)])
        free = self.rows["ICO"]
        self.assertEqual([c["part_id"] for c in free["candidates"]], [INSTALLED, ONE_END, FREE])
        self.assertEqual(free["prefill"], FREE)                           # the one cable still open
        self.assertNotIn("candidates", self.rows["ISH"])                  # a connected row is offered nothing

    def test_a_bundle_with_several_open_cables_prefills_none(self):
        api = _api()
        api.get_subcomponents.side_effect = lambda pid: {"data": _api().get_subcomponents(TRAY)["data"] if pid == TRAY else []}
        device = cabling.device_connections(api, "dev", FLANGE)
        self.assertTrue(cabling.offer_bundle(api, "dev", device, TRAY)["offered"])
        self.assertEqual({r["prefill"] for r in device["rows"] if r["accepts"] == [WARM]}, {""})
        self.assertEqual([r.get("candidates") for r in device["rows"] if r["position"] == "FCT.T"], [[]])   # another type

    def test_a_stored_picture_is_read_as_slots_in_percent(self):
        self.assertEqual(cabling.normalize_map({"image_id": 55, "slots": [
            {"label": " ISH ", "x": "10.123", "y": 20}, {"label": "ISH", "x": 1, "y": 1},     # named twice
            {"label": "Off", "x": 101, "y": 5}, {"label": "", "x": 5, "y": 5}, {"label": "Bad", "x": "a", "y": 5}, "junk"]}),
            {"image_id": "55", "slots": [{"label": "ISH", "x": 10.12, "y": 20.0}]})
        self.assertEqual(cabling.normalize_map(None), {"image_id": "", "slots": []})
        self.assertIsNone(cabling.read_map(self.api, "Z00100300064"))     # the type has no picture
        self.assertEqual(cabling.read_map(_with_picture(_api()), "Z00100300064")["image_id"], "55")   # the newer file

    def test_the_picture_gets_a_marker_per_slot_named_like_a_row(self):
        device = cabling.device_connections(_with_picture(_api()), "dev", FLANGE)
        self.assertEqual(device["picture"]["image_id"], "55")
        self.assertEqual([(m["row"]["n"], m["row"]["position"], m["row"]["status"], m["x"], m["y"])
                          for m in device["picture"]["markers"]],
                         [(1, "ISH", "installed", 10.0, 20.0), (4, "ICO", "available", 55.5, 80.0)])   # no row: left off
        self.assertIsNone(self.device["picture"])

    def test_the_editor_offers_the_positions_that_take_a_cable(self):
        connectors = self.api.get_component_type("Z00100300064")["data"]["connectors"]
        self.assertEqual(cabling.cable_positions(self.api, "dev", connectors), ["ISH", "OSH", "FCT.T", "ICO"])

    def test_a_cable_has_no_rows_of_its_own(self):
        api = _api()
        device = cabling.device_connections(api, "dev", INSTALLED)
        self.assertTrue(device["is_cable"])
        self.assertEqual(device["rows"], [])
        api.get_subcomponents.assert_not_called()


class CablesPageTest(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("k", "k@k.io", "pw"))

    def _get(self, url, api=None):
        with mock.patch("explore.views.mint_for", return_value="bearer"), \
             mock.patch("explore.views.FnalDbApiClient", return_value=api or _api()):
            return self.client.get(url)

    def _post(self, url, data, api):
        with mock.patch("explore.views.mint_for", return_value="bearer"), \
             mock.patch("explore.views.FnalDbApiClient", return_value=api):
            return self.client.post(url, data)

    def test_page_lists_the_positions_with_cable_other_side_and_status(self):
        html = self._get(PAGE).content.decode()
        self.assertIn("3 / 4 connected", html)
        self.assertIn(f'href="/hw/dev/part/{INSTALLED}/">{INSTALLED}</a><span class="cc-l2 mono">FCP Flange:1</span>', html)
        self.assertIn("<b>CH01.2</b>", html)
        self.assertIn(f'href="/hw/dev/part/{SHIELD}/cables/"', html)             # the other side opens as the working device
        self.assertIn("CRP Shield (slot 4)", html)
        self.assertIn('<span class="cc-none">not connected yet</span>', html)
        self.assertIn("Not connected<span class=\"cc-l2\">Expected: Top CRP bias warm cable</span>", html)
        for label in ("Installed", "Connected", "Available"):
            self.assertIn(f">{label}</span>", html)
        self.assertIn("Bias FT flange", html)                                    # the header's type

    def test_view_shows_one_connection_with_both_sides(self):
        html = self._get(PAGE).content.decode()
        dlg = html.split('id="cc-view-1"', 1)[1].split("</dialog>", 1)[0]     # a two-connector cable: this side, other side
        self.assertIn("Connection at 1 · ISH", dlg)
        self.assertIn("2 of 2 connectors connected", dlg)
        self.assertEqual((dlg.count("<h3>This side</h3>"), dlg.count("<h3>Other side</h3>")), (1, 1))
        self.assertIn('· <span class="mono">HVS PS:1</span> · connected', dlg)
        self.assertNotIn("<h3>Connectors", dlg)
        dlg = html.split('id="cc-view-3"', 1)[1].split("</dialog>", 1)[0]
        self.assertIn("Connection at 3 · FCT.T", dlg)
        # more than two connectors (#234): every one with its status, grouped by END, in place of the other-side boxes
        self.assertIn("<h3>Connectors · 3 of 4 connected</h3>", dlg)
        self.assertNotIn("<h3>Other side</h3>", dlg)
        self.assertEqual(dlg.count('class="cc-slots-end"'), 4)
        self.assertIn('<span class="cc-slots-end">Flange</span>', dlg)
        self.assertIn('<span class="mono">:7</span><span><span class="cc-dot on"></span><b>FCT.T</b> '
                      '<span class="cc-l2" style="display: inline;">· this side</span></span>', dlg)
        self.assertIn(f'<b>IN</b> <span class="cc-l2" style="display: inline;">· <a class="mono" href="/hw/dev/part/{FCT}/cables/"', dlg)
        self.assertIn('<span class="cc-none"><span class="cc-dot"></span>not connected</span>', dlg)
        self.assertEqual(dlg.count('class="cc-dot on"'), 3)
        self.assertIn(f'href="/hw/dev/part/{MANY}/">Open the cable’s item page</a>', dlg)
        self.assertNotIn('id="cc-view-4"', html)                                 # a free position has nothing to view

    def test_change_working_device_lists_the_other_sides(self):
        html = self._get(PAGE).content.decode()
        others = html.split('id="cc-others"', 1)[1].split("</dialog>", 1)[0]
        for pid in (SHIELD, FCT, FILTER):
            self.assertIn(f'href="/hw/dev/part/{pid}/cables/"', others)
        self.assertIn("1 cable<", others)

    def test_change_working_device_is_the_same_dialog_for_one_other_side_or_none(self):
        api = _api()
        rows = api.get_subcomponents(FLANGE)["data"][:1]                         # the installed cable alone
        inner = api.get_subcomponents.side_effect
        api.get_subcomponents.side_effect = lambda pid: {"data": rows} if pid == FLANGE else inner(pid)
        html = self._get(PAGE, api).content.decode()
        self.assertIn('data-open="cc-others">Change working device</button>', html)
        others = html.split('id="cc-others"', 1)[1].split("</dialog>", 1)[0]
        self.assertEqual(others.count("/cables/"), 1)
        self.assertIn(f'href="/hw/dev/part/{SHIELD}/cables/"', others)
        self.assertIn("Scan another device", others)

        api.get_subcomponents.side_effect = lambda pid: {"data": []}             # nothing connected
        html = self._get(PAGE, api).content.decode()
        self.assertIn('data-open="cc-others">Change working device</button>', html)
        others = html.split('id="cc-others"', 1)[1].split("</dialog>", 1)[0]
        self.assertIn("No device on the other side yet.", others)
        self.assertIn("Scan another device", others)

    def test_a_cable_gets_one_line_and_a_link_to_its_item_page(self):
        html = self._get(f"/hw/dev/part/{INSTALLED}/cables/").content.decode()
        self.assertIn("is a cable", html)
        self.assertIn(f'href="/hw/dev/part/{INSTALLED}/">its item page</a>', html)
        self.assertNotIn('<table class="cc-table">', html)

    def test_an_item_with_no_cable_position_says_so(self):
        api = _api()
        api.get_component_type.side_effect = lambda t: {"data": {"category": "generic", "connectors": {}}}
        html = self._get(PAGE, api).content.decode()
        self.assertIn("has no position that takes a cable", html)

    def test_typed_or_scanned_pid_opens_that_devices_page(self):
        r = self.client.get("/hw/dev/cables/", {"pid": FLANGE.lower()})
        self.assertRedirects(r, PAGE, fetch_redirect_response=False)
        r = self.client.get("/hw/dev/cables/", {"pid": f"https://dbweb9.fnal.gov:8443/cdbdev/view/component/{FLANGE}"})
        self.assertRedirects(r, PAGE, fetch_redirect_response=False)
        html = self.client.get("/hw/dev/cables/", {"pid": "nonsense"}).content.decode()
        self.assertIn("doesn’t look like a PID", html)
        self.assertIn('placeholder="Scan or type its PID"', self.client.get("/hw/dev/cables/").content.decode())

    def test_an_unreadable_device_keeps_the_page_and_says_why(self):
        import requests as _rq
        api = _api()
        api.get_component.side_effect = _rq.exceptions.HTTPError("404 NOT FOUND")
        html = self._get(PAGE, api).content.decode()
        self.assertIn(f"Couldn’t read {FLANGE}", html)
        self.assertIn(f'value="{FLANGE}"', html)

    def test_page_works_on_prod(self):
        self.assertIn("3 / 4 connected", self._get(f"/hw/part/{FLANGE}/cables/").content.decode())

    @override_settings(HWDB_WRITE_INSTANCES=[])
    def test_an_instance_closed_to_writes_gets_the_page_read_only(self):
        html = self._get(PAGE).content.decode()
        self.assertIn("3 / 4 connected", html)
        for gone in ('id="cc-rm"', 'id="cc-connect"', 'data-connect="', 'name="remove"', "cc-rm-all", 'id="cc-bundle"'):
            self.assertNotIn(gone, html)
        api = _api()
        self.assertEqual(self._post(PAGE, {"remove": "ISH"}, api).status_code, 403)
        api.patch_subcomponents.assert_not_called()


class CableWritesTest(TestCase):
    """#227: connect and remove on the working side, the bundle / tray."""

    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("k", "k@k.io", "pw"))
        self.api = _api()

    def _get(self, url, data=None):
        with mock.patch("explore.views.mint_for", return_value="bearer"), \
             mock.patch("explore.views.FnalDbApiClient", return_value=self.api):
            return self.client.get(url, data or {})

    def _post(self, data, follow=True):
        with mock.patch("explore.views.mint_for", return_value="bearer"), \
             mock.patch("explore.views.FnalDbApiClient", return_value=self.api):
            return self.client.post(PAGE, data, follow=follow)

    # what the device holds, as read — every write sends the rest back unchanged
    AS_READ = {"ISH": f"{INSTALLED}.FCP Flange:1", "OSH": f"{ONE_END}.FCP Flange:1", "FCT.T": f"{MANY}.Flange:7",
               "ICO": None, "Board": f"{BOARD}-00009"}

    def _written(self):
        self.api.patch_subcomponents.assert_called_once()
        pid, payload = self.api.patch_subcomponents.call_args.args
        self.assertEqual((pid, payload["component"]), (FLANGE, {"part_id": FLANGE}))
        return payload["subcomponents"]

    def test_rows_get_connect_or_remove_and_the_bundle_column(self):
        html = self._get(PAGE).content.decode()
        self.assertIn(f'data-connect="ICO" data-n="4" data-types="{WARM}"', html)
        self.assertIn('data-expected="Top CRP bias warm cable"', html)
        # a row's Remove asks first (#233): the row's button only opens the question, which names what goes
        self.assertIn(f'data-remove="ISH" data-at="1 · ISH" data-what="{INSTALLED} · FCP Flange:1">Remove</button>', html)
        self.assertEqual(html.count('data-remove="'), 3)
        one = html.split('<dialog class="cc-dlg" id="cc-rm-one">', 1)[1].split("</dialog>", 1)[0]
        self.assertIn('data-close autofocus>Cancel</button>', one)                 # Enter cancels
        self.assertIn('class="es-btn cc-danger" form="cc-rm" name="remove" id="cc-r-go">Remove</button>', one)
        self.assertEqual(html.count('name="remove"'), 1)                           # the one submit is the confirmed one
        self.assertIn('data-open="cc-rm-all">Remove all</button>', html)
        dlg = html.split('<dialog class="cc-dlg" id="cc-rm-all">', 1)[1].split("</dialog>", 1)[0]
        self.assertIn(f'⚠ This removes all 3 connections on <span class="mono">{FLANGE}</span> from HWDB. It cannot be undone', dlg)
        for n, pos, cable in ((1, "ISH", INSTALLED), (2, "OSH", ONE_END), (3, "FCT.T", MANY)):    # what goes, named
            self.assertIn(f'<b>{n} · {pos}</b><span class="mono">{cable}</span>', dlg)
        self.assertIn('data-close autofocus>Cancel</button>', dlg)                 # Enter cancels
        self.assertIn('name="remove_all" value="1">Remove all 3</button>', dlg)
        self.assertIn(f'<td class="cc-bun"><a class="mono" href="/hw/dev/part/{TRAY}/">{TRAY}</a>'
                      '<span class="cc-l2">Top CRP bias warm cable bundle · also at 2</span></td>', html)
        self.assertIn('id="cc-bundle" name="bundle" value=""', html)
        self.assertNotIn("<template", html)                               # no bundle scanned: nothing offered

    def test_the_role_banner_shows_as_on_the_other_linking_pages(self):
        inner = self.api.get_component_type.side_effect
        self.api.get_component_type.side_effect = lambda t: {"data": {
            **inner(t)["data"], "roles": [{"id": 3, "name": "type-manager"}]}}
        with mock.patch("explore.views._my_roles", return_value=[]):
            html = self._get(PAGE).content.decode()
        self.assertIn("need one of the HWDB roles <b>type-manager</b>", html)

    def test_the_dialog_asks_for_a_cables_end_with_those_in_use_marked(self):
        d = self._get(PAGE, {"slots": ONE_END.lower(), "pos": "ICO"}).json()
        self.assertEqual(d, {"pid": ONE_END, "slots": [{"name": "FCP Flange:1", "used": True},
                                                       {"name": "HVS PS:1", "used": False}]})
        self.api.patch_subcomponents.assert_not_called()

    def test_a_cable_of_another_type_is_refused_naming_the_expected_type(self):
        said = "“ICO” takes Top CRP bias warm cable, not HVS Test Bundle 4 Ends."   # named off the type records
        self.assertEqual(self._get(PAGE, {"slots": MANY, "pos": "ICO"}).json(), {"error": said})
        html = self._post({"connect": "ICO", "pid": MANY, "end": "Flange:7"}).content.decode()
        self.assertIn(said, html)
        self.api.patch_subcomponents.assert_not_called()                  # before any write

    def test_a_non_cable_or_a_non_pid_is_refused(self):
        self.assertEqual(self._get(PAGE, {"slots": f"{BOARD}-00003", "pos": "Board"}).json(),
                         {"error": f"{BOARD}-00003 is not a cable."})
        self.assertEqual(self._get(PAGE, {"slots": "nonsense", "pos": "ICO"}).json(),
                         {"error": "“nonsense” doesn’t look like a PID."})

    def test_connect_writes_the_end_at_the_position_and_leaves_the_others(self):
        r = self._post({"connect": "ICO", "pid": FREE, "end": "HVS PS:1"}, follow=False)
        self.assertRedirects(r, PAGE, fetch_redirect_response=False)
        self.assertEqual(self._written(), {**self.AS_READ, "ICO": f"{FREE}.HVS PS:1"})

    def test_connect_keeps_the_bundle_on_the_way_back(self):
        r = self._post({"connect": "ICO", "pid": FREE, "end": "HVS PS:1", "bundle": TRAY}, follow=False)
        self.assertRedirects(r, f"{PAGE}?bundle={TRAY}", fetch_redirect_response=False)

    def test_connect_needs_an_end_the_cable_has_and_a_free_position(self):
        for data, said in (
                ({"connect": "ICO", "pid": FREE, "end": ""}, "Pick the cable’s END : connector."),
                ({"connect": "ICO", "pid": FREE, "end": "Nope:1"}, f"{FREE} has no “Nope:1”."),
                ({"connect": "ISH", "pid": FREE, "end": "HVS PS:1"}, "“ISH” already holds"),
                ({"connect": "Nowhere", "pid": FREE, "end": "HVS PS:1"}, "There is no “Nowhere” position.")):
            self.assertIn(said, self._post(data).content.decode())
        self.api.patch_subcomponents.assert_not_called()

    def test_hwdbs_refusal_is_shown_as_it_comes_and_nothing_changes(self):
        import requests as _rq
        resp = mock.Mock(status_code=409)
        resp.json.return_value = {"status": "ERROR", "data": f"The component '{FREE}.HVS PS:1' is already in use in 'X/Y'"}
        self.api.patch_subcomponents.side_effect = _rq.exceptions.HTTPError("409", response=resp)
        html = self._post({"connect": "ICO", "pid": FREE, "end": "HVS PS:1"}).content.decode()
        self.assertIn(f"HWDB refused — The component &#x27;{FREE}.HVS PS:1&#x27; is already in use in &#x27;X/Y&#x27;", html)
        self.assertIn("3 / 4 connected", html)

    def test_remove_empties_that_position_alone(self):
        html = self._post({"remove": "OSH"}).content.decode()
        self.assertEqual(self._written(), {**self.AS_READ, "OSH": None})
        self.assertIn(f"Removed {ONE_END}.FCP Flange:1 from “OSH”.", html)

    def test_remove_all_empties_every_cable_end_and_keeps_the_rest(self):
        html = self._post({"remove_all": "1"}).content.decode()
        self.assertEqual(self._written(), {"ISH": None, "OSH": None, "FCT.T": None, "ICO": None,
                                           "Board": f"{BOARD}-00009"})
        self.assertIn(f"Removed 3 connections from {FLANGE}.", html)

    def test_removing_nothing_writes_nothing(self):
        self.assertIn("“ICO” holds nothing to remove.", self._post({"remove": "ICO"}).content.decode())
        self.api.patch_subcomponents.assert_not_called()

    def test_the_cable_and_the_bundle_can_be_scanned_with_a_phone(self):
        """The checklists' phone route: the scanner page's link and QR for
        this device, a button at the Connect dialog's box and at the bundle
        box, and the feed the page listens to."""
        r = self._get(PAGE)
        phone, html = r.context["phone"], r.content.decode()
        self.assertEqual(phone["url"], f"http://testserver/hw/dev/scan/?target={FLANGE}&for=cables")
        self.assertEqual((phone["feed"], phone["ack"], phone["since"]),
                         (f"/hw/dev/scan/feed/?target={FLANGE}", "/hw/dev/scan/ack/", 0))
        self.assertIn(f'id="cc-phone-panel" hidden data-feed="/hw/dev/scan/feed/?target={FLANGE}" data-ack="/hw/dev/scan/ack/" data-since="0"', html)
        self.assertIn('class="es-btn quiet cc-phone" id="cc-c-phone" data-target="cc-c-pid"', html)
        self.assertIn('class="es-btn quiet cc-phone" data-target="cc-bundle" data-what="bundle / tray"', html)
        self.assertIn("<svg", phone["qr"])
        with override_settings(HWDB_WRITE_INSTANCES=[]):                           # the scan route is closed there too
            closed = self._get(PAGE).content.decode()
            self.assertNotIn('id="cc-phone-panel"', closed)
            self.assertNotIn('class="es-btn quiet cc-phone"', closed)

    def test_the_phones_scanner_page_speaks_of_cables(self):
        html = self.client.get(f"/hw/dev/scan/?target={FLANGE}&for=cables").content.decode()
        self.assertIn(f'<h1>Scan cables for <span style="font-family:ui-monospace,monospace;">{FLANGE}</span></h1>', html)
        self.assertIn("var CABLES = true,", html)
        self.assertNotIn("Scan into the checklist of", html)
        plain = self.client.get(f"/hw/dev/scan/?target={FLANGE}").content.decode()   # a checklist's page is as before
        self.assertIn("Scan into the checklist of", plain)
        self.assertIn("var CABLES = false,", plain)

    def test_a_scanned_bundle_fills_each_free_positions_list(self):
        html = self._get(PAGE, {"bundle": TRAY.lower()}).content.decode()
        self.assertIn(f'id="cc-bundle" name="bundle" value="{TRAY.lower()}"', html)
        self.assertIn("3 cables, offered at the free positions", html)
        self.assertIn(f'data-prefill="{FREE}"', html)
        cands = html.split('<template id="cc-cands-4">', 1)[1].split("</template>", 1)[0]
        self.assertEqual(cands.count("<button"), 3)
        self.assertIn(f'<button type="button" data-pid="{INSTALLED}" class="done">', cands)
        self.assertIn("connected at 1", cands)
        self.assertIn(f'<button type="button" data-pid="{FREE}">', cands)
        self.assertIn(">free<", cands)
        self.assertIn(f'<input type="hidden" name="bundle" value="{TRAY}">', html)
        self.api.patch_subcomponents.assert_not_called()                  # nothing linked until Connect

    def test_an_unreadable_bundle_keeps_the_page(self):
        import requests as _rq
        inner = self.api.get_subcomponents.side_effect

        def subs(pid):
            if pid == TRAY:
                raise _rq.exceptions.HTTPError("404 NOT FOUND")
            return inner(pid)
        self.api.get_subcomponents.side_effect = subs
        html = self._get(PAGE, {"bundle": TRAY}).content.decode()
        self.assertIn(f"Couldn’t read the bundle / tray {TRAY}", html)
        self.assertIn("3 / 4 connected", html)


class PartPageLinkTest(TestCase):
    """The item page of a device that holds a cable end links to the page."""

    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("k", "k@k.io", "pw"))

    def _page(self, pid):
        api = _api()
        for name in ("get_locations", "get_images", "get_test_types", "get_tests", "get_container"):
            getattr(api, name).return_value = {"data": []}
        with mock.patch("explore.views.mint_for", return_value="bearer"), \
             mock.patch("explore.views.FnalDbApiClient", return_value=api):
            return self.client.get(f"/hw/dev/part/{pid}/").content.decode()

    def test_a_device_holding_a_cable_end_links_to_its_cable_connections(self):
        self.assertIn(f'href="/hw/dev/part/{FLANGE}/cables/">Cable connections</a>', self._page(FLANGE))

    def test_a_cables_own_page_does_not(self):
        self.assertNotIn(">Cable connections</a>", self._page(INSTALLED))


class CablePictureTest(TestCase):
    """#228: the type's picture over the list, and its editor."""

    EDITOR = "/hw/dev/cables/picture/Z00100300064/"

    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("k", "k@k.io", "pw"))
        self.api = _api()

    def _call(self, method, url, data=None, **kw):
        with mock.patch("explore.views.mint_for", return_value="bearer"), \
             mock.patch("explore.views.FnalDbApiClient", return_value=self.api):
            return getattr(self.client, method)(url, data or {}, **kw)

    def test_the_page_shows_the_picture_with_the_rows_numbers_and_statuses(self):
        _with_picture(self.api)
        html = self._call("get", PAGE).content.decode()
        self.assertIn('<img src="/hw/dev/shipment-image/55/"', html)
        self.assertIn('class="cc-mk cc-installed" data-row="1" style="left: 10%; top: 20%;" title="ISH"', html)
        self.assertIn('class="cc-mk cc-available" data-row="4" style="left: 55.5%; top: 80%;" title="ICO"', html)
        self.assertEqual(html.count('class="cc-mk '), 2)                  # "Gone" and "Board" have no row
        self.assertIn('<tr class="cc-installed" data-row="1">', html)
        self.assertIn(f'href="{self.EDITOR}?item={FLANGE}" title="The picture and markers of this type — every item of the type shows them">Edit cabling guide</a>', html)

    def test_a_type_with_no_picture_shows_the_list_alone_and_a_link_to_the_editor(self):
        html = self._call("get", PAGE).content.decode()
        self.assertNotIn('id="cc-map"', html)
        self.assertIn("3 / 4 connected", html)
        self.assertIn(f'href="{self.EDITOR}?item={FLANGE}"', html)
        self.assertIn(">Add cabling guide</a>", html)
        self.assertLess(html.index(">Add cabling guide</a>"), html.index('<table class="cc-table">'))   # where the picture would be

    def test_the_link_is_for_those_who_may_edit(self):
        inner = self.api.get_component_type.side_effect
        self.api.get_component_type.side_effect = lambda t: {"data": {**inner(t)["data"], "roles": [{"id": 3, "name": "type-manager"}]}}
        with mock.patch("explore.views._my_roles", return_value=[]):
            self.assertNotIn("cables/picture/", self._call("get", PAGE).content.decode())
        with override_settings(HWDB_WRITE_INSTANCES=[]):
            self.assertNotIn("cables/picture/", self._call("get", PAGE).content.decode())
            self.assertEqual(self._call("get", self.EDITOR).status_code, 403)

    def test_the_editor_lists_the_cable_positions_and_the_stored_markers(self):
        _with_picture(self.api)
        r = self._call("get", self.EDITOR, {"item": FLANGE})
        ed = r.context["editor"]
        self.assertEqual(ed["positions"], ["ISH", "OSH", "FCT.T", "ICO"])
        self.assertEqual([s["label"] for s in ed["map"]["slots"]], ["ISH", "ICO", "Gone", "Board"])   # the stale ones too, to be flagged
        self.assertEqual((ed["image"], ed["upload"]), ("/hw/dev/shipment-image/IMGID000/",
                                                       "/hw/dev/checklist-config/Z00100300064/asset/"))
        html = r.content.decode()
        self.assertIn('id="cm-data"', html)
        self.assertIn(f'href="/hw/dev/part/{FLANGE}/cables/">Cancel</a>', html)

    def test_save_posts_the_markers_onto_the_type_and_goes_back_to_the_device(self):
        posted = {"image_id": "55", "slots": [{"label": "ISH", "x": 12.345, "y": 20}, {"label": "Off", "x": 300, "y": 2}]}
        r = self._call("post", self.EDITOR, {"map": json.dumps(posted), "item": FLANGE})
        self.assertRedirects(r, PAGE, fetch_redirect_response=False)
        ptid, fileobj, fname = self.api.post_component_type_image.call_args.args
        self.assertEqual((ptid, fname), ("Z00100300064", "Cable_map_Z00100300064.json"))
        saved = json.loads(fileobj.getvalue())
        self.assertEqual((saved["image_id"], saved["slots"], saved["updated_by"]),
                         ("55", [{"label": "ISH", "x": 12.35, "y": 20.0}], "k"))

    def test_save_needs_a_picture_and_shows_hwdbs_refusal(self):
        html = self._call("post", self.EDITOR, {"map": json.dumps({"image_id": "", "slots": []})}, follow=True).content.decode()
        self.assertIn("Upload a picture first.", html)
        self.api.post_component_type_image.assert_not_called()
        self.api.post_component_type_image.return_value = {"status": "ERROR", "data": "Not authorized"}
        html = self._call("post", self.EDITOR, {"map": json.dumps({"image_id": "55", "slots": []})}, follow=True).content.decode()
        self.assertIn("HWDB refused the picture’s markers — Not authorized", html)


class CablingGuideTest(TestCase):
    """#235: the editor under its name, reached from the type's page, and the
    picture's image id."""

    EDITOR = "/hw/dev/cables/picture/Z00100300064/"
    NAMES = "/hw/dev/checklist-names/Z00100300064/"

    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("k", "k@k.io", "pw"))
        self.api = _api()
        H.objects.create(instance="dev", level=H.LEVEL_TYPE, system_id=1, system_name="S", subsystem_id=3,
                         subsystem_name="SS", name="Top CRP bias warm cable", part_type_id=WARM, category="cable")

    def _call(self, method, url, data=None, **kw):
        with mock.patch("explore.views.mint_for", return_value="bearer"), \
             mock.patch("explore.views.FnalDbApiClient", return_value=self.api):
            return getattr(self.client, method)(url, data or {}, **kw)

    def test_the_type_pages_lazy_answer_says_whether_to_link_the_guide(self):
        self.assertEqual(self._call("get", self.NAMES).json(), {"checklists": []})          # not asked: nothing read for it
        self.api.get_component_type.assert_not_called()
        self.assertEqual(self._call("get", self.NAMES, {"cabling": 1}).json(), {"checklists": [], "cabling_guide": True})
        self.assertEqual(self.api.get_component_type.call_count, 1)                         # the type's record, nothing else
        board = f"/hw/dev/checklist-names/{BOARD}/"                                         # no position takes a cable
        self.assertFalse(self._call("get", board, {"cabling": 1}).json()["cabling_guide"])
        H.objects.filter(part_type_id=WARM).delete()                                        # the mirror's word alone
        self.assertFalse(self._call("get", self.NAMES, {"cabling": 1}).json()["cabling_guide"])

    def test_the_answer_is_no_without_one_of_the_types_roles(self):
        inner = self.api.get_component_type.side_effect
        self.api.get_component_type.side_effect = lambda t: {"data": {**inner(t)["data"], "roles": [{"id": 3, "name": "type-manager"}]}}
        with mock.patch("explore.views._my_roles", return_value=[]):
            self.assertFalse(self._call("get", self.NAMES, {"cabling": 1}).json()["cabling_guide"])
        with mock.patch("explore.views._my_roles", return_value=[{"id": 3, "name": "type-manager"}]):
            self.assertTrue(self._call("get", self.NAMES, {"cabling": 1}).json()["cabling_guide"])

    def test_the_type_page_holds_a_cabling_line_hidden_until_the_answer(self):
        from explore import navigation
        from explore.models import ConsortiumTypeOverride
        from explore.tests.test_events import _node
        sipm = "D00400300001"
        _node(sipm)
        url = navigation.leaf_path_for("prod", sipm)
        html = self.client.get(url).content.decode()
        self.assertIn(f'<dt id="cg-dt" hidden>Cabling</dt><dd id="cg-dd" class="span" hidden><a href="/hw/cables/picture/{sipm}/" target="_blank"', html)
        self.assertIn('>Cabling Guide <span aria-hidden="true">', html)
        self.assertIn('(cgDd ? "?cabling=1" : "")', html)                                   # asked for only where the line is
        # Chao 2026-11-23: system and subsystem in one field, no Test events line
        self.assertIn('<dt>System</dt><dd>FD-VD TDE (57) <span class="crumbs-sep">›</span> Digital electronics (2)</dd>', html)
        self.assertNotIn("<dt>Subsystem</dt>", html)
        self.assertNotIn("Test events</dt>", html)
        ConsortiumTypeOverride.objects.create(instance="prod", part_type_id=sipm)           # no items, no guide: not asked
        html = self.client.get(url).content.decode()
        self.assertNotIn('id="cg-dd"', html)
        self.assertIn('<dt>System</dt><dd class="span">FD-VD TDE (57) ', html)               # no Items cell beside it
        ConsortiumTypeOverride.objects.all().delete()
        with override_settings(HWDB_WRITE_INSTANCES=[]):
            self.assertNotIn('id="cg-dd"', self.client.get(url).content.decode())

    def test_opened_from_the_type_the_editor_goes_back_to_the_types_page(self):
        with mock.patch("explore.views.navigation.leaf_path_for", return_value="/hw/dev/the-type/"):
            html = self._call("get", self.EDITOR).content.decode()
            self.assertIn("<title>Cabling Guide · ", html)
            self.assertIn("<h1>Cabling Guide<span", html)
            self.assertIn('<span class="sep">›</span><a href="/hw/dev/the-type/">Z00100300064</a>', html)
            self.assertIn('<span class="sep">›</span>Cabling Guide', html)
            self.assertIn('href="/hw/dev/the-type/">Cancel</a>', html)
            posted = {"image_id": "55", "slots": [{"label": "ISH", "x": 10, "y": 20}]}
            r = self._call("post", self.EDITOR, {"map": json.dumps(posted)})
            self.assertRedirects(r, "/hw/dev/the-type/", fetch_redirect_response=False)
        self.assertEqual(self.api.post_component_type_image.call_args.args[2], "Cable_map_Z00100300064.json")   # stored as before

    def test_opened_from_an_item_the_crumbs_go_through_its_cable_connections(self):
        html = self._call("get", self.EDITOR, {"item": FLANGE}).content.decode()
        self.assertIn(f'<a href="/hw/dev/part/{FLANGE}/cables/">Cable connections</a>', html)
        self.assertIn('<span class="sep">›</span>Cabling Guide', html)

    def test_the_editor_shows_the_pictures_image_id_with_a_copy_button(self):
        _with_picture(self.api)
        r = self._call("get", self.EDITOR)
        self.assertEqual(r.context["editor"]["map"]["image_id"], "55")       # the page fills the line from it, and again after an upload
        html = r.content.decode()
        self.assertIn('id="cm-idline" hidden>Image id <code class="mono" id="cm-id"></code>', html)
        self.assertIn('<button type="button" class="es-btn quiet" id="cm-copy">Copy</button>', html)


class ConnectListTest(TestCase):
    """#236: Connect's List — the pick list's table of the position's cables,
    a short page at a time, each with its END : connectors read, the free
    ones offered."""

    def setUp(self):
        from explore.models import HwdbComponentEvent as C
        self.C = C
        self.client.force_login(get_user_model().objects.create_user("k", "k@k.io", "pw"))
        self.api = _api()
        for pid, serial in ((INSTALLED, ""), (ONE_END, "SN-21"), (FREE, ""), (f"{BOARD}-00009", "")):
            C.objects.create(instance="dev", part_type_id=pid.rsplit("-", 1)[0], part_id=pid, serial_number=serial, status_id=120,
                             status="QA/QC Tests - Passed All", qaqc_uploaded=True, certified_qaqc=False, institution="BNL")

    def _list(self, **params):
        with mock.patch("explore.views.mint_for", return_value="bearer"), \
             mock.patch("explore.views.FnalDbApiClient", return_value=self.api):
            return self.client.get(PAGE, params).json()

    def test_each_cable_shown_comes_with_its_connectors_those_in_use_marked(self):
        d = self._list(cables=f"{WARM},{BOARD}")
        self.assertEqual([r["part_id"] for r in d["rows"]], [INSTALLED, ONE_END, FREE])          # the board type is no cable type
        used = {r["part_id"]: [(s["name"], s["used"]) for s in r["slots"]] for r in d["rows"]}
        self.assertEqual(used[INSTALLED], [("FCP Flange:1", True), ("HVS PS:1", True)])
        self.assertEqual(used[ONE_END], [("FCP Flange:1", True), ("HVS PS:1", False)])
        self.assertEqual(used[FREE], [("FCP Flange:1", False), ("HVS PS:1", False)])
        row = d["rows"][1]                                                                       # the pick list's columns, and the serial
        self.assertEqual((row["status"], row["linkable"], row["qc_up"], row["qc_cert"], row["institution"], row["serial"], row["part_type_id"]),
                         ("QA/QC Tests - Passed All", True, True, False, "BNL", "SN-21", WARM))
        self.assertEqual(d["types"], {WARM: WARM})                                               # not in the mirror: its id for a name
        self.assertEqual((d["total"], d["page"], d["pages"], d["per"]), (3, 1, 1, 8))
        self.assertEqual(sorted(c.args[0] for c in self.api.get_subcomponents.call_args_list), sorted([INSTALLED, ONE_END, FREE]))
        self.assertEqual(sorted(c.args[0] for c in self.api.get_component_type.call_args_list), sorted([WARM, BOARD]))

    def test_only_the_page_shown_is_read_and_the_search_narrows(self):
        for n in range(30, 40):
            self.C.objects.create(instance="dev", part_type_id=WARM, part_id=f"{WARM}-000{n}", status_id=120)
        d = self._list(cables=WARM, page="2")
        self.assertEqual((d["total"], d["page"], d["pages"], len(d["rows"])), (13, 2, 2, 5))
        self.assertEqual(self.api.get_subcomponents.call_count, 5)                                 # 13 cables of the type, 5 shown
        self.assertEqual([r["part_id"] for r in self._list(cables=WARM, q="sn-2")["rows"]], [ONE_END])  # by serial number
        self.assertEqual([r["part_id"] for r in self._list(cables=WARM, q="00022")["rows"]], [FREE])    # by PID
        self.assertEqual(self._list(cables=WARM, q="nothing")["rows"], [])

    def test_a_cable_that_could_not_be_read_is_listed_without_connectors(self):
        inner = self.api.get_subcomponents.side_effect

        def rows(pid):
            if pid == ONE_END or (pid == FREE and not tried.count(FREE)):
                tried.append(pid)
                raise requests.ConnectionError("down")
            return inner(pid)
        tried = []
        self.api.get_subcomponents.side_effect = rows
        d = self._list(cables=WARM)
        self.assertEqual([(r["part_id"], r["slots"] is None) for r in d["rows"]], [(INSTALLED, False), (ONE_END, True), (FREE, False)])
        self.assertEqual(sorted(tried), sorted([ONE_END, ONE_END, FREE]))                          # each failed read tried once more

    def test_a_type_that_cannot_be_read_is_said_rather_than_an_empty_list(self):
        self.api.get_component_type.side_effect = requests.ConnectionError("down")
        self.assertEqual(self._list(cables=WARM), {"error": "Couldn’t read the cable type — down"})

    def test_several_cable_types_are_named_and_other_statuses_are_shown_only_on_request(self):
        H.objects.create(instance="dev", level=H.LEVEL_TYPE, system_id=1, system_name="S", subsystem_id=3, subsystem_name="SS",
                         name="HVS Test Bundle 4 Ends", part_type_id=BUNDLE4, category="cable")
        self.C.objects.create(instance="dev", part_type_id=BUNDLE4, part_id=MANY, status_id=120)
        self.C.objects.create(instance="dev", part_type_id=BUNDLE4, part_id=f"{BUNDLE4}-00002", status_id=150, status="In Rework")
        d = self._list(cables=f"{WARM},{BUNDLE4}", q=BUNDLE4)
        self.assertEqual(d["types"], {WARM: WARM, BUNDLE4: "HVS Test Bundle 4 Ends"})
        self.assertEqual([r["part_id"] for r in d["rows"]], [MANY])
        self.assertEqual([s["name"] for s in d["rows"][0]["slots"] if not s["used"]], ["Outer CRP:1"])
        self.api.get_subcomponents.reset_mock()
        d = self._list(cables=BUNDLE4, all="1")                                                    # "show all statuses"
        self.assertEqual([(r["part_id"], r["linkable"], r["slots"] is None) for r in d["rows"]],
                         [(MANY, True, False), (f"{BUNDLE4}-00002", False, True)])
        self.assertEqual([c.args[0] for c in self.api.get_subcomponents.call_args_list], [MANY])   # a display-only cable is not read

    def test_the_connect_dialog_opens_its_own_list(self):
        with mock.patch("explore.views.mint_for", return_value="bearer"), \
             mock.patch("explore.views.FnalDbApiClient", return_value=self.api):
            html = self.client.get(PAGE).content.decode()
        self.assertIn('<button type="button" class="es-btn quiet" id="cc-c-list" title="Cables of the expected type with their free END : connectors">List</button>', html)
        self.assertIn('<dialog class="cc-dlg" id="cc-pick">', html)
        self.assertIn('<thead><tr><th>Item</th><th class="ty">Type</th><th>Status</th><th>Uploaded</th><th>Certified</th><th class="inst">Institution</th></tr></thead>', html)
        self.assertIn('<input type="checkbox" id="cc-p-all"> show all statuses</label>', html)
        self.assertIn('fetch("?cables=" + encodeURIComponent(psel.value || ptypes)', html)
        # the list is the mirror's: the Link items page's two syncs, for the type(s) listed
        self.assertIn('<span class="cc-p-sync" id="cc-p-sync" data-sync-url="/hw/dev/sync-tests/__T__/">', html)
        self.assertIn('data-mode="incremental" title="Fetch this type’s new items from HWDB into the mirror — does not refresh items already listed">Sync new items</button>', html)
        self.assertIn('data-mode="components" title="Re-fetch every item of this type from HWDB — refreshes status and QC flags of items already listed">Re-sync</button>', html)
        self.assertNotIn('id="cl-pick-modal"', html)                                              # the shared dialog itself is not used here
        with override_settings(HWDB_WRITE_INSTANCES=[]), mock.patch("explore.views.mint_for", return_value="bearer"), \
             mock.patch("explore.views.FnalDbApiClient", return_value=self.api):
            self.assertNotIn('id="cc-pick"', self.client.get(PAGE).content.decode())


def _located(api, locations, data=None):
    """The items named in ``locations`` carry that device location in their
    Item Specs; the shield becomes a device with the installed cable's far
    END on it, and the flange's type template defines DATA."""
    inner_c, inner_t, inner_s = (api.get_component.side_effect, api.get_component_type.side_effect,
                                 api.get_subcomponents.side_effect)

    def component(pid):
        rec = inner_c(pid)["data"]
        specs = {"DATA": {**(data or {}), **({cabling.LOCATION_KEY: locations[pid]} if pid in locations else {})}}
        return {"data": {**rec, "serial_number": "S1", "comments": "c", "manufacturer": None, "specifications": [specs]}}

    def ctype(t):
        if t == "Z00100300061":
            return {"data": {"category": "generic", "connectors": {"CH01.2": WARM}}}
        extra = {"properties": {"specifications": [{"datasheet": {"DATA": {}}}]}} if t == "Z00100300064" else {}
        return {"data": {**inner_t(t)["data"], **extra}}

    def subcomponents(pid):
        if pid == SHIELD:
            return {"data": [{"part_id": f"{INSTALLED}.HVS PS:1", "type_name": "Top CRP bias warm cable",
                              "functional_position": "CH01.2", "operation": "mount"}]}
        return inner_s(pid)

    api.get_component.side_effect, api.get_component_type.side_effect = component, ctype
    api.get_subcomponents.side_effect = subcomponents
    api.patch_component.return_value = {"status": "OK"}
    return api


class CableLabelsTest(TestCase):
    """#229: the device location, the cable and bundle labels, and Print."""

    BOTH = {FLANGE: "FCP_201NE", SHIELD: "SEDM07.S04"}

    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("k", "k@k.io", "pw"))

    def _rows(self, locations, part_id=FLANGE):
        device = cabling.device_connections(_located(_api(), locations), "dev", part_id)
        return device, {r["position"]: r for r in device["rows"]}

    def _call(self, api, method="get", data=None, **kw):
        with mock.patch("explore.views.mint_for", return_value="bearer"), \
             mock.patch("explore.views.FnalDbApiClient", return_value=api):
            return getattr(self.client, method)(PAGE, data or {}, **kw)

    def test_the_location_is_read_off_the_item_specs_of_each_side(self):
        device, rows = self._rows(self.BOTH)
        self.assertEqual(device["location"], "FCP_201NE")
        self.assertEqual(rows["ISH"]["others"][0]["location"], "SEDM07.S04")
        self.assertEqual(rows["FCT.T"]["others"][0]["location"], "")          # nothing saved on that device
        self.assertEqual(cabling.location_of({}), "")
        self.assertEqual(cabling.location_of({"specifications": [{"DATA": {cabling.LOCATION_KEY: 7}}]}), "")

    def test_a_cable_connected_at_two_positions_gets_a_line_per_side(self):
        device, rows = self._rows(self.BOTH)
        self.assertEqual(rows["ISH"]["label"], {"lines": ["FCP_201NE.ISH", "SEDM07.S04.CH01.2"],
                                                "text": "FCP_201NE.ISH-SEDM07.S04.CH01.2", "incomplete": False})
        self.assertIsNone(rows["OSH"]["label"])                               # connected at one position
        self.assertIsNone(rows["FCT.T"]["label"])                             # at three
        self.assertEqual(device["n_labelled"], 1)

    def test_the_label_is_the_same_from_either_working_side(self):
        here = self._rows(self.BOTH)[1]["ISH"]["label"]
        there = self._rows(self.BOTH, SHIELD)[1]["CH01.2"]["label"]
        self.assertEqual(here, there)

    def test_a_side_with_no_location_is_its_position_alone_and_the_label_incomplete(self):
        label = self._rows({FLANGE: "FCP_201NE"})[1]["ISH"]["label"]
        self.assertEqual((label["lines"], label["incomplete"]), (["FCP_201NE.ISH", "CH01.2"], True))

    def test_two_connectors_of_one_end_make_no_label(self):
        api = _located(_api(), self.BOTH)
        inner = api.get_subcomponents.side_effect
        many = [{"part_id": f"{FLANGE}.FCT.T", "cable_connector": "Flange:7", "operation": "mount"},
                {"part_id": f"{SHIELD}.X", "cable_connector": "Flange:8", "operation": "mount"}]
        api.get_subcomponents.side_effect = lambda pid: {"data": many} if pid == MANY else inner(pid)
        row = {r["position"]: r for r in cabling.device_connections(api, "dev", FLANGE)["rows"]}["FCT.T"]
        self.assertEqual((row["connected"], row["label"]), (2, None))

    def test_a_bundle_is_labelled_with_the_two_locations(self):
        rows = self._rows(self.BOTH)[1]
        self.assertEqual(rows["ISH"]["bundle"]["label"], "SEDM07.S04/FCP_201NE")          # in PID order
        self.assertEqual(rows["OSH"]["bundle"]["label"], "SEDM07.S04/FCP_201NE")          # the same bundle
        self.assertEqual(self._rows(self.BOTH, SHIELD)[1]["CH01.2"]["bundle"]["label"], "SEDM07.S04/FCP_201NE")
        self.assertEqual(self._rows({FLANGE: "FCP_201NE"})[1]["ISH"]["bundle"]["label"], "")  # a location missing

    def test_a_bundle_going_to_more_than_two_devices_has_no_label(self):
        api = _located(_api(), {**self.BOTH, FCT: "FCT_3"})
        inner = api.get_subcomponents.side_effect
        one_end = [{"part_id": f"{FLANGE}.OSH", "cable_connector": "FCP Flange:1", "operation": "mount"},
                   {"part_id": f"{FCT}.IN2", "cable_connector": "HVS PS:1", "operation": "mount"}]
        api.get_subcomponents.side_effect = lambda pid: {"data": one_end} if pid == ONE_END else inner(pid)
        rows = {r["position"]: r for r in cabling.device_connections(api, "dev", FLANGE)["rows"]}
        self.assertEqual(rows["OSH"]["label"]["text"], "FCP_201NE.OSH-FCT_3.IN2")
        self.assertEqual(rows["ISH"]["bundle"]["label"], "")

    def test_print_jobs_follow_the_rows_and_what_is_asked(self):
        device = self._rows(self.BOTH)[0]

        def jobs(what, show="both"):
            return [(d["part_id"], d["lines"], [e["element type"] for e in lay["elements"]])
                    for lay, d in cabling.label_jobs(device, what, show, "qr", False, "Letter-3x10-Avery")]

        self.assertEqual(jobs("all"), [(INSTALLED, ["FCP_201NE.ISH", "SEDM07.S04.CH01.2"], ["qr", "text", "text", "part id"]),
                                       (ONE_END, [], ["qr", "part id"]),              # no label: the PID only
                                       (MANY, [], ["qr", "part id"])])
        self.assertEqual([j[0] for j in jobs("all", "label")], [INSTALLED])           # the unlabelled left out
        self.assertEqual(jobs("1", "label"), [(INSTALLED, ["FCP_201NE.ISH", "SEDM07.S04.CH01.2"], ["text", "text"])])
        self.assertEqual(jobs("1", "pid"), [(INSTALLED, [], ["qr", "part id"])])
        self.assertEqual(jobs("b1"), [(TRAY, ["SEDM07.S04/FCP_201NE"], ["qr", "text", "part id"])])
        self.assertEqual((jobs("4"), jobs("b3"), jobs("9"), jobs("")), ([], [], [], []))   # free, no bundle, no row

    def test_every_sheet_gets_a_layout_with_the_type_name_and_bar_code_on_request(self):
        from explore import labels
        for sheet, tpl in labels.TEMPLATES.items():
            lay = cabling.label_layout(sheet, ["A.B", "C.D"], "bar", True)
            self.assertEqual([e["element type"] for e in lay["elements"]], ["bar", "text", "text", "external id", "part name"])
            self.assertEqual(lay["orientation"], "landscape" if tpl["label size"][1] > tpl["label size"][0] else "portrait")
            sizes = {e["font size"] for e in lay["elements"] if e["element type"] == "text"}
            self.assertEqual(len(sizes), 1)                                   # the label's lines at one size

    def test_the_page_shows_locations_labels_and_print(self):
        html = self._call(_located(_api(), self.BOTH)).content.decode()
        self.assertIn('name="location" value="FCP_201NE" maxlength="60"', html)
        self.assertIn('name="set_location" value="1"', html)
        self.assertIn('<b class="mono">SEDM07.S04</b> · <b>CH01.2</b>', html)
        self.assertIn('Label <span class="mono">FCP_201NE.ISH-SEDM07.S04.CH01.2</span></span>', html)
        self.assertIn(f'data-print="1" data-at="1 · ISH" data-pid="{INSTALLED}" data-type="Top CRP bias warm cable" '
                      'data-l1="FCP_201NE.ISH" data-l2="SEDM07.S04.CH01.2">Print</button>', html)
        self.assertIn(f'data-print="2" data-at="2 · OSH" data-pid="{ONE_END}" data-type="Top CRP bias warm cable" '
                      'data-l1="" data-l2="">Print</button>', html)
        self.assertIn('data-print="all" data-count="3" data-labelled="1">Print labels</button>', html)
        self.assertIn(f'data-print="b1" data-at="bundle / tray" data-pid="{TRAY}"', html)
        self.assertIn('<option value="Letter-3x10-Avery" selected>', html)
        dlg = html.split('id="cc-view-1"', 1)[1].split("</dialog>", 1)[0]
        self.assertIn('<div class="cc-lbl"><span>FCP_201NE.ISH</span><span>SEDM07.S04.CH01.2</span></div>', dlg)
        self.assertIn('<b class="mono">FCP_201NE</b> · <b>ISH</b>', dlg)
        self.assertIn('data-print-row="1"', dlg)

    def test_an_incomplete_label_says_so(self):
        html = self._call(_located(_api(), {SHIELD: "SEDM07.S04"})).content.decode()
        self.assertIn('Label <span class="mono">ISH-SEDM07.S04.CH01.2</span> · location missing</span>', html)
        self.assertIn("Incomplete — a device location is missing.", html)

    def test_the_location_is_read_only_without_the_role_or_where_writes_are_closed(self):
        api = _located(_api(), self.BOTH)
        inner = api.get_component_type.side_effect
        api.get_component_type.side_effect = lambda t: {"data": {**inner(t)["data"], "roles": [{"id": 3, "name": "type-manager"}]}}
        with mock.patch("explore.views._my_roles", return_value=[]):
            html = self._call(api).content.decode()
        self.assertNotIn('name="set_location"', html)
        self.assertIn('Device location<span class="cc-val mono">FCP_201NE</span>', html)
        with override_settings(HWDB_WRITE_INSTANCES=[]):
            html = self._call(api).content.decode()
            self.assertNotIn('name="set_location"', html)
            self.assertIn(">Print labels</button>", html)                     # printing writes nothing
            self.assertEqual(self._call(api, "post", {"set_location": "1", "location": "X"}).status_code, 403)
        api.patch_component.assert_not_called()

    def test_saving_the_location_writes_its_one_key_and_keeps_the_rest(self):
        api = _located(_api(), {FLANGE: "OLD"}, data={"SubPIDs": ["a"], "Checklist": {"Torque": 5}})
        html = self._call(api, "post", {"set_location": "1", "location": "  FCP_201NE  "}, follow=True).content.decode()
        self.assertIn("Device location saved — FCP_201NE.", html)
        pid, payload = api.patch_component.call_args.args
        self.assertEqual(pid, FLANGE)
        self.assertEqual(payload["specifications"], {"DATA": {"SubPIDs": ["a"], "Checklist": {"Torque": 5},
                                                              cabling.LOCATION_KEY: "FCP_201NE"}})
        self.assertEqual((payload["serial_number"], payload["comments"]), ("S1", "c"))
        api.patch_subcomponents.assert_not_called()

    def test_a_blank_location_removes_the_key_and_a_refusal_is_shown(self):
        api = _located(_api(), {FLANGE: "OLD"}, data={"SubPIDs": ["a"]})
        html = self._call(api, "post", {"set_location": "1", "location": " "}, follow=True).content.decode()
        self.assertIn("Device location cleared.", html)
        self.assertEqual(api.patch_component.call_args.args[1]["specifications"], {"DATA": {"SubPIDs": ["a"]}})
        api.patch_component.return_value = {"status": "ERROR", "data": "Not authorized"}
        html = self._call(api, "post", {"set_location": "1", "location": "X"}, follow=True).content.decode()
        self.assertIn("Couldn’t save the device location — Not authorized", html)

    def test_print_answers_a_sheet_of_the_label_generator(self):
        import fitz
        api = _located(_api(), self.BOTH)
        r = self._call(api, data={"print": "all", "show": "both", "code": "qr", "name": "1", "sheet": "Letter-2x5-Avery"})
        self.assertEqual((r.status_code, r["Content-Type"]), (200, "application/pdf"))
        self.assertIn(f"cable_labels_{FLANGE}.pdf", r["Content-Disposition"])
        doc = fitz.open(stream=r.content, filetype="pdf")
        self.assertEqual(doc.page_count, 1)                                   # the labels alone, no intro pages
        text = doc.load_page(0).get_text()
        for expected in ("FCP_201NE.ISH", "SEDM07.S04.CH01.2", INSTALLED, ONE_END, MANY, "Top CRP bias warm cable"):
            self.assertIn(expected, text)
        self.assertLess(text.index(INSTALLED), text.index(ONE_END))           # in row order
        self.assertNotIn(INSTALLED, [c.args[0] for c in api.get_component.call_args_list])   # a QR needs no read

    def test_a_bar_code_reads_the_external_id_and_an_empty_print_goes_back(self):
        import fitz
        api = _located(_api(), self.BOTH)
        inner = api.get_component.side_effect
        api.get_component.side_effect = lambda pid: {"data": {**inner(pid)["data"], "part_id": pid, "country_code": "US",
                                                              "institution": {"id": 186}}}
        r = self._call(api, data={"print": "1", "show": "pid", "code": "bar", "sheet": "nonsense"})
        self.assertIn(f"{INSTALLED}-US186", fitz.open(stream=r.content, filetype="pdf").load_page(0).get_text())
        r = self._call(api, data={"print": "4"}, follow=True)
        self.assertRedirects(r, PAGE)
        self.assertIn("Nothing to print.", r.content.decode())
