# ADR-0002: Mint the HWDB bearer per request, don't cache it

- **Status:** Accepted
- **Date:** 2026-05-27
- **Issues:** #11

## Context

HWDB authenticates with a short-lived (~10h) bearer JWT. We hold the user's
longer-lived vault token in the session ([[0001-session-scoped-fnal-linkage]]);
the bearer is read from vault by exchanging that vault token. The question was
whether to cache the minted bearer (in the session, in memory) and reuse it
until expiry, or mint fresh each time.

A concern raised: would a bulk operation (e.g. uploading many QC records) mint
once per record?

## Decision

**Mint a fresh bearer per request, never cache it across requests**
(`hwdb/fnal/bearer.py`, `mint_for(request)`). Within a single request the caller
mints once and reuses the bearer for every HWDB call — so a bulk insert of N
records is **1 mint, N inserts**, not N mints.

Mint failures are classified into two surfaces:

- `FnalLinkRequired` — no token / expired / undecryptable / vault returns
  401/403. Re-linking fixes it.
- `FnalUnavailable` — vault unreachable or 5xx. Re-linking won't help.

The `@with_fnal_bearer` view decorator branches on these.

## Consequences

- No bearer-cache invalidation logic, no stale-bearer edge cases, nothing
  sensitive cached beyond the (encrypted) vault token.
- Each request that hits HWDB pays one extra vault round-trip (~50–150ms). For
  this app's request volume that is negligible; the bulk-upload worry is moot
  because minting is per-request, not per-record.
- If per-request mint latency ever matters, a within-process short-TTL cache can
  be added without changing the call sites (they already mint once per request).
