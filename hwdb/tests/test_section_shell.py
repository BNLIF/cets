"""Tests for the HWDB section shell (issue #13): landing, nav, retired tree.

    python manage.py test hwdb
"""

from __future__ import annotations

from unittest import mock

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
        # LArASIC is the only active card -> it links into the Display view.
        self.assertContains(resp, reverse("hwdb:component_list", args=["D08100100001"]))
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

    def test_tree_browse_is_fnal_gated(self):
        # The generic tree (reached via "More") hits the HWDB API, so an
        # unlinked user is redirected to the link page.
        with mock.patch("hwdb.views.mint_for", side_effect=FnalLinkRequired()):
            resp = self.client.get(reverse("hwdb:subsystem_list"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("hwdb:link"), resp["Location"])
