"""Per-request bearer minting from the session's vault token (issue #11).

We don't cache bearers: each request that talks to hwdb mints a fresh
~10h bearer from the user's encrypted vault token in the session. Mint cost
is one HTTPS round-trip to vault (~50-150ms); within a request the caller
mints once and reuses the bearer for every hwdb call (so a bulk insert of N
records is 1 mint, N inserts).

Two failure modes, mapped to the Q9 surface by the @with_fnal_bearer
decorator:
- ``FnalLinkRequired`` — no token, expired, undecryptable, or rejected by
  vault (401/403). Re-linking fixes it.
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
        if status in (401, 403):
            logger.warning("FNAL bearer mint rejected (%s); relink", status)
            raise FnalLinkRequired("vault token rejected")
        logger.warning("FNAL bearer mint failed (HTTP %s)", status)
        raise FnalUnavailable("could not mint bearer")
    except Exception as e:
        logger.warning("FNAL bearer mint error: %s", e)
        raise FnalUnavailable("could not mint bearer")
