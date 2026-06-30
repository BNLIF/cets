"""Tests for the Shipment Tracker core slice (issue #43, ADR-0013).

Covers the curation lookup, the latest-location sync engine, and the
shipping-leaf rendering. HWDB fetch is mocked — no network.

    python manage.py test explore
"""

from __future__ import annotations

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from explore import curation, navigation, shipments
from explore.models import HierarchyNode as H
from explore.models import ShipmentItem
from hwdb.fnal.bearer import FnalLinkRequired, FnalUnavailable

SHIP_PTID = "D08120200001"  # curated CE Shipping box (FD CE › CE Shipping Box)


def _ship_leaf(ptid=SHIP_PTID):
    """Build the FD CE › CE Shipping Box chain + the shipping-box leaf."""
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
        full_name="D.FD CE.CE Shipping Box.CE Shipping box")


def _loc(name, lid, arrived):
    return {"arrived": arrived, "location": {"id": lid, "name": name},
            "creator": "x", "comments": ""}


def _fake_client(items, locs_by_pid):
    client = mock.MagicMock()
    # sync lists items via _make_request (paginated); return a single page.
    client._make_request.side_effect = lambda method, endpoint, data=None, params=None: {
        "data": items, "pagination": {"pages": 1}}
    client.get_locations.side_effect = lambda pid: {"data": locs_by_pid.get(pid, [])}
    return client


class CurationTest(TestCase):
    def test_anchor_is_shipping_type(self):
        self.assertIn(SHIP_PTID, curation.shipping_types())
        self.assertTrue(curation.is_shipping_type(SHIP_PTID))

    def test_other_type_is_not_shipping(self):
        self.assertFalse(curation.is_shipping_type("D05700200001"))


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

    def test_empty_timeline(self):
        self.assertEqual(shipments.shipped_received([]), (None, None))


class SyncShipmentsTest(TestCase):
    def _run(self, items, locs_by_pid):
        client = _fake_client(items, locs_by_pid)
        with mock.patch("explore.shipments.FnalDbApiClient", return_value=client):
            list(shipments.sync_shipments("http://api", "bearer", SHIP_PTID))

    def test_mirrors_latest_location_and_status(self):
        self._run(
            items=[{"part_id": "B1"}, {"part_id": "B2"}],
            locs_by_pid={
                "B1": [_loc("In Transit", 0, "2026-06-10T00:00:00-05:00"),
                       _loc("BNL", 128, "2026-06-03T00:00:00-05:00")],
                "B2": [_loc("FNAL", 1, "2026-05-21T00:00:00-05:00")],
            },
        )
        b1 = ShipmentItem.objects.get(part_id="B1")
        self.assertEqual(b1.location_id, 0)
        self.assertTrue(b1.is_in_transit)
        self.assertIsNotNone(b1.last_arrived)
        b2 = ShipmentItem.objects.get(part_id="B2")
        self.assertEqual(b2.location_name, "FNAL")
        self.assertFalse(b2.is_in_transit)

    def test_box_with_no_locations(self):
        self._run(items=[{"part_id": "B3"}], locs_by_pid={})
        b3 = ShipmentItem.objects.get(part_id="B3")
        self.assertEqual(b3.location_name, "")
        self.assertIsNone(b3.location_id)
        self.assertIsNone(b3.last_arrived)

    def test_stores_shipped_received(self):
        self._run(
            items=[{"part_id": "B1"}],
            locs_by_pid={"B1": [_loc("FNAL", 1, "2026-05-01T00:00:00-05:00"),
                                _loc("In Transit", 0, "2026-05-02T00:00:00-05:00")]},
        )
        b1 = ShipmentItem.objects.get(part_id="B1")
        self.assertIsNotNone(b1.shipped_date)
        self.assertIsNone(b1.received_date)  # still in transit

    def test_paginates_all_pages(self):
        client = mock.MagicMock()
        pages = {1: {"data": [{"part_id": "B1"}], "pagination": {"pages": 2}},
                 2: {"data": [{"part_id": "B2"}], "pagination": {"pages": 2}}}
        client._make_request.side_effect = (
            lambda method, endpoint, data=None, params=None: pages[params["page"]])
        client.get_locations.side_effect = lambda pid: {"data": []}
        with mock.patch("explore.shipments.FnalDbApiClient", return_value=client):
            list(shipments.sync_shipments("http://api", "b", SHIP_PTID))
        # Both pages' boxes mirrored — not just the first page.
        self.assertEqual(ShipmentItem.objects.filter(part_type_id=SHIP_PTID).count(), 2)

    def test_wholesale_rewrite_no_duplicates(self):
        items = [{"part_id": "B1"}]
        locs = {"B1": [_loc("FNAL", 1, "2026-05-21T00:00:00-05:00")]}
        self._run(items, locs)
        self._run(items, locs)  # second sync
        self.assertEqual(ShipmentItem.objects.filter(part_type_id=SHIP_PTID).count(), 1)


class ShipmentPanelViewTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("ship", "s@s.io", "pw")
        self.client.force_login(self.user)

    def test_synced_shipping_leaf_renders_panel(self):
        leaf = _ship_leaf()
        ShipmentItem.objects.create(part_type_id=leaf.part_type_id, part_id="B1",
                                    location_name="In Transit", location_id=0)
        ShipmentItem.objects.create(part_type_id=leaf.part_type_id, part_id="B2",
                                    location_name="FNAL", location_id=1)
        html = self.client.get(navigation.leaf_path_for(leaf.part_type_id)).content.decode()
        self.assertIn("Sync shipments", html)
        self.assertIn("B1", html)
        self.assertIn("In Transit", html)
        self.assertIn("FNAL", html)
        # Shipping leaf shows no test-plot machinery (the chart config script
        # element and the chart canvases are absent; the static JS still
        # references the id, so match the rendered element specifically).
        self.assertNotIn('id="node-chart-config"', html)
        self.assertNotIn(f"bar_{leaf.part_type_id}", html)
        self.assertNotIn("Test events", html)

    def test_unsynced_shipping_leaf_shows_autosync_block(self):
        leaf = _ship_leaf()
        html = self.client.get(navigation.leaf_path_for(leaf.part_type_id)).content.decode()
        self.assertIn('id="shipment-unsynced"', html)

    def test_summary_cards_and_status_pills(self):
        leaf = _ship_leaf()
        ShipmentItem.objects.create(part_type_id=leaf.part_type_id, part_id="B1",
                                    location_name="In Transit", location_id=0)
        ShipmentItem.objects.create(part_type_id=leaf.part_type_id, part_id="B2",
                                    location_name="CERN", location_id=200)
        html = self.client.get(navigation.leaf_path_for(leaf.part_type_id)).content.decode()
        self.assertIn("Total boxes", html)
        self.assertIn("In transit", html)
        self.assertIn("Delivered", html)
        self.assertIn("ship-pill is-transit", html)
        self.assertIn("ship-pill is-delivered", html)

    def test_rows_are_expandable_with_detail_url(self):
        leaf = _ship_leaf()
        ShipmentItem.objects.create(part_type_id=leaf.part_type_id, part_id="B1",
                                    location_name="FNAL", location_id=1)
        html = self.client.get(navigation.leaf_path_for(leaf.part_type_id)).content.decode()
        self.assertIn('class="ship-row"', html)
        self.assertIn("/explore/shipment-box/B1/", html)


class BoxDetailTest(TestCase):
    def test_timeline_sorted_desc_and_manifest_filters_unmount(self):
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
        d = shipments.box_detail(api, "B1")
        self.assertEqual(d["timeline"][0]["location"], "In Transit")
        self.assertEqual(d["timeline"][0]["location_id"], 0)
        self.assertEqual([m["part_id"] for m in d["manifest"]], ["P1"])


class ShipmentBoxViewTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("box", "b@b.io", "pw")
        self.client.force_login(self.user)
        self.url = "/explore/shipment-box/B1/"

    def _api(self):
        api = mock.MagicMock()
        api.get_locations.return_value = {"data": [_loc("FNAL", 1, "2026-05-21T00:00:00-05:00")]}
        api.get_subcomponents.return_value = {"data": []}
        return api

    def test_returns_json_detail(self):
        with mock.patch("explore.views.mint_for", return_value="bearer"), \
             mock.patch("explore.views.FnalDbApiClient", return_value=self._api()):
            resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["part_id"], "B1")
        self.assertEqual(data["timeline"][0]["location"], "FNAL")
        self.assertEqual(data["manifest"], [])

    def test_fnal_link_required_returns_409_with_link(self):
        with mock.patch("explore.views.mint_for", side_effect=FnalLinkRequired()):
            resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["error"], "fnal_link")
        self.assertIn("link", resp.json())

    def test_fnal_unavailable_returns_502(self):
        with mock.patch("explore.views.mint_for", side_effect=FnalUnavailable()):
            resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 502)
        self.assertEqual(resp.json()["error"], "unavailable")
