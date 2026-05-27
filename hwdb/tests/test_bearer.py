"""Tests for per-request bearer minting + the @with_fnal_bearer decorator
(issue #11). Vault is mocked; no live FNAL calls.

    python manage.py test hwdb
"""

from __future__ import annotations

import base64
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

import requests
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from hwdb.fnal import crypto
from hwdb.fnal.bearer import FnalLinkRequired, FnalUnavailable, mint_for
from hwdb.fnal.session import LINK_KEY


def _link(token="s.vault-token", credkey="chaoz", expires_in=timedelta(days=28)):
    ct, nonce = crypto.encrypt(token.encode())
    return {
        "vault_ct": base64.b64encode(ct).decode(),
        "vault_nonce": base64.b64encode(nonce).decode(),
        "credkey": credkey,
        "vault_expires_at": (timezone.now() + expires_in).isoformat(),
    }


def _req(session_data):
    return SimpleNamespace(session=session_data)


class MintForTest(TestCase):
    def test_no_link_requires_relink(self):
        with self.assertRaises(FnalLinkRequired):
            mint_for(_req({}))

    def test_expired_token_requires_relink(self):
        req = _req({LINK_KEY: _link(expires_in=timedelta(days=-1))})
        with self.assertRaises(FnalLinkRequired):
            mint_for(req)

    def test_valid_token_mints_bearer(self):
        req = _req({LINK_KEY: _link()})
        with mock.patch(
            "hwdb.fnal.bearer.flow.mint_bearer", return_value="eyJ.bearer"
        ) as m:
            self.assertEqual(mint_for(req), "eyJ.bearer")
        m.assert_called_once_with("s.vault-token", "chaoz")

    def test_undecryptable_token_requires_relink(self):
        link = _link()
        link["vault_ct"] = base64.b64encode(b"garbage").decode()
        with self.assertRaises(FnalLinkRequired):
            mint_for(_req({LINK_KEY: link}))

    def test_vault_rejection_requires_relink(self):
        resp = requests.Response()
        resp.status_code = 403
        req = _req({LINK_KEY: _link()})
        with mock.patch(
            "hwdb.fnal.bearer.flow.mint_bearer",
            side_effect=requests.HTTPError(response=resp),
        ):
            with self.assertRaises(FnalLinkRequired):
                mint_for(req)

    def test_vault_5xx_is_unavailable(self):
        resp = requests.Response()
        resp.status_code = 503
        req = _req({LINK_KEY: _link()})
        with mock.patch(
            "hwdb.fnal.bearer.flow.mint_bearer",
            side_effect=requests.HTTPError(response=resp),
        ):
            with self.assertRaises(FnalUnavailable):
                mint_for(req)

    def test_connection_error_is_unavailable(self):
        req = _req({LINK_KEY: _link()})
        with mock.patch(
            "hwdb.fnal.bearer.flow.mint_bearer",
            side_effect=requests.ConnectionError("down"),
        ):
            with self.assertRaises(FnalUnavailable):
                mint_for(req)


class WithFnalBearerDecoratorTest(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user("guest", password="x")
        self.client.force_login(user)
        self.url = reverse("hwdb:subsystem_list")

    def test_no_link_redirects_to_link_with_next(self):
        with mock.patch("hwdb.views.mint_for", side_effect=FnalLinkRequired()):
            resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("hwdb:link"), resp["Location"])
        self.assertIn("next=", resp["Location"])

    def test_vault_unavailable_shows_error_page(self):
        with mock.patch("hwdb.views.mint_for", side_effect=FnalUnavailable()):
            resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "unavailable")

    def test_linked_user_gets_data(self):
        with mock.patch("hwdb.views.mint_for", return_value="bearer123"), mock.patch(
            "hwdb.api_client.FnalDbApiClient.get_subsystems",
            return_value={"data": []},
        ):
            resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "hwdb/subsystem_list.html")
