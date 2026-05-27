"""Tests for the HWDB section shell (issue #13): landing, nav, retired tree.

    python manage.py test hwdb
"""

from __future__ import annotations

from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from hwdb.fnal.bearer import FnalLinkRequired


class SectionShellTest(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user("guest", password="x")
        self.client.force_login(user)

    def test_landing_lists_component_type_cards(self):
        resp = self.client.get(reverse("hwdb:home"))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "hwdb/home.html")
        for name in ("LArASIC", "ColdADC", "COLDATA", "FEMB", "Cable"):
            self.assertContains(resp, name)
        # LArASIC is the only active card -> it links into the Display view,
        # using the configured instance's part type.
        self.assertContains(
            resp,
            reverse("hwdb:component_list", args=[settings.HWDB_LARASIC_PART_TYPE]),
        )
        self.assertContains(resp, "coming soon")
        # "More" card links into the generic tree browse.
        self.assertContains(resp, reverse("hwdb:subsystem_list"))

    def test_landing_is_not_fnal_gated(self):
        # Static cards: no FNAL link required, so no redirect to /hwdb/link/.
        resp = self.client.get(reverse("hwdb:home"))
        self.assertEqual(resp.status_code, 200)

    def test_nav_tab_present(self):
        resp = self.client.get(reverse("hwdb:home"))
        # The HWDB nav tab links to the landing and is marked current.
        self.assertContains(resp, 'href="{}" aria-current="page"'.format(reverse("hwdb:home")))
        self.assertContains(resp, 'nav-tab-dot"></span>HWDB')

    def test_pagination_bar_renders_on_inner_page(self):
        # Page 3 of 5: both prev and next nav present, stable bar at the top.
        payload = {
            "component_type": {"name": "LArASIC"},
            "data": [{"serial_number": "002-00001", "part_id": "p1"}],
            "pagination": {"page": 3, "page_size": 100, "pages": 5},
        }
        with mock.patch("hwdb.views.mint_for", return_value="b"), mock.patch(
            "hwdb.api_client.FnalDbApiClient._make_request", return_value=payload
        ):
            resp = self.client.get(
                reverse("hwdb:component_list", args=["D08100100001"]) + "?page=3"
            )
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("pagination", body)
        self.assertIn("3/5", body)
        # First/Prev/Next/Last all live links on an inner page.
        self.assertIn("page=1&size=100", body)  # First
        self.assertIn("page=2&size=100", body)  # Prev
        self.assertIn("page=4&size=100", body)  # Next
        self.assertIn("page=5&size=100", body)  # Last
        self.assertNotIn("disabled", body)

    def test_defaults_to_prod_instance(self):
        # Default HWDB_INSTANCE is prod: prod API path, prod LArASIC part type.
        self.assertEqual(settings.HWDB_INSTANCE, "prod")
        self.assertIn("/cdb/api/", settings.HWDB_API_BASE_URL)
        self.assertNotIn("cdbdev", settings.HWDB_API_BASE_URL)
        self.assertEqual(settings.HWDB_LARASIC_PART_TYPE, "D08100100003")

    def test_external_links_use_instance_ui_base(self):
        payload = {
            "component_type": {"name": "LArASIC"},
            "data": [{"serial_number": "x", "part_id": "p", "component_id": "c1"}],
            "pagination": {"page": 1, "page_size": 100, "pages": 1},
        }
        with mock.patch("hwdb.views.mint_for", return_value="b"), mock.patch(
            "hwdb.api_client.FnalDbApiClient._make_request", return_value=payload
        ):
            resp = self.client.get(reverse("hwdb:component_list", args=["D08100100003"]))
        self.assertContains(resp, settings.HWDB_UI_BASE_URL + "/edit/component/c1")
        self.assertNotContains(resp, "cdbdev")

    def test_session_instance_toggle_overrides_default(self):
        # Default is prod; switch this session to dev and the landing's
        # LArASIC card flips to the dev part type — no restart.
        resp = self.client.post(
            reverse("hwdb:set_instance"),
            {"instance": "dev", "next": reverse("hwdb:home")},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.client.session["hwdb_instance"], "dev")

        resp = self.client.get(reverse("hwdb:home"))
        self.assertContains(
            resp, reverse("hwdb:component_list", args=["D08100100001"])
        )  # dev LArASIC part type

    def test_session_instance_toggle_rejects_garbage(self):
        self.client.post(reverse("hwdb:set_instance"), {"instance": "bogus"})
        self.assertNotIn("hwdb_instance", self.client.session)

    def test_dev_session_uses_dev_api_for_display(self):
        self.client.post(reverse("hwdb:set_instance"), {"instance": "dev"})
        captured = {}

        def fake_make_request(self, method, endpoint):
            captured["base"] = self.base_url
            return {"component_type": {"name": "L"}, "data": [], "pagination": {}}

        with mock.patch("hwdb.views.mint_for", return_value="b"), mock.patch(
            "hwdb.api_client.FnalDbApiClient._make_request", fake_make_request
        ):
            self.client.get(reverse("hwdb:component_list", args=["D08100100001"]))
        self.assertIn("cdbdev", captured["base"])

    def test_tree_browse_is_fnal_gated(self):
        # The generic tree (reached via "More") hits the HWDB API, so an
        # unlinked user is redirected to the link page.
        with mock.patch("hwdb.views.mint_for", side_effect=FnalLinkRequired()):
            resp = self.client.get(reverse("hwdb:subsystem_list"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("hwdb:link"), resp["Location"])
