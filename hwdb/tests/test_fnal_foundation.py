"""Unit tests for the FNAL auth foundation (issue #9).

No live FNAL calls — the vault HTTP boundary (``flow._vault_post`` /
``flow._vault_get``) is monkey-patched. Run with::

    python manage.py test hwdb
"""

from __future__ import annotations

import base64
import json
from unittest import mock

import requests
from django.test import SimpleTestCase

from hwdb.fnal import bearer, crypto, flow


class FakeResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class CryptoRoundTripTest(SimpleTestCase):
    def test_encrypt_decrypt_round_trip(self):
        plaintext = b"s.vault-token-abc123"
        ct, nonce = crypto.encrypt(plaintext)
        self.assertNotEqual(ct, plaintext)
        self.assertEqual(crypto.decrypt(ct, nonce), plaintext)

    def test_nonce_differs_per_call(self):
        _, n1 = crypto.encrypt(b"x")
        _, n2 = crypto.encrypt(b"x")
        self.assertNotEqual(n1, n2)

    def test_tampered_ciphertext_fails(self):
        ct, nonce = crypto.encrypt(b"hello")
        with self.assertRaises(Exception):
            crypto.decrypt(ct + b"\x00", nonce)


class FlowStartTest(SimpleTestCase):
    def test_start_returns_auth_url_and_poll_body(self):
        resp = FakeResponse(
            200,
            {
                "data": {
                    "auth_url": "https://cilogon.org/device/?user_code=ABC-DEF",
                    "user_code": "ABC-DEF",
                    "state": "state-xyz",
                    "poll_interval": 5,
                }
            },
        )
        with mock.patch.object(flow, "_vault_post", return_value=resp) as post:
            result = flow.start()

        # auth_url POST hit the fermilab mount.
        called_url = post.call_args.args[0]
        self.assertIn("auth/oidc-fermilab/oidc/auth_url", called_url)

        self.assertEqual(result.auth_url, "https://cilogon.org/device/?user_code=ABC-DEF")
        self.assertEqual(result.user_code, "ABC-DEF")
        # poll_body carries the leftover fields + the generated client_nonce,
        # and does NOT carry auth_url/user_code.
        self.assertEqual(result.poll_body["state"], "state-xyz")
        self.assertIn("client_nonce", result.poll_body)
        self.assertNotIn("auth_url", result.poll_body)
        self.assertNotIn("user_code", result.poll_body)

    def test_start_raises_on_empty_auth_url(self):
        resp = FakeResponse(200, {"data": {"auth_url": "", "user_code": None}})
        with mock.patch.object(flow, "_vault_post", return_value=resp):
            with self.assertRaises(RuntimeError):
                flow.start()


class FlowPollTest(SimpleTestCase):
    def _poll(self, resp):
        with mock.patch.object(flow, "_vault_post", return_value=resp):
            return flow.poll({"client_nonce": "n"})

    def test_pending(self):
        r = self._poll(FakeResponse(400, {"errors": ["authorization_pending"]}))
        self.assertEqual(r.outcome, "pending")
        self.assertIsNone(r.auth)

    def test_slow_down(self):
        r = self._poll(FakeResponse(400, {"errors": ["slow_down"]}))
        self.assertEqual(r.outcome, "slow_down")

    def test_complete(self):
        auth = {"client_token": "s.tok", "metadata": {"credkey": "chaoz"}}
        r = self._poll(FakeResponse(200, {"auth": auth}))
        self.assertEqual(r.outcome, "complete")
        self.assertEqual(r.auth, auth)

    def test_other_400_raises(self):
        with self.assertRaises(RuntimeError):
            self._poll(FakeResponse(400, {"errors": ["invalid_request"]}))


class FlowCompleteTest(SimpleTestCase):
    def test_extracts_session_fields(self):
        auth = {
            "client_token": "s.vault-token",
            "lease_duration": 2419200,
            "metadata": {"credkey": "chaoz", "oauth2_refresh_token": "rt.secret"},
        }
        result = flow.complete(auth)
        self.assertEqual(result.vault_token, "s.vault-token")
        self.assertEqual(result.vault_lease_seconds, 2419200)
        self.assertEqual(result.credkey, "chaoz")
        self.assertEqual(result.refresh_token, "rt.secret")

    def test_refresh_token_optional(self):
        result = flow.complete({"client_token": "s.tok", "metadata": {"credkey": "chaoz"}})
        self.assertIsNone(result.refresh_token)

    def test_missing_credkey_raises(self):
        with self.assertRaises(RuntimeError):
            flow.complete({"client_token": "s.tok", "metadata": {}})


class StoreRefreshTokenTest(SimpleTestCase):
    def test_posts_refresh_token_to_creds_path(self):
        resp = FakeResponse(204, {})
        with mock.patch.object(flow, "_vault_post", return_value=resp) as post:
            flow.store_refresh_token("s.vault-token", "yubo", "rt.secret")

        url, body = post.call_args.args
        self.assertIn("secret/oauth/creds/fermilab/yubo:default", url)
        self.assertEqual(body, {"server": "fermilab", "refresh_token": "rt.secret"})
        self.assertEqual(post.call_args.kwargs["headers"], {"X-Vault-Token": "s.vault-token"})

    def test_rejected_write_raises(self):
        with mock.patch.object(flow, "_vault_post", return_value=FakeResponse(403, {})):
            with self.assertRaises(requests.HTTPError):
                flow.store_refresh_token("s.vault-token", "yubo", "rt.secret")


class VerifyLinkTest(SimpleTestCase):
    """The link must create the creds path before minting; six prod users
    404'd when it did not (2026-09-09)."""

    def _login(self, refresh_token="rt.secret"):
        return flow.LoginResult(
            vault_token="s.vault-token", vault_lease_seconds=100,
            credkey="yubo", refresh_token=refresh_token,
        )

    def test_stores_refresh_token_then_mints(self):
        calls = []
        with mock.patch.object(flow, "store_refresh_token", side_effect=lambda *a: calls.append(("store", a))), \
             mock.patch.object(flow, "mint_bearer", side_effect=lambda *a: calls.append(("mint", a)) or "jwt"):
            self.assertIsNone(bearer.verify_link(self._login()))
        self.assertEqual(calls, [
            ("store", ("s.vault-token", "yubo", "rt.secret")),
            ("mint", ("s.vault-token", "yubo")),
        ])

    def test_no_refresh_token_still_mints(self):
        with mock.patch.object(flow, "store_refresh_token") as store, \
             mock.patch.object(flow, "mint_bearer", return_value="jwt"):
            self.assertIsNone(bearer.verify_link(self._login(refresh_token=None)))
        store.assert_not_called()

    def test_mint_404_returns_message(self):
        err = requests.HTTPError(response=mock.Mock(status_code=404))
        with mock.patch.object(flow, "store_refresh_token"), \
             mock.patch.object(flow, "mint_bearer", side_effect=err):
            msg = bearer.verify_link(self._login())
        self.assertIn("yubo", msg)
        self.assertIn("404", msg)


class MintBearerTest(SimpleTestCase):
    def test_reads_secret_path_and_returns_bearer(self):
        resp = FakeResponse(200, {"data": {"access_token": "eyJ.bearer.jwt"}})
        with mock.patch.object(flow, "_vault_get", return_value=resp) as get:
            bearer = flow.mint_bearer("s.vault-token", "chaoz")

        url = get.call_args.args[0]
        self.assertIn("secret/oauth/creds/fermilab/chaoz:default", url)
        self.assertEqual(
            get.call_args.kwargs["headers"]["X-Vault-Token"], "s.vault-token"
        )
        self.assertEqual(bearer, "eyJ.bearer.jwt")


class JwtClaimsTest(SimpleTestCase):
    def test_decodes_body(self):
        body = base64.urlsafe_b64encode(
            json.dumps({"iss": "https://cilogon.org/fermilab"}).encode()
        ).rstrip(b"=").decode()
        token = f"header.{body}.sig"
        claims = flow.jwt_claims(token)
        self.assertEqual(claims["iss"], "https://cilogon.org/fermilab")

    def test_non_jwt_raises(self):
        with self.assertRaises(RuntimeError):
            flow.jwt_claims("not-a-jwt")
