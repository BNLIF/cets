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

from hwdb.fnal import crypto, flow


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
            "metadata": {"credkey": "chaoz"},
        }
        result = flow.complete(auth)
        self.assertEqual(result.vault_token, "s.vault-token")
        self.assertEqual(result.vault_lease_seconds, 2419200)
        self.assertEqual(result.credkey, "chaoz")

    def test_missing_credkey_raises(self):
        with self.assertRaises(RuntimeError):
            flow.complete({"client_token": "s.tok", "metadata": {}})


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
