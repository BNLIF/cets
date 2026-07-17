"""Tests for the user profile page: the signed-in account's HWDB identity
and roles (``users/whoami``), reachable from the top-nav user chip.

    python manage.py test explore
"""

from __future__ import annotations

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from hwdb.fnal.bearer import FnalLinkRequired

PAGE = "/hw/dev/profile/"

WHOAMI = {"data": {
    "active": True, "administrator": False, "architect": False,
    "affiliation": "", "email": "chaoz@fnal.gov", "full_name": "Chao Zhang",
    "user_id": 12621, "username": "chaoz",
    "roles": [{"id": 4, "name": "tester"}, {"id": 3, "name": "type-manager"}]}}


def _api(whoami=WHOAMI):
    api = mock.MagicMock()
    api.whoami.return_value = whoami
    return api


def _mocked(api):
    return (mock.patch("explore.views.mint_for", return_value="bearer"),
            mock.patch("explore.views.FnalDbApiClient", return_value=api))


class ProfileViewTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("s", "s@s.io", "pw")
        self.client.force_login(self.user)

    def test_shows_identity_and_roles(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(PAGE).content.decode()
        self.assertIn("Chao Zhang", html)
        self.assertIn("chaoz", html)
        self.assertIn("chaoz@fnal.gov", html)
        self.assertIn("12621", html)
        self.assertIn("tester", html)          # roles listed
        self.assertIn("type-manager", html)
        self.assertIn("#4", html)              # role id shown
        self.assertIn("Roles (2)", html)

    def test_no_roles_warns_writes_are_refused(self):
        api = _api({"data": {**WHOAMI["data"], "roles": []}})
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(PAGE).content.decode()
        self.assertIn("Roles (0)", html)
        self.assertIn("will be refused", html)

    def test_nav_chip_links_to_profile(self):
        # The user chip in the top nav is a link to the profile page.
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(PAGE).content.decode()
        self.assertIn('class="eh-user" href="/hw/dev/profile/"', html)

    def test_expired_link_redirects_to_relink(self):
        with mock.patch("explore.views.mint_for", side_effect=FnalLinkRequired()):
            resp = self.client.get(PAGE)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("link", resp["Location"])

    def test_anonymous_is_redirected_to_login(self):
        self.client.logout()
        resp = self.client.get(PAGE)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("login", resp["Location"])
