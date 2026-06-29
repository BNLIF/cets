"""Tests for the hwdb FNAL link flow (issue #10).

The vault device-flow driver is mocked; no live FNAL calls. End-to-end
verification (real CILogon login) is a manual step on the FNAL network.

    python manage.py test hwdb
"""

from __future__ import annotations

import base64
from unittest import mock

from django.contrib.auth import SESSION_KEY, get_user_model
from django.test import TestCase
from django.urls import reverse

from hwdb.fnal import crypto, flow
from hwdb.fnal.session import FLOW_KEY, LINK_KEY


class LinkFlowTest(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user("guest", password="x")
        self.client.force_login(user)
        self.link_url = reverse("hwdb:link")
        self.poll_url = reverse("hwdb:link_poll")

    def _start(self):
        return flow.StartResult(
            auth_url="https://cilogon.org/device/?user_code=ABC-DEF",
            user_code="ABC-DEF",
            poll_body={"state": "s", "client_nonce": "n"},
        )

    # ---- link view ----

    def test_link_view_starts_flow_and_stashes_session(self):
        with mock.patch("hwdb.fnal.flow.start", return_value=self._start()):
            resp = self.client.get(self.link_url, {"next": "/hwdb/components/"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "cilogon.org/device")
        state = self.client.session[FLOW_KEY]
        self.assertEqual(state["poll_body"]["state"], "s")
        self.assertEqual(state["next"], "/hwdb/components/")

    def test_link_view_rejects_unsafe_next(self):
        with mock.patch("hwdb.fnal.flow.start", return_value=self._start()):
            self.client.get(self.link_url, {"next": "https://evil.example.com/x"})
        # Falls back to the hwdb home, not the external URL.
        self.assertEqual(self.client.session[FLOW_KEY]["next"], reverse("hwdb:home"))

    def test_link_view_vault_down_shows_error(self):
        with mock.patch("hwdb.fnal.flow.start", side_effect=RuntimeError("vault down")):
            resp = self.client.get(self.link_url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "unavailable")
        self.assertNotIn(FLOW_KEY, self.client.session)

    # ---- poll view ----

    def _seed_flow(self, next_url="/hwdb/components/"):
        with mock.patch("hwdb.fnal.flow.start", return_value=self._start()):
            self.client.get(self.link_url, {"next": next_url})

    def test_poll_no_flow_404(self):
        resp = self.client.get(self.poll_url)
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["status"], "error")

    def test_poll_pending(self):
        self._seed_flow()
        with mock.patch(
            "hwdb.fnal.flow.poll",
            return_value=flow.PollResult(outcome="pending", auth=None),
        ):
            resp = self.client.get(self.poll_url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "pending")

    def test_poll_complete_stores_encrypted_token_and_clears_flow(self):
        self._seed_flow(next_url="/hwdb/components/D08100400001/")
        auth = {
            "client_token": "s.vault-token-xyz",
            "lease_duration": 2419200,
            "metadata": {"credkey": "chaoz"},
        }
        with mock.patch(
            "hwdb.fnal.flow.poll",
            return_value=flow.PollResult(outcome="complete", auth=auth),
        ):
            resp = self.client.get(self.poll_url)

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["next"], "/hwdb/components/D08100400001/")

        # Flow state cleared; completed link stored and decryptable.
        sess = self.client.session
        self.assertNotIn(FLOW_KEY, sess)
        link = sess[LINK_KEY]
        self.assertEqual(link["credkey"], "chaoz")
        ct = base64.b64decode(link["vault_ct"])
        nonce = base64.b64decode(link["vault_nonce"])
        self.assertEqual(crypto.decrypt(ct, nonce), b"s.vault-token-xyz")

    def test_ce_flow_does_not_provision_or_swap_user(self):
        # ADR-0011: the CE "Link FNAL" flow stays link-only — it must NOT create
        # a credkey-named user or swap the logged-in `guest` for one. Only the
        # explore-started flow (login_user=True) logs a user in.
        self._seed_flow()
        self.assertFalse(self.client.session[FLOW_KEY].get("login_user"))
        auth = {
            "client_token": "s.tok",
            "lease_duration": 2419200,
            "metadata": {"credkey": "chaoz"},
        }
        with mock.patch(
            "hwdb.fnal.flow.poll",
            return_value=flow.PollResult(outcome="complete", auth=auth),
        ):
            self.client.get(self.poll_url)
        User = get_user_model()
        self.assertFalse(User.objects.filter(username="chaoz").exists())
        # Still the original guest in the session.
        self.assertEqual(self.client.session[SESSION_KEY], str(User.objects.get(username="guest").pk))

    def test_poll_expired_flow_410_and_cleared(self):
        self._seed_flow()
        # Force the stored flow to look expired.
        sess = self.client.session
        sess[FLOW_KEY]["expires_at"] = "2000-01-01T00:00:00+00:00"
        sess.save()
        resp = self.client.get(self.poll_url)
        self.assertEqual(resp.status_code, 410)
        self.assertNotIn(FLOW_KEY, self.client.session)
