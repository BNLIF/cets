"""Where the FNAL linkage lives: the user's Django session.

Session-scoped, not per-User — cets has a shared ``guest`` login used by
several people with different FNAL identities, so a per-User row would let
concurrent guests mint bearers as each other. Each browser session holds its
own encrypted vault token instead. No model, no migration.

Two keys:
- ``FLOW_KEY``  — the in-progress device flow (poll_body + expiry + next),
  present only between starting a link and completing it.
- ``LINK_KEY``  — the completed link: the encrypted vault token, credkey, and
  vault-token expiry. Read per-request by ``bearer.mint_for`` (issue #11).

Binary ciphertext/nonce are base64'd because the session uses the JSON
serializer.
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta

from django.utils import timezone

from . import crypto, flow

FLOW_KEY = "fnal_link_flow"
LINK_KEY = "fnal_link"


def set_flow(
    request, poll_body: dict, expires_at, next_url: str, login_user: bool = False,
    auth_url: str = "", user_code: str | None = None,
) -> None:
    """Stash an in-progress device flow.

    ``login_user`` is the intent flag (ADR-0011): an explore-started flow sets
    it so completion provisions + logs in a Django user, while the CE "Link
    FNAL" flow leaves it ``False`` and stays link-only. The default keeps every
    existing (CE) caller byte-for-byte unchanged. ``auth_url``/``user_code``
    let ``resume_flow`` re-render the same CILogon button later.
    """
    request.session[FLOW_KEY] = {
        "poll_body": poll_body,
        "expires_at": expires_at.isoformat(),
        "next": next_url,
        "login_user": login_user,
        "auth_url": auth_url,
        "user_code": user_code,
    }


def resume_flow(request, next_url: str, login_user: bool = False):
    """The in-progress flow's ``(auth_url, user_code)`` when one is still
    running with the same intent — else None. Several requests landing on the
    link page at once (a bounced page plus its panels, two tabs) must share
    ONE flow: starting a new one per visit overwrote the flow the user was
    completing in CILogon, and the page then polled a flow nobody finished
    (prod, 2026-09-04). ``next`` follows the latest request."""
    state = request.session.get(FLOW_KEY)
    if not state or not state.get("auth_url") or bool(state.get("login_user")) != login_user:
        return None
    if datetime.fromisoformat(state["expires_at"]) <= timezone.now():
        return None
    state["next"] = next_url
    request.session[FLOW_KEY] = state
    return state["auth_url"], state.get("user_code")


def get_flow(request) -> dict | None:
    return request.session.get(FLOW_KEY)


def clear_flow(request) -> None:
    request.session.pop(FLOW_KEY, None)


def store_link(request, login: flow.LoginResult) -> None:
    """Encrypt the vault token and persist the completed link in the session."""
    ciphertext, nonce = crypto.encrypt(login.vault_token.encode())
    expires_at = timezone.now() + timedelta(seconds=login.vault_lease_seconds)
    request.session[LINK_KEY] = {
        "vault_ct": base64.b64encode(ciphertext).decode(),
        "vault_nonce": base64.b64encode(nonce).decode(),
        "credkey": login.credkey,
        "vault_expires_at": expires_at.isoformat(),
    }
