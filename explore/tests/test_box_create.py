"""Tests for the New-box mint path (issue #62) — creating a shipping box from
its type's page, plus the lazy institutions endpoint and the reuse-existing
picker. Writes stay gated to ``HWDB_WRITE_INSTANCES`` (dev). HWDB is mocked.

    python manage.py test explore
"""

from __future__ import annotations

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from explore import navigation
from explore.models import HierarchyNode as H
from explore.models import ShipmentItem
from hwdb.fnal.bearer import FnalLinkRequired

PTID = "D08120200055"  # under dev-curated shipping subsystem "81.202"
NEW_PID = f"{PTID}-00042"


def _dev_ship_leaf(ptid=PTID):
    """The FD CE › CE Shipping Box chain on the DEV instance."""
    sys, _ = H.objects.get_or_create(
        instance="dev", level=H.LEVEL_SYSTEM, system_id=81, subsystem_id=None,
        part_type_id="", defaults={"system_name": "FD CE", "name": "FD CE"})
    sub, _ = H.objects.get_or_create(
        instance="dev", level=H.LEVEL_SUBSYSTEM, system_id=81, subsystem_id=202,
        part_type_id="", defaults={"parent": sys, "system_name": "FD CE",
                                   "subsystem_name": "CE Shipping Box",
                                   "name": "CE Shipping Box"})
    return H.objects.create(
        instance="dev", level=H.LEVEL_TYPE, parent=sub, system_id=81,
        system_name="FD CE", subsystem_id=202, subsystem_name="CE Shipping Box",
        name="CE Shipping box", part_type_id=ptid, n_components=1,
        full_name="D.FD CE.CE Shipping Box.CE Shipping box",
        shipments_synced_at=timezone.now(), tests_synced_at=timezone.now())


def _api(manufacturers=None):
    api = mock.MagicMock()
    api.get_institutions.return_value = {"data": [
        {"id": 128, "name": "Brookhaven National Laboratory", "country": {"code": "US"}},
        {"id": 186, "name": "SURF", "country": {"code": "US"}}]}
    api.get_component_type.return_value = {"status": "OK", "data": {
        "part_type_id": PTID, "manufacturers": manufacturers or [],
        "properties": {"specifications": [{"datasheet": {"Batch": None, "_meta": {}}}]}}}
    api.create_component.return_value = {"status": "OK", "part_id": NEW_PID}
    api.get_locations.return_value = {"data": []}   # refresh_box after mint
    api.get_subcomponents.return_value = {"data": []}
    return api


def _mocked(api):
    return (mock.patch("explore.views.mint_for", return_value="bearer"),
            mock.patch("explore.views.FnalDbApiClient", return_value=api))


class NewBoxPaneRenderTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("b", "b@b.io", "pw")
        self.client.force_login(self.user)

    def test_pane_renders_on_dev_shipping_leaf_with_reuse_picker(self):
        leaf = _dev_ship_leaf()
        ShipmentItem.objects.create(instance="dev", part_type_id=PTID,
                                    part_id=f"{PTID}-00007", n_contents=0)
        url = navigation.leaf_path_for("dev", leaf.part_type_id)
        html = self.client.get(url).content.decode()
        self.assertIn("New box", html)
        self.assertIn(f"/hw/dev/box-create/{PTID}/", html)
        self.assertIn("/hw/dev/institutions/", html)
        self.assertIn(f"{PTID}-00007", html)  # reuse-existing option

    @override_settings(HWDB_WRITE_INSTANCES=["dev"])
    def test_pane_absent_on_prod_leaf(self):
        sys, _ = H.objects.get_or_create(
            level=H.LEVEL_SYSTEM, system_id=81, subsystem_id=None, part_type_id="",
            defaults={"system_name": "FD CE", "name": "FD CE"})
        sub, _ = H.objects.get_or_create(
            level=H.LEVEL_SUBSYSTEM, system_id=81, subsystem_id=202, part_type_id="",
            defaults={"parent": sys, "system_name": "FD CE",
                      "subsystem_name": "CE Shipping Box", "name": "CE Shipping Box"})
        leaf = H.objects.create(
            level=H.LEVEL_TYPE, parent=sub, system_id=81, system_name="FD CE",
            subsystem_id=202, subsystem_name="CE Shipping Box", name="CE Shipping box",
            part_type_id="D08120200001", n_components=1,
            full_name="D.FD CE.CE Shipping Box.CE Shipping box",
            shipments_synced_at=timezone.now(), tests_synced_at=timezone.now())
        html = self.client.get(
            navigation.leaf_path_for("prod", leaf.part_type_id)).content.decode()
        self.assertNotIn("New box", html)
        self.assertNotIn("box-create", html)


class BoxCreateTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("b", "b@b.io", "pw")
        self.client.force_login(self.user)
        self.leaf = _dev_ship_leaf()
        self.url = f"/hw/dev/box-create/{PTID}/"

    def test_mint_posts_official_payload_and_lands_on_new_box(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post(self.url, {
                "institution_id": "186", "serial_number": "BOX-42",
                "comments": "minted from explorer"})
        self.assertRedirects(resp, f"/hw/dev/part/{NEW_PID}/",
                             fetch_redirect_response=False)
        api.create_component.assert_called_once_with(PTID, {
            "component_type": {"part_type_id": PTID},
            "country_code": "US",
            "institution": {"id": 186},
            "serial_number": "BOX-42",
            "comments": "minted from explorer",
            "specifications": {"Batch": None, "_meta": {}},
        })
        row = ShipmentItem.for_instance("dev").get(part_id=NEW_PID)
        self.assertEqual(row.n_contents, 0)

    def test_single_manufacturer_is_included(self):
        api = _api(manufacturers=[{"id": 7, "name": "Acme Crates"}])
        m1, m2 = _mocked(api)
        with m1, m2:
            self.client.post(self.url, {"institution_id": "128"})
        payload = api.create_component.call_args.args[1]
        self.assertEqual(payload["manufacturer"], {"id": 7})

    @override_settings(HWDB_WRITE_INSTANCES=["dev"])
    def test_prod_post_is_forbidden(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post("/hw/box-create/D08120200001/",
                                    {"institution_id": "186"})
        self.assertEqual(resp.status_code, 403)
        api.create_component.assert_not_called()

    def test_non_shipping_type_is_forbidden(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post("/hw/dev/box-create/D05700200099/",
                                    {"institution_id": "186"})
        self.assertEqual(resp.status_code, 403)
        api.create_component.assert_not_called()

    def test_unknown_institution_posts_nothing(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post(self.url, {"institution_id": "999"}, follow=True)
        api.create_component.assert_not_called()
        self.assertIn("Pick an institution", resp.content.decode())

    def test_app_level_error_surfaces_on_leaf_page(self):
        api = _api()
        api.create_component.return_value = {
            "status": "ERROR", "data": "serial_number already exists"}
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post(self.url, {"institution_id": "186"}, follow=True)
        html = resp.content.decode()
        self.assertIn("HWDB rejected the new box", html)
        self.assertIn("serial_number already exists", html)
        self.assertFalse(ShipmentItem.for_instance("dev").filter(part_id=NEW_PID).exists())

    def test_expired_link_redirects_to_link_page(self):
        with mock.patch("explore.views.mint_for", side_effect=FnalLinkRequired()):
            resp = self.client.post(self.url, {"institution_id": "186"})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("link", resp["Location"])


class InstitutionsEndpointTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("b", "b@b.io", "pw")
        self.client.force_login(self.user)

    def test_dev_returns_sorted_options(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            data = self.client.get("/hw/dev/institutions/").json()
        self.assertEqual(
            [o["name"] for o in data["institutions"]],
            ["Brookhaven National Laboratory", "SURF"])
        self.assertEqual(data["institutions"][1],
                         {"id": 186, "name": "SURF", "country_code": "US"})

    @override_settings(HWDB_WRITE_INSTANCES=["dev"])
    def test_prod_is_forbidden(self):
        resp = self.client.get("/hw/institutions/")
        self.assertEqual(resp.status_code, 403)
