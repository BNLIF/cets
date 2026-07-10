"""Tests for the Update-location write path (issue #61) — the explorer's first
HWDB write. Writes are gated to instances in ``HWDB_WRITE_INSTANCES`` (dev by
default): the form only renders there, and the POST endpoint enforces the same
gate server-side. HWDB is mocked throughout.

    python manage.py test explore
"""

from __future__ import annotations

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from explore.models import ShipmentItem
from hwdb.fnal.bearer import FnalLinkRequired

# Hajime's ship/receive walkthrough type — explicitly curated as a dev
# shipping type; its prod counterpart below is curated via subsystem 81.202.
DEV_BOX = "D00599800007-00128"
PROD_BOX = "D08120200001-00001"
DEV_PAGE = f"/hw/dev/part/{DEV_BOX}/"
DEV_POST = f"/hw/dev/part/{DEV_BOX}/location/"


def _api():
    api = mock.MagicMock()
    api.get_component.return_value = {"data": {
        "serial_number": "SN", "status": "Passed",
        "component_type": {"name": "Test Type 007"},
        "specifications": [{"DATA": {}}]}}
    api.get_locations.return_value = {"data": [
        {"arrived": "2026-07-01T00:00:00", "location": {"id": 128, "name": "BNL"},
         "creator": "hajime", "comments": ""}]}
    api.get_subcomponents.return_value = {"data": []}
    api.get_images.return_value = {"data": []}
    api.get_test_types.return_value = {"data": []}
    api.get_tests.return_value = {"data": []}
    api.get_institutions.return_value = {"data": [
        {"id": 128, "name": "Brookhaven National Laboratory", "country": {"code": "US"}},
        {"id": 186, "name": "SURF", "country": {"code": "US"}}]}
    api.post_location.return_value = {"status": "OK"}
    return api


def _mocked(api):
    return (mock.patch("explore.views.mint_for", return_value="bearer"),
            mock.patch("explore.views.FnalDbApiClient", return_value=api))


class LocationFormRenderTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("w", "w@w.io", "pw")
        self.client.force_login(self.user)

    def test_form_renders_on_dev_box_page_with_institutions(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(DEV_PAGE).content.decode()
        self.assertIn("Update location", html)
        self.assertIn(f"{DEV_POST}", html)
        self.assertIn("Brookhaven National Laboratory", html)

    def test_form_absent_on_prod_box_page(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(f"/hw/part/{PROD_BOX}/").content.decode()
        self.assertNotIn("Update location", html)
        api.get_institutions.assert_not_called()


class LocationPostTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("w", "w@w.io", "pw")
        self.client.force_login(self.user)

    def test_post_writes_payload_and_refreshes_mirror_row(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post(DEV_POST, {
                "location_id": "186", "arrived": "2026-07-10T09:00",
                "comments": "moved to SURF"})
        self.assertRedirects(resp, DEV_PAGE, fetch_redirect_response=False)
        api.post_location.assert_called_once_with(DEV_BOX, {
            "location": {"id": 186},
            "arrived": "2026-07-10T09:00:00",
            "comments": "moved to SURF"})
        row = ShipmentItem.for_instance("dev").get(part_id=DEV_BOX)
        self.assertEqual(row.part_type_id, "D00599800007")
        self.assertEqual(row.location_name, "BNL")  # from the mocked re-fetch

    def test_prod_post_is_forbidden_server_side(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post(f"/hw/part/{PROD_BOX}/location/",
                                    {"location_id": "186", "arrived": "2026-07-10T09:00"})
        self.assertEqual(resp.status_code, 403)
        api.post_location.assert_not_called()

    def test_non_shipping_part_is_forbidden(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post("/hw/dev/part/D05700200099-00007/location/",
                                    {"location_id": "186", "arrived": "2026-07-10T09:00"})
        self.assertEqual(resp.status_code, 403)
        api.post_location.assert_not_called()

    def test_invalid_input_posts_nothing_and_surfaces_error(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post(DEV_POST, {"location_id": "", "arrived": "not-a-date"},
                                    follow=True)
        api.post_location.assert_not_called()
        self.assertIn("Pick a location and a valid arrival time",
                      resp.content.decode())

    def test_hwdb_error_surfaces_readably(self):
        import requests
        api = _api()
        api.post_location.side_effect = requests.exceptions.HTTPError(
            "422 Unprocessable for …/locations: extra fields not permitted")
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post(DEV_POST, {
                "location_id": "186", "arrived": "2026-07-10T09:00"}, follow=True)
        self.assertIn("HWDB rejected the location update", resp.content.decode())
        self.assertIn("extra fields not permitted", resp.content.decode())
        self.assertFalse(ShipmentItem.for_instance("dev").filter(part_id=DEV_BOX).exists())

    def test_expired_fnal_link_redirects_to_link_page(self):
        with mock.patch("explore.views.mint_for", side_effect=FnalLinkRequired()):
            resp = self.client.post(DEV_POST, {
                "location_id": "186", "arrived": "2026-07-10T09:00"})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("link", resp["Location"])
