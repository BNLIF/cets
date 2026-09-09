"""Per-request bearer minting from the session's vault token (issue #11).

We don't cache bearers: each request that talks to hwdb mints a fresh
~10h bearer from the user's encrypted vault token in the session. Mint cost
is one HTTPS round-trip to vault (~50-150ms); within a request the caller
mints once and reuses the bearer for every hwdb call (so a bulk insert of N
records is 1 mint, N inserts).

Two failure modes, mapped to the Q9 surface by the @with_fnal_bearer
decorator:
- ``FnalLinkRequired`` — no token, expired, undecryptable, or rejected by
  vault (401/403, or 404 = creds path gone). Re-linking fixes it.
- ``FnalUnavailable`` — vault unreachable / transient. Re-linking won't help.
"""

from __future__ import annotations

import base64
import logging
from datetime import datetime

import requests
from django.utils import timezone

from . import crypto, flow
from .session import LINK_KEY

logger = logging.getLogger(__name__)


class FnalLinkRequired(Exception):
    """The session has no usable vault token; the user must (re)link."""


class FnalUnavailable(Exception):
    """Vault/mint failed transiently; re-linking won't help."""


def mint_for(request) -> str:
    """Decrypt the session vault token and mint a fresh bearer."""
    data = request.session.get(LINK_KEY)
    if not data:
        raise FnalLinkRequired("no FNAL link in session")
    if datetime.fromisoformat(data["vault_expires_at"]) <= timezone.now():
        raise FnalLinkRequired("vault token expired")

    try:
        vault_token = crypto.decrypt(
            base64.b64decode(data["vault_ct"]),
            base64.b64decode(data["vault_nonce"]),
        ).decode()
    except Exception as e:
        logger.warning("FNAL vault token decrypt failed: %s", e)
        raise FnalLinkRequired("vault token unreadable")

    try:
        return flow.mint_bearer(vault_token, data["credkey"])
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else None
        # 404 = the vault creds path is gone (htvault expired/cleaned the
        # stored OIDC credentials) — the vault token may still look valid,
        # but only re-linking recreates the creds (seen on prod 2026-09-01).
        if status in (401, 403, 404):
            logger.warning("FNAL bearer mint rejected (%s) for credkey %s at %s; relink",
                           status, data["credkey"], flow.creds_path(data["credkey"]))
            raise FnalLinkRequired("vault token rejected")
        logger.warning("FNAL bearer mint failed (HTTP %s)", status)
        raise FnalUnavailable("could not mint bearer")
    except Exception as e:
        logger.warning("FNAL bearer mint error: %s", e)
        raise FnalUnavailable("could not mint bearer")


def verify_link(login) -> str | None:
    """Store the refresh token, then mint once, right after a device flow
    completes. The store is what creates the vault creds path (2026-09-09:
    six prod users 404'd because we skipped it — only accounts that had run
    htgettoken themselves had a path). A 401/403/404 on the mint means vault
    still holds no HWDB token for this account — storing the link would only
    bounce the user between the page and the re-link screen forever, so the
    caller shows this message instead. Transient trouble returns None: the
    link is stored and the pages report it as they do today."""
    try:
        if login.refresh_token:
            flow.store_refresh_token(login.vault_token, login.credkey, login.refresh_token)
        else:
            logger.warning("FNAL poll for credkey %s carried no oauth2_refresh_token", login.credkey)
        flow.mint_bearer(login.vault_token, login.credkey)
        return None
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else None
        if status in (401, 403, 404):
            logger.warning("FNAL link for credkey %s completed but vault has no HWDB token "
                           "(%s at %s)", login.credkey, status, flow.creds_path(login.credkey))
            return (f"Fermilab login succeeded for {login.credkey}, but the hardware database "
                    f"has no access token for that account (vault answered {status}). "
                    f"Ask the HWDB administrators to enable {login.credkey} for the FNAL token service.")
        logger.warning("FNAL verify-link mint failed (HTTP %s) for %s", status, login.credkey)
    except Exception as e:
        logger.warning("FNAL verify-link mint error for %s: %s", login.credkey, e)
    return None
