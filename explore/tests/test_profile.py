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
        # avatar initials are first + last name (CZ), not the first two letters
        self.assertIn('class="pf-avatar">CZ<', html)
        # …and the visit caches the name, so the HEADER avatar shows CZ too
        self.assertRegex(html, r'class="eh-user-dot eh-acct-btn"[^>]*>CZ<')
        # …and the page has a tree, so the drawer aside is not marked bare (#93).
        self.assertIn('<aside class="ex-side" id="ex-side"', html)
        self.assertEqual(self.client.session["fnal_full_name"], "Chao Zhang")

    def test_false_admin_architect_flags_are_hidden(self):
        api = _api()                            # fixture: both flags False
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(PAGE).content.decode()
        self.assertIn("Active ✓", html)
        self.assertNotIn("Administrator", html)
        self.assertNotIn("Architect", html)

    def test_true_flags_show(self):
        api = _api({"data": {**WHOAMI["data"], "architect": True}})
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(PAGE).content.decode()
        self.assertIn("Architect ✓", html)
        self.assertNotIn("Administrator", html)

    def test_no_roles_warns_writes_are_refused(self):
        api = _api({"data": {**WHOAMI["data"], "roles": []}})
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(PAGE).content.decode()
        self.assertIn("Roles (0)", html)
        self.assertIn("will be refused", html)

    def test_account_menu_links_to_profile_and_signs_out(self):
        # The avatar in the top bar opens the account menu: the name, the
        # profile page, Sign out — no name or button in the bar itself.
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(PAGE).content.decode()
        self.assertIn('popovertarget="eh-acct"', html)
        menu = html.split('id="eh-acct" popover>', 1)[1].split("</div>\n            {% endif", 1)[0][:900]
        self.assertIn('<div class="eh-acct-name">', menu)
        self.assertIn('<a href="/hw/dev/profile/">Profile</a>', menu)
        self.assertIn('<button type="submit">Sign out</button>', menu)
        self.assertEqual(html.count("Sign out"), 1)

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
