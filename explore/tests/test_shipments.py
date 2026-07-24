"""Tests for the Shipment Tracker core slice (issue #43, ADR-0013).

Covers the curation lookup, the latest-location sync engine, and the
shipping-leaf rendering. HWDB fetch is mocked — no network.

    python manage.py test explore
"""

from __future__ import annotations

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from explore import curation, navigation, parts, shipments
from explore.models import HierarchyNode as H
from explore.models import HwdbComponentEvent, ShipmentItem
from hwdb.fnal.bearer import FnalLinkRequired, FnalUnavailable

SHIP_PTID = "D08120200001"  # curated CE Shipping box (FD CE › CE Shipping Box)


def _ship_leaf(ptid=SHIP_PTID, synced=True):
    """Build the FD CE › CE Shipping Box chain + the shipping-box leaf.

    ``synced`` stamps BOTH sync markers (boxes are regular components too, so
    a lived-in leaf has shipments_synced_at and tests_synced_at); pass
    synced=False to test the never-synced (auto-sync) state.
    """
    sys, _ = H.objects.get_or_create(
        level=H.LEVEL_SYSTEM, system_id=81, subsystem_id=None, part_type_id="",
        defaults={"system_name": "FD CE", "name": "FD CE"})
    sub, _ = H.objects.get_or_create(
        level=H.LEVEL_SUBSYSTEM, system_id=81, subsystem_id=202, part_type_id="",
        defaults={"parent": sys, "system_name": "FD CE",
                  "subsystem_name": "CE Shipping Box", "name": "CE Shipping Box"})
    return H.objects.create(
        level=H.LEVEL_TYPE, parent=sub, system_id=81, system_name="FD CE",
        subsystem_id=202, subsystem_name="CE Shipping Box", name="CE Shipping box",
        part_type_id=ptid, n_components=2,
        full_name="D.FD CE.CE Shipping Box.CE Shipping box",
        shipments_synced_at=timezone.now() if synced else None,
        tests_synced_at=timezone.now() if synced else None)


def _loc(name, lid, arrived):
    return {"arrived": arrived, "location": {"id": lid, "name": name},
            "creator": "x", "comments": ""}


def _sub(pos="Slot 1"):
    return {"part_id": "P-" + pos, "type_name": "FEMB",
            "functional_position": pos, "operation": "mount"}


# Default spec DATA for fake boxes: a recorded Shipping Checklist, so
# timeline-derived SHIPPED dates survive the #73 gate unless a test says
# otherwise via comp_by_pid.
_SHIPPED_SPECS = {"Shipping Checklist": [{"Carrier": "FedEx"}]}


def _fake_client(items, locs_by_pid, subs_by_pid=None, comp_by_pid=None):
    subs_by_pid = subs_by_pid or {}
    comp_by_pid = comp_by_pid if comp_by_pid is not None else {}
    client = mock.MagicMock()
    # sync lists items via _make_request (paginated); return a single page.
    client._make_request.side_effect = lambda method, endpoint, data=None, params=None: {
        "data": items, "pagination": {"pages": 1}}
    client.get_locations.side_effect = lambda pid: {"data": locs_by_pid.get(pid, [])}
    client.get_subcomponents.side_effect = lambda pid: {"data": subs_by_pid.get(pid, [])}
    client.get_component.side_effect = lambda pid: {
        "data": {"specifications": [{"DATA": comp_by_pid.get(pid, _SHIPPED_SPECS)}]}}
    return client


class CurationTest(TestCase):
    def test_anchor_is_shipping_type(self):
        # Curated via the "81.202" whole-subsystem selector.
        self.assertTrue(curation.is_shipping_type("prod", SHIP_PTID))

    def test_other_type_is_not_shipping(self):
        self.assertFalse(curation.is_shipping_type("prod", "D05700200001"))


class LatestLocationTest(TestCase):
    def test_picks_max_arrived_not_list_order(self):
        locs = [
            _loc("In Transit", 0, "2026-06-10T00:00:00-05:00"),  # newest, first
            _loc("BNL", 128, "2026-06-03T00:00:00-05:00"),
        ]
        self.assertEqual(shipments.latest_location(locs)["location"]["name"], "In Transit")

    def test_empty(self):
        self.assertIsNone(shipments.latest_location([]))


class ShippedReceivedTest(TestCase):
    def test_in_transit_has_shipped_but_no_received(self):
        locs = [_loc("BNL", 128, "2026-06-03T00:00:00-05:00"),
                _loc("In Transit", 0, "2026-06-05T00:00:00-05:00")]
        shipped, received = shipments.shipped_received(locs)
        self.assertEqual(shipped.date().isoformat(), "2026-06-05")
        self.assertIsNone(received)

    def test_delivered_has_shipped_and_received(self):
        locs = [_loc("FNAL", 1, "2026-05-01T00:00:00-05:00"),
                _loc("In Transit", 0, "2026-05-02T00:00:00-05:00"),
                _loc("CERN", 200, "2026-05-10T00:00:00-05:00")]
        shipped, received = shipments.shipped_received(locs)
        self.assertEqual(shipped.date().isoformat(), "2026-05-02")
        self.assertEqual(received.date().isoformat(), "2026-05-10")

    def test_reshipped_box_shows_latest_trip_not_first(self):
        # #73, D00599800007-00121: shipped once 2025-12-15 (checklist later
        # wiped), re-shipped 2026-07-23 and received at UMN — the card must
        # describe the current trip, not the first In-Transit ever.
        locs = [_loc("BNL", 128, "2025-12-01T00:00:00-05:00"),
                _loc("In Transit", 0, "2025-12-15T00:00:00-05:00"),
                _loc("In Transit", 0, "2026-07-23T14:36:00-04:00"),
                _loc("U. Minnesota", 186, "2026-07-23T14:42:00-04:00")]
        shipped, received = shipments.shipped_received(locs)
        self.assertEqual(shipped.date().isoformat(), "2026-07-23")
        self.assertEqual(received.date().isoformat(), "2026-07-23")

    def test_empty_timeline(self):
        self.assertEqual(shipments.shipped_received([]), (None, None))


class SyncShipmentsTest(TestCase):
    def _run(self, items, locs_by_pid, subs_by_pid=None, comp_by_pid=None):
        client = _fake_client(items, locs_by_pid, subs_by_pid, comp_by_pid)
        with mock.patch("explore.shipments.FnalDbApiClient", return_value=client):
            list(shipments.sync_shipments("http://api", "bearer", SHIP_PTID))
        return client

    def test_mirrors_latest_location_and_status(self):
        self._run(
            items=[{"part_id": "B1"}, {"part_id": "B2"}],
            locs_by_pid={
                "B1": [_loc("In Transit", 0, "2026-06-10T00:00:00-05:00"),
                       _loc("BNL", 128, "2026-06-03T00:00:00-05:00")],
                "B2": [_loc("FNAL", 1, "2026-05-21T00:00:00-05:00")],
            },
            subs_by_pid={"B1": [_sub()], "B2": [_sub()]},
        )
        b1 = ShipmentItem.objects.get(part_id="B1")
        self.assertEqual(b1.location_id, 0)
        self.assertTrue(b1.is_in_transit)
        self.assertIsNotNone(b1.last_arrived)
        b2 = ShipmentItem.objects.get(part_id="B2")
        self.assertEqual(b2.location_name, "FNAL")
        self.assertFalse(b2.is_in_transit)

    def test_mirrors_empty_boxes_with_zero_contents(self):
        self._run(
            items=[{"part_id": "B1"}, {"part_id": "B2"}],
            locs_by_pid={"B1": [_loc("FNAL", 1, "2026-05-21T00:00:00-05:00")],
                         "B2": [_loc("FNAL", 1, "2026-05-21T00:00:00-05:00")]},
            subs_by_pid={"B1": [_sub()]},  # B2 has no contents → mirrored as empty
        )
        self.assertEqual(ShipmentItem.objects.get(part_id="B1").n_contents, 1)
        b2 = ShipmentItem.objects.get(part_id="B2")
        self.assertEqual(b2.n_contents, 0)
        self.assertEqual(b2.location_name, "FNAL")  # location still mirrored
        # Empty boxes stay off the boxes-over-time chart.
        self.assertFalse(HwdbComponentEvent.objects.filter(part_id="B2").exists())

    def test_counts_contents(self):
        self._run(
            items=[{"part_id": "B1"}],
            locs_by_pid={"B1": [_loc("FNAL", 1, "2026-05-21T00:00:00-05:00")]},
            subs_by_pid={"B1": [_sub("Slot 1"), _sub("Slot 2"),
                                {"part_id": "X", "operation": "unmount"}]},  # unmount excluded
        )
        self.assertEqual(ShipmentItem.objects.get(part_id="B1").n_contents, 2)

    def test_sync_sets_marker_even_when_all_empty(self):
        _ship_leaf(synced=False)  # the leaf node, initially unsynced
        self._run(items=[{"part_id": "B1"}], locs_by_pid={}, subs_by_pid={})  # all empty
        leaf = H.objects.get(level=H.LEVEL_TYPE, part_type_id=SHIP_PTID)
        self.assertIsNotNone(leaf.shipments_synced_at)  # marked → page won't loop
        self.assertEqual(ShipmentItem.objects.get(part_type_id=SHIP_PTID,
                                                  part_id="B1").n_contents, 0)

    def test_box_with_no_locations_but_has_contents(self):
        self._run(items=[{"part_id": "B3"}], locs_by_pid={},
                  subs_by_pid={"B3": [_sub()]})
        b3 = ShipmentItem.objects.get(part_id="B3")
        self.assertEqual(b3.location_name, "")
        self.assertIsNone(b3.location_id)
        self.assertIsNone(b3.last_arrived)
        self.assertEqual(b3.n_contents, 1)

    def test_does_not_touch_component_events(self):
        # Boxes are regular components: the node (test) sync owns
        # HwdbComponentEvent; the shipments sync must not clobber it.
        HwdbComponentEvent.objects.create(part_type_id=SHIP_PTID, part_id="B1",
                                          status="Available")
        self._run(
            items=[{"part_id": "B1", "created": "2026-05-01T00:00:00-05:00"}],
            locs_by_pid={"B1": [_loc("FNAL", 1, "2026-05-21T00:00:00-05:00")]},
            subs_by_pid={"B1": [_sub()]},
        )
        ev = HwdbComponentEvent.objects.get(part_type_id=SHIP_PTID, part_id="B1")
        self.assertEqual(ev.status, "Available")  # untouched

    def test_stores_shipped_received(self):
        self._run(
            items=[{"part_id": "B1"}],
            locs_by_pid={"B1": [_loc("FNAL", 1, "2026-05-01T00:00:00-05:00"),
                                _loc("In Transit", 0, "2026-05-02T00:00:00-05:00")]},
            subs_by_pid={"B1": [_sub()]},
        )
        b1 = ShipmentItem.objects.get(part_id="B1")
        self.assertIsNotNone(b1.shipped_date)
        self.assertIsNone(b1.received_date)  # still in transit

    def test_shipped_dropped_when_specs_lack_shipping_checklist(self):
        # #73 (D00599800007-00121): the timeline still has the In-Transit
        # event, but the Shipping Checklist was wiped from the specs — no
        # SHIPPED date. Received (a real location fact) is untouched.
        self._run(
            items=[{"part_id": "B1"}],
            locs_by_pid={"B1": [_loc("FNAL", 1, "2025-12-01T00:00:00-05:00"),
                                _loc("In Transit", 0, "2025-12-15T00:00:00-05:00"),
                                _loc("CERN", 200, "2025-12-20T00:00:00-05:00")]},
            subs_by_pid={"B1": [_sub()]},
            comp_by_pid={"B1": {"Pre-Shipping Checklist": [{"Origin": "BNL"}]}},
        )
        b1 = ShipmentItem.objects.get(part_id="B1")
        self.assertIsNone(b1.shipped_date)
        self.assertEqual(b1.received_date.date().isoformat(), "2025-12-20")

    def test_contentless_checklist_counts_as_absent(self):
        # A bare [{}] renders as "Not recorded yet" on the box page — the
        # SHIPPED column must agree with it.
        self._run(
            items=[{"part_id": "B1"}],
            locs_by_pid={"B1": [_loc("In Transit", 0, "2025-12-15T00:00:00-05:00")]},
            subs_by_pid={"B1": [_sub()]},
            comp_by_pid={"B1": {"Shipping Checklist": [{}]}},
        )
        self.assertIsNone(ShipmentItem.objects.get(part_id="B1").shipped_date)

    def test_never_shipped_box_skips_the_spec_fetch(self):
        # The gate costs one item fetch — only for boxes that entered transit.
        client = self._run(
            items=[{"part_id": "B1"}, {"part_id": "B2"}],
            locs_by_pid={"B1": [_loc("FNAL", 1, "2026-05-21T00:00:00-05:00")],
                         "B2": [_loc("In Transit", 0, "2026-05-22T00:00:00-05:00")]},
            subs_by_pid={"B1": [_sub()], "B2": [_sub()]},
        )
        fetched = {c.args[0] for c in client.get_component.call_args_list}
        self.assertEqual(fetched, {"B2"})
        self.assertIsNotNone(ShipmentItem.objects.get(part_id="B2").shipped_date)

    def test_failed_spec_fetch_keeps_timeline_date(self):
        # Best-effort: a transient item-fetch error must not blank the date.
        client = _fake_client(
            items=[{"part_id": "B1"}],
            locs_by_pid={"B1": [_loc("In Transit", 0, "2025-12-15T00:00:00-05:00")]},
            subs_by_pid={"B1": [_sub()]})
        client.get_component.side_effect = RuntimeError("boom")
        with mock.patch("explore.shipments.FnalDbApiClient", return_value=client):
            list(shipments.sync_shipments("http://api", "bearer", SHIP_PTID))
        self.assertIsNotNone(ShipmentItem.objects.get(part_id="B1").shipped_date)

    def test_paginates_all_pages(self):
        client = mock.MagicMock()
        pages = {1: {"data": [{"part_id": "B1"}], "pagination": {"pages": 2}},
                 2: {"data": [{"part_id": "B2"}], "pagination": {"pages": 2}}}
        client._make_request.side_effect = (
            lambda method, endpoint, data=None, params=None: pages[params["page"]])
        client.get_locations.side_effect = lambda pid: {"data": []}
        client.get_subcomponents.side_effect = lambda pid: {"data": [_sub()]}
        with mock.patch("explore.shipments.FnalDbApiClient", return_value=client):
            list(shipments.sync_shipments("http://api", "b", SHIP_PTID))
        # Both pages' boxes mirrored — not just the first page.
        self.assertEqual(ShipmentItem.objects.filter(part_type_id=SHIP_PTID).count(), 2)

    def test_incremental_fetches_new_boxes_only(self):
        # Known box keeps its mirrored location untouched, vanished box is
        # pruned, and only the new box costs API calls.
        ShipmentItem.objects.create(part_type_id=SHIP_PTID, part_id="B1",
                                    location_name="OLD", location_id=5, n_contents=1)
        ShipmentItem.objects.create(part_type_id=SHIP_PTID, part_id="GONE",
                                    location_name="X", location_id=6, n_contents=1)
        client = _fake_client(
            items=[{"part_id": "B1"}, {"part_id": "B2"}],
            locs_by_pid={"B1": [_loc("NEW", 7, "2026-06-01T00:00:00-05:00")],
                         "B2": [_loc("FNAL", 1, "2026-06-01T00:00:00-05:00")]},
            subs_by_pid={"B2": [_sub()]})
        with mock.patch("explore.shipments.FnalDbApiClient", return_value=client):
            out = "".join(shipments.sync_shipments("http://api", "b", SHIP_PTID,
                                                   mode="incremental"))
        self.assertEqual(ShipmentItem.objects.get(part_id="B1").location_name, "OLD")
        self.assertEqual(ShipmentItem.objects.get(part_id="B2").location_name, "FNAL")
        self.assertFalse(ShipmentItem.objects.filter(part_id="GONE").exists())
        fetched = {c.args[0] for c in client.get_locations.call_args_list}
        self.assertEqual(fetched, {"B2"})   # the known box is never re-fetched
        self.assertIn("1 known kept", out)

    def test_wholesale_rewrite_no_duplicates(self):
        items = [{"part_id": "B1"}]
        locs = {"B1": [_loc("FNAL", 1, "2026-05-21T00:00:00-05:00")]}
        subs = {"B1": [_sub()]}
        self._run(items, locs, subs)
        self._run(items, locs, subs)  # second sync
        self.assertEqual(ShipmentItem.objects.filter(part_type_id=SHIP_PTID).count(), 1)


class RefreshBoxGateTest(TestCase):
    """The single-box re-mirror (#61) applies the same #73 gate."""

    def test_refresh_box_drops_shipped_without_checklist(self):
        api = mock.MagicMock()
        api.get_locations.return_value = {
            "data": [_loc("In Transit", 0, "2025-12-15T00:00:00-05:00")]}
        api.get_subcomponents.return_value = {"data": [_sub()]}
        api.get_component.return_value = {"data": {"specifications": [{"DATA": {}}]}}
        shipments.refresh_box(api, "prod", SHIP_PTID, "B1")
        self.assertIsNone(ShipmentItem.objects.get(part_id="B1").shipped_date)

    def test_refresh_box_keeps_shipped_with_checklist(self):
        api = mock.MagicMock()
        api.get_locations.return_value = {
            "data": [_loc("In Transit", 0, "2025-12-15T00:00:00-05:00")]}
        api.get_subcomponents.return_value = {"data": [_sub()]}
        api.get_component.return_value = {
            "data": {"specifications": [{"DATA": _SHIPPED_SPECS}]}}
        shipments.refresh_box(api, "prod", SHIP_PTID, "B1")
        self.assertIsNotNone(ShipmentItem.objects.get(part_id="B1").shipped_date)


class ShipmentPanelViewTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("ship", "s@s.io", "pw")
        self.client.force_login(self.user)

    def test_synced_shipping_leaf_renders_panel(self):
        leaf = _ship_leaf()
        ShipmentItem.objects.create(part_type_id=leaf.part_type_id, part_id="B1",
                                    location_name="In Transit", location_id=0, n_contents=3)
        ShipmentItem.objects.create(part_type_id=leaf.part_type_id, part_id="B2",
                                    location_name="FNAL", location_id=1, n_contents=5)
        html = self.client.get(navigation.leaf_path_for("prod", leaf.part_type_id)).content.decode()
        self.assertIn("Sync shipments", html)
        self.assertIn("B1", html)
        self.assertIn("In Transit", html)
        self.assertIn("FNAL", html)
        # Boxes are regular components too: the standard component view (sync
        # buttons + plots) renders ABOVE the shipping panes.
        self.assertIn("Full re-sync", html)
        self.assertIn("Components updated", html)
        self.assertIn("Tests recorded", html)
        self.assertIn(">Shipments</div>", html)   # the extras section header

    def test_empty_boxes_get_their_own_pane(self):
        leaf = _ship_leaf()
        ShipmentItem.objects.create(part_type_id=leaf.part_type_id, part_id="FULL",
                                    location_name="FNAL", location_id=1, n_contents=4)
        ShipmentItem.objects.create(part_type_id=leaf.part_type_id, part_id="EMPTYBOX",
                                    location_name="CERN", location_id=200, n_contents=0)
        html = self.client.get(navigation.leaf_path_for("prod", leaf.part_type_id)).content.decode()
        self.assertIn("FULL", html)
        self.assertIn("Boxes (1)", html)        # main table: non-empty only
        self.assertIn("Empty boxes (1)", html)  # separate pane
        self.assertIn("EMPTYBOX", html)
        # Summary cards count boxes with contents only.
        self.assertIn("Boxes with contents", html)

    @override_settings(HWDB_WRITE_INSTANCES=["dev"])
    def test_empty_boxes_pane_paginates(self):
        leaf = _ship_leaf()
        for i in range(51):
            ShipmentItem.objects.create(part_type_id=leaf.part_type_id,
                                        part_id=f"E{i:03d}", n_contents=0)
        url = navigation.leaf_path_for("prod", leaf.part_type_id)
        html = self.client.get(url).content.decode()
        self.assertIn("Empty boxes (51)", html)
        self.assertIn("Page 1 of 2", html)
        self.assertIn("E000", html)
        self.assertNotIn("E050", html)  # on page 2
        # ?bpage= pages the empty-box pane (?page= belongs to the components table)
        html2 = self.client.get(url, {"bpage": 2}).content.decode()
        self.assertIn("E050", html2)
        self.assertNotIn("E000", html2)
        # An htmx pager click gets just the pane back (in-place swap, no
        # full-page reload / scroll-to-top).
        frag = self.client.get(url, {"bpage": 2}, HTTP_HX_REQUEST="true",
                               HTTP_HX_TARGET="empty-boxes-pane").content.decode()
        self.assertIn('id="empty-boxes-pane"', frag)
        self.assertIn("E050", frag)
        self.assertNotIn("<html", frag)

    def test_unsynced_shipping_leaf_autosyncs_components_first(self):
        # Never-synced leaf: the component auto-sync fires; the shipments
        # auto-sync waits (two concurrent streams would race the reload).
        leaf = _ship_leaf(synced=False)
        html = self.client.get(navigation.leaf_path_for("prod", leaf.part_type_id)).content.decode()
        self.assertIn('id="node-unsynced"', html)
        self.assertNotIn('id="shipment-unsynced"', html)
        self.assertIn("Waiting for the item sync", html)
        # Once components are synced, the shipments auto-sync takes its turn.
        leaf.tests_synced_at = timezone.now()
        leaf.save()
        html = self.client.get(navigation.leaf_path_for("prod", leaf.part_type_id)).content.decode()
        self.assertNotIn('id="node-unsynced"', html)
        self.assertIn('id="shipment-unsynced"', html)

    def test_synced_but_empty_does_not_loop(self):
        # Synced (marker set) but no non-empty boxes → show a message, NOT the
        # auto-sync block (which would reload-loop forever). Regression for the
        # Electronics-box bug.
        leaf = _ship_leaf(synced=True)  # no ShipmentItems created
        html = self.client.get(navigation.leaf_path_for("prod", leaf.part_type_id)).content.decode()
        self.assertNotIn('id="shipment-unsynced"', html)
        self.assertIn("No boxes with contents here", html)

    def test_summary_cards_status_pills_contents_and_collapsible(self):
        leaf = _ship_leaf()
        ShipmentItem.objects.create(part_type_id=leaf.part_type_id, part_id="B1",
                                    location_name="In Transit", location_id=0, n_contents=7)
        ShipmentItem.objects.create(part_type_id=leaf.part_type_id, part_id="B2",
                                    location_name="CERN", location_id=200, n_contents=2)
        html = self.client.get(navigation.leaf_path_for("prod", leaf.part_type_id)).content.decode()
        self.assertIn("Boxes with contents", html)
        self.assertIn("ship-pill is-transit", html)
        self.assertIn("ship-pill is-delivered", html)
        self.assertIn("<th>Contents</th>", html)
        self.assertIn("details class=\"chart-card ship-boxes\"", html)  # collapsible

    def test_rows_link_to_box_detail_page(self):
        leaf = _ship_leaf()
        ShipmentItem.objects.create(part_type_id=leaf.part_type_id, part_id="B1",
                                    location_name="FNAL", location_id=1, n_contents=1)
        html = self.client.get(navigation.leaf_path_for("prod", leaf.part_type_id)).content.decode()
        self.assertIn('class="ship-row"', html)
        self.assertIn("/hw/part/B1/", html)  # row click → part detail page

    def test_box_pid_links_to_part_page(self):
        leaf = _ship_leaf()
        ShipmentItem.objects.create(part_type_id=leaf.part_type_id, part_id="B1",
                                    location_name="FNAL", location_id=1, n_contents=1)
        html = self.client.get(navigation.leaf_path_for("prod", leaf.part_type_id)).content.decode()
        self.assertIn("/hw/part/B1/", html)              # box PID → local part page
        self.assertNotIn("/edit/component/B1", html)          # not the FNAL deep link
        self.assertIn("event.stopPropagation()", html)        # link doesn't trigger the row


def _component(data_sections):
    """A full item record whose spec DATA carries the given checklist sections."""
    return {"data": {"specifications": [{"DATA": data_sections}]}}


def _sec(details, title):
    """The detail section with the given display title."""
    return next(s for s in details if s["title"] == title)


class ShipmentDetailsTest(TestCase):
    def test_folds_single_field_entries_into_one_section(self):
        # The blob stores each field as its own list entry — must NOT repeat
        # the section title per field.
        blob = {"Pre-Shipping Checklist": [
            {"Origin of this shipment": "BNL"},
            {"Destination of this shipment": "FNAL"},
            {"Weight of this shipment": ""},                 # blank → skipped
            {"Image ID for this Shipping Sheet": "img-9"},
        ]}
        secs = shipments.shipment_details(blob)
        sec = secs[0]  # Pre-shipping is first
        self.assertEqual(sec["title"], "Pre-shipping")
        labels = {f["label"]: f["value"] for f in sec["fields"]}
        self.assertEqual(labels, {"Origin of this shipment": "BNL",
                                  "Destination of this shipment": "FNAL"})
        self.assertEqual(sec["attachments"], [{"label": "Shipping Sheet", "image_id": "img-9"}])

    def test_always_returns_all_three_sections_in_lifecycle_order(self):
        # Even with only Warehouse populated, all three render (empty stages
        # show just their title), in fixed lifecycle order.
        blob = {"Warehouse": [{"SKU": "SKU-1"}], "Shipping Checklist": [{}]}
        secs = shipments.shipment_details(blob)
        self.assertEqual([s["title"] for s in secs],
                         ["Pre-shipping", "Shipping", "Info @ Warehouse"])
        self.assertEqual(secs[0]["fields"], [])               # Pre-shipping empty
        self.assertEqual(secs[1]["fields"], [])               # Shipping empty
        self.assertEqual(secs[2]["fields"], [{"label": "SKU", "value": "SKU-1"}])

    def test_none_blob_returns_three_empty_sections(self):
        secs = shipments.shipment_details(None)
        self.assertEqual(len(secs), 3)
        self.assertTrue(all(not s["fields"] and not s["attachments"] for s in secs))


class PartDetailEngineTest(TestCase):
    """parts.part_detail — the generic engine (box page is is_shipping=True)."""

    def _api(self, component=None, images=None, tests=None):
        api = mock.MagicMock()
        api.get_locations.return_value = {"data": [
            _loc("BNL", 128, "2026-06-03T00:00:00-05:00"),
            _loc("In Transit", 0, "2026-06-10T00:00:00-05:00"),  # newest
        ]}
        api.get_subcomponents.return_value = {"data": [
            {"part_id": "P1", "type_name": "FEMB", "functional_position": "Slot 1",
             "operation": "mount"},
            {"part_id": "P2", "type_name": "FEMB", "functional_position": "Slot 2",
             "operation": "unmount"},  # excluded
        ]}
        api.get_component.return_value = component or {"data": {"specifications": []}}
        api.get_images.return_value = {"data": images or []}
        api.get_tests.return_value = {"data": tests or []}
        return api

    def test_timeline_sorted_desc_and_manifest_filters_unmount(self):
        d = parts.part_detail(self._api(), "B1", is_shipping=False)
        self.assertEqual(d["timeline"][0]["location"], "In Transit")
        self.assertEqual(d["timeline"][0]["location_id"], 0)
        self.assertEqual([m["part_id"] for m in d["manifest"]], ["P1"])
        self.assertTrue(d["has_location"])

    def test_shipping_box_uses_lifecycle_sections_and_attachments(self):
        api = self._api(
            component=_component({"Warehouse": [{"SKU": "SKU-1", "PalletID": "PAL-7"}]}),
            images=[{"image_id": "img-1", "image_name": "label.pdf"},
                    {"image_id": None, "image_name": "broken"}],  # dropped (no id)
        )
        d = parts.part_detail(api, "B1", is_shipping=True)
        self.assertEqual(_sec(d["sections"], "Info @ Warehouse")["fields"][0]["label"], "SKU")
        self.assertEqual([a["image_id"] for a in d["attachments"]], ["img-1"])

    def test_flags_image_attachments_for_thumbnailing(self):
        api = self._api(
            component=_component({"Shipping Checklist": [
                {"Image ID for the visual inspection photo": "img-jpg"},
                {"Image ID for BoL": "img-pdf"}]}),
            images=[{"image_id": "img-jpg", "image_name": "inspect.JPG"},
                    {"image_id": "img-pdf", "image_name": "bol.pdf"}],
        )
        secs = parts.part_detail(api, "B1", is_shipping=True)["sections"]
        atts = {a["image_id"]: a for a in _sec(secs, "Shipping")["attachments"]}
        self.assertTrue(atts["img-jpg"]["is_image"])    # .JPG (case-insensitive)
        self.assertFalse(atts["img-pdf"]["is_image"])   # .pdf → download chip

    def test_attachment_filename_resolved_from_image_list(self):
        # The spec gives only the image id; the real filename (with extension)
        # comes from the /images listing and must drive the download name.
        api = self._api(
            component=_component(
                {"Shipping Checklist": [{"Image ID for this Shipping Sheet": "img-1"}]}),
            images=[{"image_id": "img-1", "image_name": "D08120200001-00002-shipping-label.pdf"}],
        )
        att = _sec(parts.part_detail(api, "B1", is_shipping=True)["sections"], "Shipping")["attachments"][0]
        self.assertEqual(att["label"], "Shipping Sheet")
        self.assertEqual(att["filename"], "D08120200001-00002-shipping-label.pdf")


class ShipmentDetailPageTest(TestCase):
    """The per-box detail page (one click from either table; renders live)."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("box", "b@b.io", "pw")
        self.client.force_login(self.user)
        self.leaf = _ship_leaf()
        self.part_id = SHIP_PTID + "-00002"
        ShipmentItem.objects.create(part_type_id=SHIP_PTID, part_id=self.part_id,
                                    location_name="In Transit", location_id=0, n_contents=1)
        self.url = "/hw/part/" + self.part_id + "/"

    def _api(self):
        api = mock.MagicMock()
        api.get_locations.return_value = {"data": [_loc("In Transit", 0, "2026-06-10T00:00:00-05:00")]}
        api.get_subcomponents.return_value = {"data": [_sub()]}
        api.get_component.return_value = {"data": {"specifications": [
            {"DATA": {"Shipping Checklist": [{"Image ID for this Shipping Sheet": "img-1"}]}}]}}
        api.get_images.return_value = {"data": [{"image_id": "img-1", "image_name": "label.pdf"}]}
        api.get_tests.return_value = {"data": []}
        return api

    def test_renders_detail_with_checklist_and_download(self):
        with mock.patch("explore.views.mint_for", return_value="bearer"), \
             mock.patch("explore.views.FnalDbApiClient", return_value=self._api()):
            resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn(self.part_id, body)
        # All three lifecycle sections render, even the empty ones.
        self.assertIn("Pre-shipping", body)
        self.assertIn("Info @ Warehouse", body)
        self.assertIn("Not recorded yet.", body)           # empty stage placeholder
        self.assertIn("Shipping Sheet", body)              # download chip label
        self.assertIn("label.pdf", body)                   # real filename in ?name=
        self.assertIn(navigation.leaf_path_for("prod", SHIP_PTID), body)  # breadcrumb back to leaf

    def test_fnal_link_required_redirects(self):
        with mock.patch("explore.views.mint_for", side_effect=FnalLinkRequired()):
            resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("hwdb:link"), resp["Location"])

    def test_fnal_unavailable_shows_banner(self):
        with mock.patch("explore.views.mint_for", side_effect=FnalUnavailable()):
            resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Couldn", resp.content.decode())  # "Couldn't load …" banner


class ShipmentImageViewTest(TestCase):
    """Attachment/label download proxy (bearer-gated bytes streamed through)."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("img", "i@i.io", "pw")
        self.client.force_login(self.user)
        self.url = "/hw/shipment-image/img-7/"

    def _api(self):
        api = mock.MagicMock()
        upstream = mock.MagicMock()
        upstream.headers = {"Content-Type": "application/pdf"}
        upstream.iter_content.return_value = iter([b"%PDF-", b"bytes"])
        api.get_image_response.return_value = upstream
        return api

    def test_streams_bytes_with_sanitised_filename(self):
        with mock.patch("explore.views.mint_for", return_value="bearer"), \
             mock.patch("explore.views.FnalDbApiClient", return_value=self._api()):
            resp = self.client.get(self.url, {"name": 'la/be"l.pdf'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertEqual(resp["Content-Disposition"], 'attachment; filename="label.pdf"')
        self.assertEqual(b"".join(resp.streaming_content), b"%PDF-bytes")

    def test_inline_disposition_for_thumbnail_view(self):
        with mock.patch("explore.views.mint_for", return_value="bearer"), \
             mock.patch("explore.views.FnalDbApiClient", return_value=self._api()):
            resp = self.client.get(self.url, {"name": "photo.jpg", "inline": "1"})
        self.assertEqual(resp["Content-Disposition"], 'inline; filename="photo.jpg"')

    def test_fnal_link_required_returns_409(self):
        with mock.patch("explore.views.mint_for", side_effect=FnalLinkRequired()):
            resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["error"], "fnal_link")


class ShipmentsPageTest(TestCase):
    """Top-level Shipments dashboard (Hajime's ask)."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("sp", "s@p.io", "pw")
        self.client.force_login(self.user)
        self.leaf = _ship_leaf()
        ShipmentItem.objects.create(part_type_id=self.leaf.part_type_id, part_id="B1",
                                    location_name="In Transit", location_id=0, n_contents=3)
        ShipmentItem.objects.create(part_type_id=self.leaf.part_type_id, part_id="B2",
                                    location_name="CERN", location_id=200, n_contents=5)

    def test_requires_login(self):
        self.client.logout()
        resp = self.client.get(reverse("explore:shipments"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("explore:login"), resp["Location"])

    def test_lists_boxes_with_summary_and_leaf_links(self):
        html = self.client.get(reverse("explore:shipments")).content.decode()
        self.assertIn("B1", html)
        self.assertIn("B2", html)
        # each box links into the existing leaf node view
        self.assertIn(navigation.leaf_path_for("prod", self.leaf.part_type_id), html)
        self.assertIn("ship-pill is-transit", html)
        self.assertIn("ship-pill is-delivered", html)

    def test_htmx_pager_click_returns_just_the_pane(self):
        # 51 boxes with contents → 2 pages; an hx-get from the pager swaps the
        # boxes pane in place (fragment only, no full page / scroll-to-top).
        for i in range(49):
            ShipmentItem.objects.create(part_type_id=self.leaf.part_type_id,
                                        part_id=f"C{i:03d}", location_id=200,
                                        n_contents=1)
        frag = self.client.get(reverse("explore:shipments"), {"page": 2},
                               HTTP_HX_REQUEST="true",
                               HTTP_HX_TARGET="shipments-pane").content.decode()
        self.assertTrue(frag.strip().startswith('<div id="shipments-pane"'))
        self.assertIn("Page 2 of 2", frag)
        self.assertNotIn("<html", frag)                # not the full page
        self.assertIn('hx-get="?page=1"', frag)
        self.assertIn('hx-target="#shipments-pane"', frag)

    def test_nav_has_shipments_tab_active(self):
        html = self.client.get(reverse("explore:shipments")).content.decode()
        self.assertIn("eh-nav-item active", html)
        self.assertIn(">Shipments<", html)

    def test_skips_empty_boxes(self):
        ShipmentItem.objects.create(part_type_id=self.leaf.part_type_id, part_id="EMPTYBOX",
                                    location_name="FNAL", location_id=1, n_contents=0)
        html = self.client.get(reverse("explore:shipments")).content.decode()
        self.assertNotIn("EMPTYBOX", html)

    def test_types_grouped_by_subsystem_with_ids_and_idle_rows(self):
        # A second type in the same subsystem with no boxes gets a dimmed row
        # in the group's compact table, not a card of its own.
        H.objects.create(
            level=H.LEVEL_TYPE, parent=self.leaf.parent, system_id=81,
            system_name="FD CE", subsystem_id=202, subsystem_name="CE Shipping Box",
            name="Spare box", part_type_id="D08120200002", n_components=0)
        html = self.client.get(reverse("explore:shipments")).content.decode()
        self.assertEqual(html.count('<details class="tsg"'), 1)  # one subsystem group
        self.assertIn("(81.202)", html)                    # system.subsystem id in the header
        self.assertIn("2 boxes", html)                     # group header: B1 + B2
        self.assertIn("D08120200001", html)                # type ids in the rows
        self.assertIn("D08120200002", html)
        self.assertIn('class="tsg-row-idle"', html)        # 0-box row dimmed
        self.assertIn("never — open to sync", html)

    def test_sync_all_button_with_targets(self):
        html = self.client.get(reverse("explore:shipments")).content.decode()
        self.assertIn('id="shipall-btn"', html)            # Sync new (incremental)
        self.assertIn('data-mode="incremental"', html)
        self.assertIn('id="shipall-full-btn"', html)       # Re-sync all (full)
        self.assertIn('id="tsg-toggle"', html)             # expand/collapse all
        self.assertIn('id="shipall-data"', html)
        # the target list carries each type's streaming sync endpoint
        self.assertIn(f'"/hw/sync-shipments/{self.leaf.part_type_id}/"', html)

    def test_sync_view_forwards_mode(self):
        with mock.patch("explore.views.sync_shipments") as m, \
             mock.patch("explore.views.mint_for", return_value="b"):
            m.return_value = iter(["ok\n"])
            resp = self.client.post(f"/hw/sync-shipments/{self.leaf.part_type_id}/",
                                    {"mode": "incremental"})
            list(resp.streaming_content)
        self.assertEqual(m.call_args.kwargs["mode"], "incremental")
        # bogus / absent mode falls back to full
        with mock.patch("explore.views.sync_shipments") as m, \
             mock.patch("explore.views.mint_for", return_value="b"):
            m.return_value = iter(["ok\n"])
            resp = self.client.post(f"/hw/sync-shipments/{self.leaf.part_type_id}/",
                                    {"mode": "bogus"})
            list(resp.streaming_content)
        self.assertEqual(m.call_args.kwargs["mode"], "full")

    def test_paginated_50_per_page(self):
        # setUp already made 2 non-empty boxes; add 53 → 55 total across 2 pages.
        ShipmentItem.objects.bulk_create([
            ShipmentItem(part_type_id=self.leaf.part_type_id, part_id=f"X{i}",
                         location_name="FNAL", location_id=1, n_contents=1)
            for i in range(53)
        ])
        pg = self.client.get(reverse("explore:shipments")).context["page_obj"]
        self.assertEqual(pg.paginator.count, 55)
        self.assertEqual(pg.paginator.num_pages, 2)
        self.assertEqual(len(pg.object_list), 50)
        pg2 = self.client.get(reverse("explore:shipments") + "?page=2").context["page_obj"]
        self.assertEqual(len(pg2.object_list), 5)
        # summary still counts all boxes, not just the page
        self.assertEqual(pg.paginator.count, 55)
