"""AES-GCM encryption for per-session FNAL vault tokens.

The vault token is stashed in the user's Django session, whose data is
stored server-side as plaintext in the ``django_session`` table. Encrypting
it with a key held *outside* the DB means a DB dump alone doesn't yield
usable 28-day FNAL credentials.

The key is HKDF-derived from ``settings.SECRET_KEY`` — no separate secret to
provision. Rotating ``SECRET_KEY`` changes the derived key, which makes
existing ciphertext undecryptable; that's fine here because vault tokens are
ephemeral (session-scoped, re-linked ~every 2 weeks) and a decrypt failure
already routes the user back through the link flow.

Ported from ``~/Code/dunecat/dunecat/hub/crypto.py``, shrunk to drop the
env/file/auto-generate key ladder.
"""

from __future__ import annotations

import secrets

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings

# Domain-separation label so this key is distinct from every other use of
# SECRET_KEY (sessions, signing, CSRF). Changing it invalidates ciphertext.
_HKDF_INFO = b"cets-hwdb-vault-token"


def _aesgcm() -> AESGCM:
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=_HKDF_INFO,
    ).derive(settings.SECRET_KEY.encode())
    return AESGCM(key)


def encrypt(plaintext: bytes) -> tuple[bytes, bytes]:
    """Return ``(ciphertext, nonce)``."""
    nonce = secrets.token_bytes(12)
    return _aesgcm().encrypt(nonce, plaintext, None), nonce


def decrypt(ciphertext: bytes, nonce: bytes) -> bytes:
    return _aesgcm().decrypt(nonce, ciphertext, None)
