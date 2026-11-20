"""The Cable connections page (#226): one endpoint device, its positions that
take a cable, and where each connected cable goes. HWDB is mocked with rows
shaped as dev answers them since 2026-11-20, the client having taken the
country / institution codes off.

    python manage.py test explore.tests.test_cabling
"""

from __future__ import annotations

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from explore import cabling
from explore.models import HierarchyNode as H

FLANGE = "Z00100300064-00004"
WARM, BUNDLE4, BOARD = "Z00100300073", "Z00100300035", "D08100100004"
INSTALLED, ONE_END, MANY = f"{WARM}-00020", f"{WARM}-00021", f"{BUNDLE4}-00001"
SHIELD, FCT, FILTER = "Z00100300061-00001", "Z00100300066-00003", "Z00100300068-00012"
PAGE = f"/hw/dev/part/{FLANGE}/cables/"


def _api():
    """A flange with five positions: one cable connected at both its ENDs,
    one connected here alone, one 4-END cable going to two other devices,
    one free cable position, and a position that takes a board."""
    types = {
        "Z00100300064": {"category": "generic", "connectors": {
            "ISH": WARM, "OSH": WARM, "FCT.T": BUNDLE4, "ICO": WARM, "Board": BOARD}},
        WARM: {"category": "cable", "full_name": "Z.Sandbox.Test.Top CRP bias warm cable",
               "connectors": {"FCP Flange:1": None, "HVS PS:1": None}},
        BUNDLE4: {"category": "cable", "full_name": "Z.Sandbox.Test.HVS Test Bundle 4 Ends",
                  "connectors": {"Flange:7": None, "FC Termination:1": None, "Inner CRP:1": None, "Outer CRP:1": None}},
        BOARD: {"category": "generic", "full_name": "D.FD CE.Chips.LArASIC", "connectors": {}},
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
    }
    api = mock.MagicMock()
    api.get_component.side_effect = lambda pid: {"data": {
        "category": "cable" if pid.rsplit("-", 1)[0] in (WARM, BUNDLE4) else "generic",
        "component_type": {"name": "Bias FT flange" if pid == FLANGE else "Top CRP bias warm cable"}}}
    api.get_component_type.side_effect = lambda t: {"data": types[t]}
    api.get_subcomponents.side_effect = lambda pid: {"data": rows.get(pid, [])}
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
        self.assertEqual(r["others"], [{"part_id": SHIELD, "type_name": "CRP Shield (slot 4)", "here": False,
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
        self.assertEqual(by["ISH"]["others"], [{"part_id": FILTER, "type_name": "Filter box", "here": False, "connections": [
            {"position": "FB1", "end": "Inner CRP:1"}, {"position": "FB2", "end": "Inner CRP:2"}]}])
        self.assertEqual([(o["here"], o["connections"]) for o in by["ICO"]["others"]],
                         [(True, [{"position": "Board", "end": "HVS PS:1"}])])
        self.assertEqual([o["part_id"] for o in device["others"]], [FILTER])     # not the device itself

    def test_the_other_side_devices_with_how_many_cables_go_there(self):
        self.assertEqual([(o["part_id"], o["type_name"], o["cables"]) for o in self.device["others"]],
                         [(SHIELD, "CRP Shield (slot 4)", 1), (FCT, "FC termination board", 1), (FILTER, "Filter box", 1)])

    def test_reads_are_bounded_by_the_device(self):
        """Its record, its positions, each connected cable's rows once, a type
        record per type — no item of the other side, no listing."""
        self.assertEqual(self.api.get_component.call_count, 1)
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

    def test_a_cable_linked_without_an_end_is_not_a_connection(self):
        api = _api()
        rows = [{"part_id": ONE_END, "type_name": "Top CRP bias warm cable",
                 "functional_position": "ICO", "operation": "mount"}]
        api.get_subcomponents.side_effect = lambda pid: {"data": rows if pid == FLANGE else []}
        device = cabling.device_connections(api, "dev", FLANGE)
        r = {r["position"]: r for r in device["rows"]}["ICO"]
        self.assertEqual((r["status"], r["cable"], r["end"]), ("noend", ONE_END, None))
        self.assertEqual(device["n_connected"], 0)

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
        dlg = html.split('id="cc-view-3"', 1)[1].split("</dialog>", 1)[0]
        self.assertIn("Connection at 3 · FCT.T", dlg)
        self.assertIn("3 of 4 connectors connected", dlg)
        self.assertEqual(dlg.count("<h3>Other side</h3>"), 2)
        self.assertIn("· FC Termination:1", dlg)
        self.assertIn(f'href="/hw/dev/part/{MANY}/">Open the cable’s item page</a>', dlg)
        self.assertNotIn('id="cc-view-4"', html)                                 # a free position has nothing to view

    def test_change_working_device_lists_the_other_sides(self):
        html = self._get(PAGE).content.decode()
        others = html.split('id="cc-others"', 1)[1].split("</dialog>", 1)[0]
        for pid in (SHIELD, FCT, FILTER):
            self.assertIn(f'href="/hw/dev/part/{pid}/cables/"', others)
        self.assertIn("1 cable<", others)

    def test_one_other_side_is_a_straight_link(self):
        api = _api()
        rows = api.get_subcomponents(FLANGE)["data"][:1]                         # the installed cable alone
        inner = api.get_subcomponents.side_effect
        api.get_subcomponents.side_effect = lambda pid: {"data": rows} if pid == FLANGE else inner(pid)
        html = self._get(PAGE, api).content.decode()
        self.assertIn(f'<a class="es-btn quiet" href="/hw/dev/part/{SHIELD}/cables/"', html)
        self.assertNotIn('id="cc-others"', html)

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

    def test_page_is_read_only_and_works_on_prod(self):
        html = self._get(f"/hw/part/{FLANGE}/cables/").content.decode()
        self.assertIn("3 / 4 connected", html)
        self.assertNotIn("<form method=\"post\"", html)


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
