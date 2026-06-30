"""Tests for the Shipment Tracker core slice (issue #43, ADR-0013).

Covers the curation lookup, the latest-location sync engine, and the
shipping-leaf rendering. HWDB fetch is mocked — no network.

    python manage.py test explore
"""

from __future__ import annotations

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from explore import curation, navigation, parts, shipments
from explore.models import HierarchyNode as H
from explore.models import HwdbComponentEvent, ShipmentItem
from hwdb.fnal.bearer import FnalLinkRequired, FnalUnavailable

SHIP_PTID = "D08120200001"  # curated CE Shipping box (FD CE › CE Shipping Box)


def _ship_leaf(ptid=SHIP_PTID, synced=True):
    """Build the FD CE › CE Shipping Box chain + the shipping-box leaf.

    ``synced`` stamps shipments_synced_at (the sync marker) so the panel renders;
    pass synced=False to test the never-synced (auto-sync) state.
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
        shipments_synced_at=timezone.now() if synced else None)


def _loc(name, lid, arrived):
    return {"arrived": arrived, "location": {"id": lid, "name": name},
            "creator": "x", "comments": ""}


def _sub(pos="Slot 1"):
    return {"part_id": "P-" + pos, "type_name": "FEMB",
            "functional_position": pos, "operation": "mount"}


def _fake_client(items, locs_by_pid, subs_by_pid=None):
    subs_by_pid = subs_by_pid or {}
    client = mock.MagicMock()
    # sync lists items via _make_request (paginated); return a single page.
    client._make_request.side_effect = lambda method, endpoint, data=None, params=None: {
        "data": items, "pagination": {"pages": 1}}
    client.get_locations.side_effect = lambda pid: {"data": locs_by_pid.get(pid, [])}
    client.get_subcomponents.side_effect = lambda pid: {"data": subs_by_pid.get(pid, [])}
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
    def _run(self, items, locs_by_pid, subs_by_pid=None):
        client = _fake_client(items, locs_by_pid, subs_by_pid)
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
            subs_by_pid={"B1": [_sub()], "B2": [_sub()]},
        )
        b1 = ShipmentItem.objects.get(part_id="B1")
        self.assertEqual(b1.location_id, 0)
        self.assertTrue(b1.is_in_transit)
        self.assertIsNotNone(b1.last_arrived)
        b2 = ShipmentItem.objects.get(part_id="B2")
        self.assertEqual(b2.location_name, "FNAL")
        self.assertFalse(b2.is_in_transit)

    def test_skips_empty_boxes(self):
        self._run(
            items=[{"part_id": "B1"}, {"part_id": "B2"}],
            locs_by_pid={"B1": [_loc("FNAL", 1, "2026-05-21T00:00:00-05:00")],
                         "B2": [_loc("FNAL", 1, "2026-05-21T00:00:00-05:00")]},
            subs_by_pid={"B1": [_sub()]},  # B2 has no contents → skipped
        )
        self.assertTrue(ShipmentItem.objects.filter(part_id="B1").exists())
        self.assertFalse(ShipmentItem.objects.filter(part_id="B2").exists())

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
        self.assertEqual(ShipmentItem.objects.filter(part_type_id=SHIP_PTID).count(), 0)

    def test_box_with_no_locations_but_has_contents(self):
        self._run(items=[{"part_id": "B3"}], locs_by_pid={},
                  subs_by_pid={"B3": [_sub()]})
        b3 = ShipmentItem.objects.get(part_id="B3")
        self.assertEqual(b3.location_name, "")
        self.assertIsNone(b3.location_id)
        self.assertIsNone(b3.last_arrived)
        self.assertEqual(b3.n_contents, 1)

    def test_populates_component_events_for_chart(self):
        self._run(
            items=[{"part_id": "B1", "created": "2026-05-01T00:00:00-05:00"}],
            locs_by_pid={"B1": [_loc("FNAL", 1, "2026-05-21T00:00:00-05:00")]},
            subs_by_pid={"B1": [_sub()]},
        )
        ev = HwdbComponentEvent.objects.get(part_type_id=SHIP_PTID, part_id="B1")
        self.assertIsNotNone(ev.created)  # → boxes-over-time chart

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

    def test_wholesale_rewrite_no_duplicates(self):
        items = [{"part_id": "B1"}]
        locs = {"B1": [_loc("FNAL", 1, "2026-05-21T00:00:00-05:00")]}
        subs = {"B1": [_sub()]}
        self._run(items, locs, subs)
        self._run(items, locs, subs)  # second sync
        self.assertEqual(ShipmentItem.objects.filter(part_type_id=SHIP_PTID).count(), 1)


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
        html = self.client.get(navigation.leaf_path_for(leaf.part_type_id)).content.decode()
        self.assertIn("Sync shipments", html)
        self.assertIn("B1", html)
        self.assertIn("In Transit", html)
        self.assertIn("FNAL", html)
        # Boxes-over-time chart present; test-plot machinery absent.
        self.assertIn("Boxes over time", html)
        self.assertNotIn("Test events", html)
        self.assertNotIn("Tests performed", html)

    def test_skips_empty_boxes_in_view(self):
        leaf = _ship_leaf()
        ShipmentItem.objects.create(part_type_id=leaf.part_type_id, part_id="FULL",
                                    location_name="FNAL", location_id=1, n_contents=4)
        ShipmentItem.objects.create(part_type_id=leaf.part_type_id, part_id="EMPTY",
                                    location_name="FNAL", location_id=1, n_contents=0)
        html = self.client.get(navigation.leaf_path_for(leaf.part_type_id)).content.decode()
        self.assertIn("FULL", html)
        self.assertNotIn("EMPTY", html)
        self.assertIn("Boxes (1)", html)  # only the non-empty box counted

    def test_unsynced_shipping_leaf_shows_autosync_block(self):
        leaf = _ship_leaf(synced=False)
        html = self.client.get(navigation.leaf_path_for(leaf.part_type_id)).content.decode()
        self.assertIn('id="shipment-unsynced"', html)

    def test_synced_but_empty_does_not_loop(self):
        # Synced (marker set) but no non-empty boxes → show a message, NOT the
        # auto-sync block (which would reload-loop forever). Regression for the
        # Electronics-box bug.
        leaf = _ship_leaf(synced=True)  # no ShipmentItems created
        html = self.client.get(navigation.leaf_path_for(leaf.part_type_id)).content.decode()
        self.assertNotIn('id="shipment-unsynced"', html)
        self.assertIn("No boxes with contents here", html)

    def test_summary_cards_status_pills_contents_and_collapsible(self):
        leaf = _ship_leaf()
        ShipmentItem.objects.create(part_type_id=leaf.part_type_id, part_id="B1",
                                    location_name="In Transit", location_id=0, n_contents=7)
        ShipmentItem.objects.create(part_type_id=leaf.part_type_id, part_id="B2",
                                    location_name="CERN", location_id=200, n_contents=2)
        html = self.client.get(navigation.leaf_path_for(leaf.part_type_id)).content.decode()
        self.assertIn("Boxes with contents", html)
        self.assertIn("ship-pill is-transit", html)
        self.assertIn("ship-pill is-delivered", html)
        self.assertIn("<th>Contents</th>", html)
        self.assertIn("details class=\"chart-card ship-boxes\"", html)  # collapsible

    def test_rows_link_to_box_detail_page(self):
        leaf = _ship_leaf()
        ShipmentItem.objects.create(part_type_id=leaf.part_type_id, part_id="B1",
                                    location_name="FNAL", location_id=1, n_contents=1)
        html = self.client.get(navigation.leaf_path_for(leaf.part_type_id)).content.decode()
        self.assertIn('class="ship-row"', html)
        self.assertIn("/explore/part/B1/", html)  # row click → part detail page

    def test_box_pid_links_to_hwdb(self):
        leaf = _ship_leaf()
        ShipmentItem.objects.create(part_type_id=leaf.part_type_id, part_id="B1",
                                    location_name="FNAL", location_id=1, n_contents=1)
        html = self.client.get(navigation.leaf_path_for(leaf.part_type_id)).content.decode()
        self.assertIn("/edit/component/B1", html)             # box PID → HWDB item
        self.assertIn("event.stopPropagation()", html)        # link doesn't toggle the row


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
        self.url = "/explore/part/" + self.part_id + "/"

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
        self.assertIn(navigation.leaf_path_for(SHIP_PTID), body)  # breadcrumb back to leaf

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
        self.url = "/explore/shipment-image/img-7/"

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
        self.assertIn(navigation.leaf_path_for(self.leaf.part_type_id), html)
        self.assertIn("ship-pill is-transit", html)
        self.assertIn("ship-pill is-delivered", html)

    def test_nav_has_shipments_tab_active(self):
        html = self.client.get(reverse("explore:shipments")).content.decode()
        self.assertIn("eh-nav-item active", html)
        self.assertIn(">Shipments<", html)

    def test_skips_empty_boxes(self):
        ShipmentItem.objects.create(part_type_id=self.leaf.part_type_id, part_id="EMPTYBOX",
                                    location_name="FNAL", location_id=1, n_contents=0)
        html = self.client.get(reverse("explore:shipments")).content.decode()
        self.assertNotIn("EMPTYBOX", html)

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
