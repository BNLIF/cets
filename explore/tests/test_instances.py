"""URL-carried HWDB instance support (#47): /hw/dev/ routing, per-instance
curation, mirror scoping, and the dev-page affordances (banner + switch).

    python manage.py test explore.tests.test_instances
"""

from __future__ import annotations

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from explore import curation, navigation, shipments
from explore.models import HierarchySyncState, HierarchyNode as H, ShipmentItem

DEV_PTID = "D00599800007"  # Hajime's shipping-test type on dev (system 5)


def _node(instance, ptid, sid, sname, ssid, ssname, tname, **leaf):
    sys, _ = H.objects.get_or_create(
        instance=instance, level=H.LEVEL_SYSTEM, system_id=sid, subsystem_id=None,
        part_type_id="", defaults={"system_name": sname, "name": sname})
    sub, _ = H.objects.get_or_create(
        instance=instance, level=H.LEVEL_SUBSYSTEM, system_id=sid, subsystem_id=ssid,
        part_type_id="", defaults={"parent": sys, "system_name": sname,
                                   "subsystem_name": ssname, "name": ssname})
    return H.objects.create(
        instance=instance, level=H.LEVEL_TYPE, parent=sub, system_id=sid,
        system_name=sname, subsystem_id=ssid, subsystem_name=ssname,
        name=tname, part_type_id=ptid, **leaf)


class CurationInstanceTest(TestCase):
    def test_per_instance_blocks(self):
        # Both instances curate prod-style FD families, but membership follows
        # each instance's own audit: dev's FD-HD has system 2 (no 9), prod's
        # has 9 (no 2). System 5 (HWDBUnitTest sandbox home) is dev FD-HD.
        prod, dev = curation.curated_system_ids("prod"), curation.curated_system_ids("dev")
        self.assertIn(9, prod)
        self.assertNotIn(9, dev)
        self.assertIn(2, dev)
        self.assertNotIn(2, prod)
        self.assertIn(5, dev)

    def test_shipping_types_per_instance(self):
        self.assertIn("D08120200001", curation.shipping_types("prod"))
        self.assertNotIn("D08120200001", curation.shipping_types("dev"))
        # Hajime's ship/receive type is a dev shipping box (#48) — dev only.
        self.assertIn(DEV_PTID, curation.shipping_types("dev"))
        self.assertNotIn(DEV_PTID, curation.shipping_types("prod"))


class InstanceUrlTest(TestCase):
    def test_node_path_carries_the_instance_prefix(self):
        prod = navigation.node_path("prod", "FD", "FD-CE")
        dev = navigation.node_path("dev", "FD", "FD-HD")
        self.assertTrue(prod.startswith("/hw/") and "/hw/dev/" not in prod)
        self.assertTrue(dev.startswith("/hw/dev/"))

    def test_reverse_via_instance_namespace(self):
        self.assertEqual(reverse("explore:home"), "/hw/")
        self.assertEqual(reverse("explore:home", current_app="explore_dev"), "/hw/dev/")

    def test_sync_state_is_per_instance(self):
        self.assertNotEqual(HierarchySyncState.get("prod").pk,
                            HierarchySyncState.get("dev").pk)


class InstanceViewTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("explorer", "e@e.io", "pw")
        self.client.force_login(self.user)
        _node("prod", "D05700200001", 57, "FD-VD TDE", 2, "Digital electronics",
              "AMC", n_components=10)
        _node("dev", DEV_PTID, 5, "Dev sandbox sys", 998, "Shipping",
              "Test shipping box", n_components=2)

    def test_trees_are_instance_scoped(self):
        prod_html = self.client.get("/hw/").content.decode()
        dev_html = self.client.get("/hw/dev/").content.decode()
        self.assertIn("AMC", prod_html)
        self.assertNotIn("Test shipping box", prod_html)
        self.assertIn("Test shipping box", dev_html)
        self.assertNotIn("AMC", dev_html)

    def test_dev_banner_and_switch(self):
        prod_html = self.client.get("/hw/").content.decode()
        dev_html = self.client.get("/hw/dev/").content.decode()
        self.assertIn("DEVELOPMENT HWDB", dev_html)
        self.assertNotIn("DEVELOPMENT HWDB", prod_html)
        # both pages offer the switch to the other instance's root
        self.assertIn('href="/hw/dev/"', prod_html)
        self.assertIn('href="/hw/"', dev_html)

    def test_dev_page_links_stay_on_dev(self):
        # {% url %} reversing (navbar) is pinned to /hw/dev/ by the middleware.
        dev_html = self.client.get("/hw/dev/").content.decode()
        self.assertIn('href="/hw/dev/search/"', dev_html)
        self.assertNotIn('href="/hw/search/"', dev_html)

    def test_dev_leaf_drill_in(self):
        url = navigation.leaf_path_for("dev", DEV_PTID)
        self.assertTrue(url.startswith("/hw/dev/FD/FD-HD/5/"))
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Test shipping box", resp.content.decode())

    def test_anon_login_redirect_stays_on_dev(self):
        self.client.logout()
        resp = self.client.get("/hw/dev/")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["Location"].startswith("/hw/dev/login/"))

    def test_cross_instance_paths_404(self):
        # Region keys are shared prod-style, but family membership is
        # per-instance: system 2 is dev-FD-HD-only, 9 is prod-FD-HD-only.
        self.assertEqual(self.client.get("/hw/FD/FD-HD/2/").status_code, 404)
        self.assertEqual(self.client.get("/hw/dev/FD/FD-HD/9/").status_code, 404)
        self.assertEqual(self.client.get("/hw/NOPE/").status_code, 404)

    def test_search_api_is_instance_scoped(self):
        prod = self.client.get("/hw/search/api/", {"q": "shipping box"}).json()
        dev = self.client.get("/hw/dev/search/api/", {"q": "shipping box"}).json()
        self.assertEqual(prod["types"], [])
        self.assertEqual(len(dev["types"]), 1)
        self.assertTrue(dev["types"][0]["path"].startswith("/hw/dev/"))


class DevShipmentsTest(TestCase):
    """Dev shipping boxes in the Shipments tab (#48). The engine/view plumbing
    is instance-aware since #47; these prove the dev shipping type end-to-end."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("shipper", "s@s.io", "pw")
        self.client.force_login(self.user)
        self.leaf = _node("dev", DEV_PTID, 5, "FD1-HD HVS", 998, "HWDBUnitTest",
                          "Test Type 007", n_components=147,
                          shipments_synced_at=timezone.now(),
                          tests_synced_at=timezone.now())

    def _box(self, **over):
        row = dict(instance="dev", part_type_id=DEV_PTID,
                   part_id="D00599800007-00133", location_name="BNL",
                   location_id=128, n_contents=3, last_arrived=timezone.now())
        row.update(over)
        return ShipmentItem.objects.create(**row)

    def test_dev_leaf_renders_shipment_panel(self):
        self._box()
        html = self.client.get(navigation.leaf_path_for("dev", DEV_PTID)).content.decode()
        self.assertIn("D00599800007-00133", html)
        self.assertIn("BNL", html)
        self.assertNotIn('id="node-unsynced"', html)  # both syncs marked done

    def test_shipments_tab_is_instance_scoped(self):
        self._box()
        dev_html = self.client.get("/hw/dev/shipments/").content.decode()
        prod_html = self.client.get("/hw/shipments/").content.decode()
        self.assertIn("D00599800007-00133", dev_html)
        self.assertNotIn("D00599800007-00133", prod_html)

    def test_sync_writes_dev_scoped_rows(self):
        client = mock.MagicMock()
        client._make_request.side_effect = lambda m, e, data=None, params=None: {
            "data": [{"part_id": "D00599800007-00075"}], "pagination": {"pages": 1}}
        client.get_locations.side_effect = lambda pid: {"data": [
            {"arrived": "2026-06-10T00:00:00-05:00",
             "location": {"id": 0, "name": "In Transit"}}]}
        client.get_subcomponents.side_effect = lambda pid: {"data": [
            {"part_id": "X1", "type_name": "T", "functional_position": "1",
             "operation": "mount"}]}
        with mock.patch("explore.shipments.FnalDbApiClient", return_value=client):
            list(shipments.sync_shipments("http://api", "b", DEV_PTID, "dev"))
        box = ShipmentItem.objects.get(part_id="D00599800007-00075")
        self.assertEqual(box.instance, "dev")
        self.assertEqual(ShipmentItem.for_instance("prod").count(), 0)
        self.leaf.refresh_from_db()
        self.assertIsNotNone(self.leaf.shipments_synced_at)


class OverflowViewTest(TestCase):
    """The synthetic "Uncurated" region on the dev tree (#49)."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("uncur", "u@u.io", "pw")
        self.client.force_login(self.user)
        _node("dev", DEV_PTID, 5, "FD1-HD HVS", 998, "HWDBUnitTest",
              "Test Type 007", n_components=147)
        self.sys900 = H.objects.create(
            instance="dev", level=H.LEVEL_SYSTEM, system_id=900,
            system_name="ProtoDUNE-II complete detector", name="ProtoDUNE-II complete detector")

    def test_uncurated_section_on_dev_only(self):
        self.assertIn("Uncurated", self.client.get("/hw/dev/").content.decode())
        self.assertIn("Uncurated", self.client.get("/hw/dev/browse/").content.decode())
        self.assertNotIn("Uncurated", self.client.get("/hw/browse/").content.decode())
        self.assertEqual(self.client.get("/hw/UNC/").status_code, 404)

    def test_home_tree_links_unwalked_systems(self):
        # The Overview tree only renders childless nodes as links when they
        # carry a url — without one, unwalked overflow systems were dead rows.
        html = self.client.get("/hw/dev/").content.decode()
        self.assertIn("/hw/dev/UNC/900/", html)
        self.assertIn('"unwalked": true', html)

    def test_overflow_region_lists_systems(self):
        html = self.client.get("/hw/dev/UNC/").content.decode()
        self.assertIn("ProtoDUNE-II complete detector", html)
        # The synthetic region holds only uncurated systems — no duplication of
        # the curated system 5 (the page's sidebar still shows the full tree).
        region = navigation.overflow_region("dev")
        self.assertEqual([f["systems"] for f in region["families"]], [[900]])

    def test_unwalked_system_autofires_walk(self):
        html = self.client.get("/hw/dev/UNC/900/").content.decode()
        self.assertIn('id="system-unwalked"', html)
        self.assertIn("/hw/dev/sync-system/900/", html)

    def test_errored_walk_shows_retry_not_autofire(self):
        self.sys900.tests_sync_error = "boom"
        self.sys900.save()
        html = self.client.get("/hw/dev/UNC/900/").content.decode()
        self.assertNotIn('id="system-unwalked"', html)
        self.assertIn("system-walk-btn", html)
        self.assertIn("Last walk error", html)

    def test_walked_system_drills_in_like_curated(self):
        self.sys900.structure_synced_at = timezone.now()
        self.sys900.save()
        sub = H.objects.create(
            instance="dev", level=H.LEVEL_SUBSYSTEM, parent=self.sys900, system_id=900,
            subsystem_id=2, system_name=self.sys900.system_name,
            subsystem_name="CRP", name="CRP")
        H.objects.create(
            instance="dev", level=H.LEVEL_TYPE, parent=sub, system_id=900,
            subsystem_id=2, system_name=self.sys900.system_name, subsystem_name="CRP",
            name="Adapter Board", part_type_id="D90000200001", n_components=3)
        html = self.client.get("/hw/dev/UNC/900/").content.decode()
        self.assertNotIn('id="system-unwalked"', html)
        self.assertIn("CRP", html)
        path = navigation.leaf_path_for("dev", "D90000200001")
        self.assertTrue(path.startswith("/hw/dev/UNC/900/"))
        self.assertEqual(self.client.get(path).status_code, 200)
