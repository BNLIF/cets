# ADR-0004: HWDB instance (prod/dev) is selectable per session

- **Status:** Accepted
- **Date:** 2026-05-27
- **Issues:** #16

## Context

The HWDB has two instances — production (`cdb`) and a dev sandbox (`cdbdev`) —
that differ only by a URL path segment and the part-type IDs (e.g. LArASIC is
`D08100100003` on prod, `D08100100001` on dev). We compare against **prod** by
default, but need to reach **dev** too — for browsing and, once upload lands, to
rehearse writes against the sandbox before touching prod. Switching by editing
env + restarting the server is too heavy and is global to all users.

## Decision

- A single env var **`HWDB_INSTANCE`** (default `prod`) sets the baseline,
  validated against **`HWDB_PROFILES`** — a map of `instance -> {api, ui,
  larasic_part_type}` in `settings.py`. An invalid value raises
  `ImproperlyConfigured` at startup.
- A user can **override the instance for their own session** via the toggle on
  the HWDB landing (`hwdb/instance.py`, `SESSION_KEY = "hwdb_instance"`). No
  restart, no effect on other users. `active_instance` / `active_profile`
  resolve the override-or-default per request; views read the profile rather
  than the module-level `HWDB_*` constants.

## Consequences

- Reaching dev is a one-click, per-session action; prod stays the safe default.
- Because the active profile is resolved per request, this is the natural switch
  for "write to dev vs prod" once upload lands — the decision is deliberately
  per-session for that reason.
- `is_in_hwdb` is intentionally **not** subject to the toggle — it stays
  prod-scoped ([[0003-prod-scoped-is-in-hwdb-flag]]).
- The settings-level `HWDB_API_BASE_URL` etc. remain as the baseline default;
  any new request-time code must go through `active_profile`, not those
  constants, or it will ignore the session override.
