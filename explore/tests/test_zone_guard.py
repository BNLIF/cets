"""Tests for the two-zone authorization guard (#34, ADR-0011).

An explore-only (FNAL-provisioned, no `cets` group) user may reach the explore
zone + the FNAL flow + admin/login, but is 403'd from the CETS/CE zone. CETS
members and superusers reach everything; `is_staff` alone is not enough.

    python manage.py test explore
"""

from __future__ import annotations

from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse


class _Base(TestCase):
    def setUp(self):
        User = get_user_model()
        self.explore_user = User.objects.create_user("alice", password="x")  # no group
        self.cets_user = User.objects.create_user("bob", password="x")
        Group.objects.get(name="cets").user_set.add(self.cets_user)
        self.staff_user = User.objects.create_user("carol", password="x", is_staff=True)
        self.super_user = User.objects.create_superuser("root", "r@r.io", "x")


class CetsZoneGuardTest(_Base):
    def setUp(self):
        super().setUp()
        self.cets_url = reverse("hwdb:home")
        self.explore_url = reverse("explore:home")

    def test_explore_only_user_blocked_from_cets(self):
        self.client.force_login(self.explore_user)
        self.assertEqual(self.client.get(self.cets_url).status_code, 403)

    def test_deny_page_offers_cets_login_with_next(self):
        # The deny page must not be a dead end — it links to the CETS login,
        # carrying the requested path so login returns the user there.
        self.client.force_login(self.explore_user)
        resp = self.client.get(self.cets_url)
        self.assertEqual(resp.status_code, 403)
        from urllib.parse import urlencode
        body = resp.content.decode()
        login = reverse("rest_framework:login")
        self.assertIn(f"{login}?{urlencode({'next': self.cets_url})}", body)

    def test_explore_only_user_allowed_on_explore(self):
        self.client.force_login(self.explore_user)
        self.assertEqual(self.client.get(self.explore_url).status_code, 200)

    def test_cets_member_reaches_both_zones(self):
        self.client.force_login(self.cets_user)
        self.assertEqual(self.client.get(self.cets_url).status_code, 200)
        self.assertEqual(self.client.get(self.explore_url).status_code, 200)

    def test_superuser_reaches_cets(self):
        self.client.force_login(self.super_user)
        self.assertEqual(self.client.get(self.cets_url).status_code, 200)

    def test_staff_without_group_still_blocked(self):
        # is_staff alone does not grant CETS access — only the cets group does.
        self.client.force_login(self.staff_user)
        self.assertEqual(self.client.get(self.cets_url).status_code, 403)

    def test_anonymous_not_403_by_guard(self):
        # Anonymous is handled by the login gates (redirect), not the guard.
        self.assertEqual(self.client.get(self.cets_url).status_code, 302)


class ExploreUserAllowListTest(_Base):
    def test_can_reach_fnal_relink_flow(self):
        # explore sync redirects here to relink — must not be 403'd.
        self.client.force_login(self.explore_user)
        start = mock.Mock(auth_url="https://cilogon.org/device/", user_code="X",
                          poll_body={"state": "s", "client_nonce": "n"})
        with mock.patch("hwdb.fnal.flow.start", return_value=start):
            resp = self.client.get(reverse("hwdb:link"))
        self.assertEqual(resp.status_code, 200)

    def test_admin_allowed_through_guard(self):
        # Not a 403 from our guard; admin enforces its own staff check (302 to
        # its login).
        self.client.force_login(self.explore_user)
        resp = self.client.get(reverse("admin:index"))
        self.assertNotEqual(resp.status_code, 403)
