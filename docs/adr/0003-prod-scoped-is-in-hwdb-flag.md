# ADR-0003: `is_in_hwdb` is scoped to the production HWDB only

- **Status:** Accepted
- **Date:** 2026-05-27
- **Issues:** #14

## Context

HWDB may hold far fewer LArASIC chips than the ~12k cets tracks locally. To
avoid re-querying chips already known to be in HWDB on every sync, we cache a
per-chip boolean `is_in_hwdb` (plus `hwdb_checked_at`) on the `LArASIC` model.

But there are **two HWDB instances** — `prod` and `dev` — and a user can sync
against either ([[0004-per-session-instance-toggle]]). A naive flag would mean a
sync against `dev` overwrites what a sync against `prod` established, and vice
versa, making the flag meaningless.

## Decision

**`is_in_hwdb` reflects the production HWDB only.** The sync that writes the flag
(`hwdb.views._sync_larasic` / `larasic_sync_view`) is **guarded to run against
`prod`**; syncing while toggled to `dev` is disallowed for the purpose of
setting the flag. The HWDB-only count is persisted in the `LarasicSyncState`
singleton (`hwdb/models.py`), since HWDB-only serials have no local row to hang
a flag on.

## Consequences

- The flag has a single, stable meaning ("exists in production HWDB") regardless
  of which instance the user is browsing.
- `dev` remains fully usable for browsing/comparison and (future) upload
  rehearsal, but cannot pollute the prod-scoped flag.
- If we ever need per-instance membership tracking, this flag does not generalize
  — a second dev-scoped flag or an instance-keyed table would be required. Not
  needed today.
