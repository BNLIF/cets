# ADR-0001: Session-scoped FNAL linkage, encrypted with a SECRET_KEY-derived key

- **Status:** Accepted
- **Date:** 2026-05-27
- **Issues:** #9, #10, #11

## Context

To talk to the DUNE HWDB on a user's behalf we need that user's Fermilab
credentials. cets runs with a **shared `guest` Django login** used by several
people who each have a *different* FNAL identity. So FNAL identity cannot hang
off the Django `User`.

We obtain a vault token via an OIDC device flow (see [[0002-per-request-bearer-minting]]).
That token is a ~2-week FNAL credential and has to be stored somewhere between
requests. Django sessions are DB-backed, stored as **plaintext** in the
`django_session` table.

## Decision

1. **Store the FNAL linkage in the Django session, not on a model.** Each
   browser session holds its own vault token under `LINK_KEY` (`hwdb/fnal/session.py`).
   No table, no migration. The linkage lives and dies with the session.

2. **Encrypt the vault token at rest with AES-GCM, using a key HKDF-derived
   from `settings.SECRET_KEY`** (`hwdb/fnal/crypto.py`, HKDF info
   `b"cets-hwdb-vault-token"` for domain separation). No new secret to
   provision.

## Consequences

- Two concurrent guests can never mint bearers as each other — a per-`User` row
  would have allowed exactly that.
- A DB dump alone does not yield usable FNAL credentials; the decrypt key is
  held outside the DB.
- Rotating `SECRET_KEY` makes existing ciphertext undecryptable. Acceptable:
  vault tokens are ephemeral and a decrypt failure routes the user back through
  the link flow ([[0002-per-request-bearer-minting]] maps it to `FnalLinkRequired`).
- Linkage is lost when the session expires (~2 weeks), so users re-link
  periodically. This is intended, not a bug.
