"""Tests for FNAL device-flow as the explore site's sole login (#33, ADR-0011).

The vault device-flow driver is mocked; no live FNAL calls. End-to-end
verification (real CILogon login) is a manual step on the FNAL network.

    python manage.py test explore
"""

from __future__ import annotations

from unittest import mock

from django.contrib.auth import SESSION_KEY, get_user_model
from django.test import TestCase
from django.urls import reverse

from hwdb.fnal import flow
from hwdb.fnal.session import FLOW_KEY, LINK_KEY


def _start():
    return flow.StartResult(
        auth_url="https://cilogon.org/device/?user_code=ABC-DEF",
        user_code="ABC-DEF",
        poll_body={"state": "s", "client_nonce": "n"},
    )


def _complete_auth(credkey="chaoz"):
    return {
        "client_token": "s.vault-token-xyz",
        "lease_duration": 2419200,
        "metadata": {"credkey": credkey},
    }


class ExploreLoginRedirectTest(TestCase):
    def test_anonymous_explore_redirects_to_fnal_login(self):
        resp = self.client.get(reverse("explore:home"))
        self.assertEqual(resp.status_code, 302)
        loc = resp["Location"]
        self.assertIn(reverse("explore:login"), loc)
        self.assertNotIn(reverse("rest_framework:login"), loc)  # not the password page
        self.assertIn("next=", loc)

    def test_anonymous_sync_endpoint_also_routes_to_fnal_login(self):
        resp = self.client.post(reverse("explore:sync"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("explore:login"), resp["Location"])


class ExploreLoginViewTest(TestCase):
    def test_login_view_starts_flow_with_login_intent(self):
        with mock.patch("hwdb.fnal.flow.start", return_value=_start()):
            resp = self.client.get(reverse("explore:login"), {"next": "/explore/?node=D1"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "cilogon.org/device")
        state = self.client.session[FLOW_KEY]
        self.assertTrue(state["login_user"])           # explore intent set
        self.assertEqual(state["next"], "/explore/?node=D1")

    def test_login_view_rejects_unsafe_next(self):
        with mock.patch("hwdb.fnal.flow.start", return_value=_start()):
            self.client.get(reverse("explore:login"), {"next": "https://evil.example.com/x"})
        self.assertEqual(self.client.session[FLOW_KEY]["next"], reverse("explore:home"))

    def test_already_authenticated_skips_to_next(self):
        u = get_user_model().objects.create_user("someone", password="x")
        self.client.force_login(u)
        with mock.patch("hwdb.fnal.flow.start", return_value=_start()) as start:
            resp = self.client.get(reverse("explore:login"))
        self.assertEqual(resp.status_code, 302)
        start.assert_not_called()                       # no flow started
        self.assertNotIn(FLOW_KEY, self.client.session)


class ExploreLoginPollTest(TestCase):
    def _seed(self, next_url="/explore/"):
        with mock.patch("hwdb.fnal.flow.start", return_value=_start()):
            self.client.get(reverse("explore:login"), {"next": next_url})

    def test_poll_pending(self):
        self._seed()
        with mock.patch("hwdb.fnal.flow.poll",
                        return_value=flow.PollResult(outcome="pending", auth=None)):
            resp = self.client.get(reverse("explore:login_poll"))
        self.assertEqual(resp.json()["status"], "pending")

    def test_completion_provisions_user_and_logs_in(self):
        self._seed(next_url="/explore/?node=D08100100003")
        User = get_user_model()
        self.assertFalse(User.objects.filter(username="chaoz").exists())
        with mock.patch("hwdb.fnal.flow.poll",
                        return_value=flow.PollResult(outcome="complete", auth=_complete_auth())):
            resp = self.client.get(reverse("explore:login_poll"))

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["next"], "/explore/?node=D08100100003")

        # User auto-provisioned, keyed on credkey, password-less, and logged in.
        u = User.objects.get(username="chaoz")
        self.assertFalse(u.has_usable_password())
        self.assertEqual(int(self.client.session[SESSION_KEY]), u.pk)
        # Vault link stored; flow cleared.
        self.assertIn(LINK_KEY, self.client.session)
        self.assertNotIn(FLOW_KEY, self.client.session)

    def test_second_login_reuses_user(self):
        User = get_user_model()
        for _ in range(2):
            self._seed()
            with mock.patch("hwdb.fnal.flow.poll",
                            return_value=flow.PollResult(outcome="complete", auth=_complete_auth())):
                self.client.get(reverse("explore:login_poll"))
        self.assertEqual(User.objects.filter(username="chaoz").count(), 1)

    def test_authenticated_explore_user_can_view(self):
        # After login, the credkey user can view the explore tree (no FNAL link
        # needed to *view*).
        self._seed()
        with mock.patch("hwdb.fnal.flow.poll",
                        return_value=flow.PollResult(outcome="complete", auth=_complete_auth())):
            self.client.get(reverse("explore:login_poll"))
        resp = self.client.get(reverse("explore:home"))
        self.assertEqual(resp.status_code, 200)
