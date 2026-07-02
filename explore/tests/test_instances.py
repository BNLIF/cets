"""URL-carried HWDB instance support (#47): /hw/dev/ routing, per-instance
curation, mirror scoping, and the dev-page affordances (banner + switch).

    python manage.py test explore.tests.test_instances
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from explore import curation, navigation
from explore.models import HierarchySyncState, HierarchyNode as H

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
        self.assertIn(57, curation.curated_system_ids("prod"))
        self.assertNotIn(57, curation.curated_system_ids("dev"))
        self.assertEqual(curation.curated_system_ids("dev"), {5})

    def test_shipping_types_per_instance(self):
        self.assertIn("D08120200001", curation.shipping_types("prod"))
        self.assertNotIn("D08120200001", curation.shipping_types("dev"))


class InstanceUrlTest(TestCase):
    def test_node_path_carries_the_instance_prefix(self):
        prod = navigation.node_path("prod", "FD", "FD-CE")
        dev = navigation.node_path("dev", "DEV", "DEV-ship")
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
        self.assertTrue(url.startswith("/hw/dev/DEV/DEV-ship/"))
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Test shipping box", resp.content.decode())

    def test_anon_login_redirect_stays_on_dev(self):
        self.client.logout()
        resp = self.client.get("/hw/dev/")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["Location"].startswith("/hw/dev/login/"))

    def test_prod_tree_404s_on_dev_only_paths(self):
        # dev's region key isn't curated on prod, and vice versa.
        self.assertEqual(self.client.get("/hw/DEV/").status_code, 404)
        self.assertEqual(self.client.get("/hw/dev/FD/").status_code, 404)

    def test_search_api_is_instance_scoped(self):
        prod = self.client.get("/hw/search/api/", {"q": "shipping box"}).json()
        dev = self.client.get("/hw/dev/search/api/", {"q": "shipping box"}).json()
        self.assertEqual(prod["types"], [])
        self.assertEqual(len(dev["types"]), 1)
        self.assertTrue(dev["types"][0]["path"].startswith("/hw/dev/"))
