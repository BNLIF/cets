"""Per-user OIDC device-flow driver against htvaultprod.fnal.gov.

Ported from ``~/Code/dunecat/dunecat/hub/auth/flow.py`` with ``ISSUER``
swapped to ``fermilab``. The protocol is byte-identical to dunecat's dune
flow; only the vault mount differs, and the mount is what makes the minted
bearer fermilab-issued (``iss: https://cilogon.org/fermilab``) — which is
what hwdb's server verifies against CILogon's JWKS.

Verified end-to-end by ``.idea/spike/vault_device_flow_fermilab.py`` against
live FNAL: ``credkey`` is the lowercase Fermilab services username,
``role=default`` works, and the resulting bearer is accepted by hwdb.

Split into composable halves:

- ``start()`` POSTs ``auth_url`` and returns the CILogon URL plus a
  serialisable ``poll_body`` to hand back to ``poll()`` later (stored in the
  Django session between requests).
- ``poll(poll_body)`` does one ``poll`` POST and classifies the result.
- ``complete(auth)`` extracts what the session needs from a successful poll.
- ``mint_bearer(vault_token, credkey)`` reads the secret path and returns the
  bearer JWT (called per-request, not at link time).

HTTP calls go through module-level ``_vault_post`` / ``_vault_get`` so tests
can monkey-patch them without a real network.
"""

from __future__ import annotations

import base64
import json
import secrets
from dataclasses import dataclass
from typing import Literal

import requests

VAULT = "https://htvaultprod.fnal.gov:8200"
ISSUER = "fermilab"
ROLE = "default"
OIDC_PATH = f"auth/oidc-{ISSUER}/oidc"
REDIRECT_URI = f"{VAULT}/v1/{OIDC_PATH}/callback"

_TIMEOUT = 10.0


# ----- HTTP boundary (patched in tests) ------------------------------------


def _vault_post(url: str, body: dict) -> requests.Response:
    return requests.post(url, json=body, timeout=_TIMEOUT)


def _vault_get(url: str, headers: dict, params: dict) -> requests.Response:
    return requests.get(url, headers=headers, params=params, timeout=_TIMEOUT)


# ----- Data shapes ---------------------------------------------------------


@dataclass(frozen=True)
class StartResult:
    auth_url: str
    user_code: str | None
    poll_body: dict  # opaque blob, post verbatim to /poll later


PollOutcome = Literal["pending", "slow_down", "complete"]


@dataclass(frozen=True)
class PollResult:
    outcome: PollOutcome
    auth: dict | None  # populated only when outcome == "complete"


@dataclass(frozen=True)
class LoginResult:
    """What a successful login yields for the session to persist."""

    vault_token: str
    vault_lease_seconds: int
    credkey: str  # vault metadata.credkey = lowercase Fermilab services username


# ----- Public driver -------------------------------------------------------


def start() -> StartResult:
    """Begin a device flow. Returns the auth URL plus a serialisable poll
    body to hand to ``poll()`` later."""
    nonce = secrets.token_urlsafe()
    body = {
        "role": ROLE,
        "client_nonce": nonce,
        "redirect_uri": REDIRECT_URI,
    }
    r = _vault_post(f"{VAULT}/v1/{OIDC_PATH}/auth_url", body)
    r.raise_for_status()
    data = r.json()["data"]
    auth_url = data.pop("auth_url")
    user_code = data.pop("user_code", None)
    if not auth_url:
        raise RuntimeError("vault returned empty auth_url")
    # Everything else (state, poll_interval, etc.) goes verbatim to /poll,
    # plus the client_nonce we generated.
    poll_body = {**data, "client_nonce": nonce}
    return StartResult(auth_url=auth_url, user_code=user_code, poll_body=poll_body)


def poll(poll_body: dict) -> PollResult:
    """Do one /poll request. Caller drives the loop."""
    r = _vault_post(f"{VAULT}/v1/{OIDC_PATH}/poll", poll_body)
    if r.status_code == 400:
        errs = (r.json() or {}).get("errors", [])
        if errs and errs[0] == "authorization_pending":
            return PollResult(outcome="pending", auth=None)
        if errs and errs[0] == "slow_down":
            return PollResult(outcome="slow_down", auth=None)
        raise RuntimeError(f"vault returned 400 with errors: {errs}")
    r.raise_for_status()
    return PollResult(outcome="complete", auth=r.json().get("auth"))


def complete(auth: dict) -> LoginResult:
    """Given vault's /poll success response, extract what the session needs."""
    vault_token = auth["client_token"]
    lease = int(auth.get("lease_duration", 0))
    metadata = auth.get("metadata") or {}
    credkey = metadata.get("credkey")
    if not credkey:
        raise RuntimeError(
            "vault response missing metadata.credkey; cannot identify user"
        )
    return LoginResult(
        vault_token=vault_token,
        vault_lease_seconds=lease,
        credkey=credkey,
    )


def mint_bearer(vault_token: str, credkey: str) -> str:
    """Read the secret path and return the bearer JWT."""
    path = f"secret/oauth/creds/{ISSUER}/{credkey}:{ROLE}"
    r = _vault_get(
        f"{VAULT}/v1/{path}",
        headers={"X-Vault-Token": vault_token},
        params={"minimum_seconds": 60},
    )
    r.raise_for_status()
    return r.json()["data"]["access_token"]


# ----- JWT helper ----------------------------------------------------------


def jwt_claims(token: str) -> dict:
    parts = token.split(".")
    if len(parts) != 3:
        raise RuntimeError("not a JWT (expected 3 dot-separated segments)")
    body = parts[1]
    body += "=" * (-len(body) % 4)
    return json.loads(base64.urlsafe_b64decode(body))
