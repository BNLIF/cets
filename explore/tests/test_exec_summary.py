"""Tests for the executive-summary upload (issue #53 spike): posting a PDF
onto a shipping box under the Dashboard-gate naming convention
``ExecutiveSummary_{pid}_{ts}.pdf``. HWDB is mocked.

    python manage.py test explore
"""

from __future__ import annotations

import re
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from hwdb.fnal.bearer import FnalLinkRequired

BOX = "D00599800007-00128"
PAGE = f"/hw/dev/part/{BOX}/"
POST = f"/hw/dev/part/{BOX}/exec-summary/"


def _api(images=None):
    api = mock.MagicMock()
    api.get_component.return_value = {"data": {
        "serial_number": "SN", "status": "Passed",
        "component_type": {"name": "Test Type 007"},
        "specifications": [{"DATA": {}}]}}
    api.get_component_type.return_value = {"status": "OK", "data": {
        "connectors": {"Slot 1": "D08100100004"}}}
    api.get_subcomponents.return_value = {"data": []}
    api.get_locations.return_value = {"data": []}
    api.get_images.return_value = {"data": images or []}
    api.get_test_types.return_value = {"data": []}
    api.get_tests.return_value = {"data": []}
    api.get_institutions.return_value = {"data": []}
    api.post_component_image.return_value = {"status": "OK", "image_id": "img-1"}
    return api


def _mocked(api):
    return (mock.patch("explore.views.mint_for", return_value="bearer"),
            mock.patch("explore.views.FnalDbApiClient", return_value=api))


def _pdf(name="summary.pdf"):
    return SimpleUploadedFile(name, b"%PDF-1.4 fake", content_type="application/pdf")


class ExecSummaryCardTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("e", "e@e.io", "pw")
        self.client.force_login(self.user)

    def test_card_shows_missing_state_and_upload_form(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(PAGE).content.decode()
        self.assertIn("Executive summary", html)
        self.assertIn("No executive summary on this box yet", html)
        self.assertIn(f"{POST}", html)

    def test_card_lists_existing_summary_and_passes_gate(self):
        existing = f"ExecutiveSummary_{BOX}_20260701-101010.pdf"
        api = _api(images=[{"image_id": "i7", "image_name": existing},
                           {"image_id": "i8", "image_name": "photo.jpg"}])
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(PAGE).content.decode()
        self.assertIn(existing, html)
        self.assertIn("passes the pre-shipping gate", html)

    def test_card_absent_on_prod_box(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get("/hw/part/D08120200001-00001/").content.decode()
        self.assertNotIn("Executive summary", html)


class ExecSummaryPostTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("e", "e@e.io", "pw")
        self.client.force_login(self.user)

    def test_upload_renames_to_gate_convention(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post(POST, {"pdf": _pdf()})
        self.assertRedirects(resp, PAGE, fetch_redirect_response=False)
        (pid, fileobj, name), kwargs = api.post_component_image.call_args
        self.assertEqual(pid, BOX)
        self.assertRegex(name, rf"^ExecutiveSummary_{BOX}_\d{{8}}-\d{{6}}\.pdf$")
        self.assertEqual(kwargs["comments"], "Executive Summary")

    def test_non_pdf_is_rejected(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post(
                POST, {"pdf": SimpleUploadedFile("notes.txt", b"hello")}, follow=True)
        api.post_component_image.assert_not_called()
        self.assertIn("Pick a PDF file", resp.content.decode())

    def test_prod_and_non_shipping_are_forbidden(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            prod = self.client.post("/hw/part/D08120200001-00001/exec-summary/",
                                    {"pdf": _pdf()})
            nonship = self.client.post("/hw/dev/part/D05700200099-00007/exec-summary/",
                                       {"pdf": _pdf()})
        self.assertEqual(prod.status_code, 403)
        self.assertEqual(nonship.status_code, 403)
        api.post_component_image.assert_not_called()

    def test_app_level_error_surfaces(self):
        api = _api()
        api.post_component_image.return_value = {"status": "ERROR",
                                                 "data": "image too large"}
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post(POST, {"pdf": _pdf()}, follow=True)
        html = resp.content.decode()
        self.assertIn("HWDB rejected the summary", html)
        self.assertIn("image too large", html)

    def test_expired_link_redirects_to_link_page(self):
        with mock.patch("explore.views.mint_for", side_effect=FnalLinkRequired()):
            resp = self.client.post(POST, {"pdf": _pdf()})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("link", resp["Location"])
