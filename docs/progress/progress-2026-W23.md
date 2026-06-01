# Progress Report — Week 23, 2026

**Period:** 2026-05-25 → 2026-05-31

## Executive Summary

The big shift this week: HWDB went from read-only to a full bidirectional
integration. We shipped FNAL device-flow auth, the LArASIC sync flag, the
component-type landing pages, and Phase-3 upload — first single-chip, then
per-tray batches, then a 10-worker parallel path that cut 5-hour uploads to
roughly 30 minutes. 13 GitHub issues closed across 30 commits; **+6520 /
−865 lines** across 75 files. The week ended with a UI consolidation pass
(chip-family grouping, theme refresh, 1-year LArASIC projection) and a
local-only CSV-attach tracking model so re-uploads remain detectable when
new CSVs land for already-done trays.

## What Was Built

### Phase 1 — FNAL auth & per-user bearers

| Issue | Deliverable |
|---|---|
| #9  | FNAL auth foundation: HKDF crypto + vault device-flow driver |
| #10 | `/hwdb/link/` stores the FNAL vault token in the session |
| #11 | HWDB views mint per-user bearers; shared `bt_u502` retired |

**Result:** every HWDB request now carries the caller's own bearer minted
from a session-scoped vault link. No shared service account. Logout
destroys the linkage. (See ADR-0001, ADR-0002.)

### Phase 2 — HWDB section shell & sync

| Issue | Deliverable |
|---|---|
| #13 | HWDB section shell, nav tab, component-type landing, dashboard-style cards |
| #14 | LArASIC HWDB sync — `is_in_hwdb` flag, Sync action, count cards |
| #15 | "in HWDB" badge on the core LArASIC list/detail pages |
| #16 | HWDB instance config — dev/prod toggle, prod default, per-session switch |

**Result:** operators see at a glance how many chips are in HWDB vs not, and
the prod/dev switch makes the active instance visually obvious (amber for
prod, sky for dev) without contaminating local state — `is_in_hwdb` is
prod-scoped (ADR-0003); dev syncs are a no-op (ADR-0004).

### Phase 3 — HWDB upload (LArASIC end-to-end)

| Issue | Deliverable |
|---|---|
| #17 | HWDB upload-API probe bundle (location-on-create, PATCH-test, dup-test) |
| #18 | Pure-function upload library: LArASIC create / test / attach |
| #19 | Single-chip upload UI + streaming endpoint (DEV-only initially) |
| #20 | Per-tray batch upload + tray index page |
| #21 | PROD gauntlet (type-to-confirm modal → later simplified) + go-live |
| #22 | Parallel path: 10-worker thread pool, `requests.Session` reuse |

**Result:** a tray of ~100 chips uploads in roughly 4–5 minutes on the
parallel path with a live progress panel, down from ~25 minutes on the
serial path. Detailed records carry CSVs; simple records carry summary
fields. Shape-aware dedup (ADR-0006) recognises which mode an existing
record is in and either upgrades it or skips it.

### Beyond the tracker

These shipped without a GitHub issue — UX consolidation and follow-on fixes
discovered while operating Phase-3 against real data:

- **Chip-family grouping pages** — `/larasic/`, `/coldadc/`, `/coldata/`
  collapsed under a Tray/FEMB toggle; `/femb/` gained qc/chk counts and a
  combined version+serial column. Search inputs moved outside HTMX swap
  regions to preserve focus across typing.
- **Sky · Daylight theme refresh** — replaced the older palette, reskinned
  dashboard chart, fam-stat cards, top-pager, action bar.
- **1-year LArASIC projection** — dashboard chart extends 12 months forward
  using last-90-day daily rate, with dashed line + lower-opacity bars to
  mark the projection segment.
- **Top-nav user menu** — replaced direct admin link with a click-outside
  dropdown showing username/email, FNAL credkey (if linked), Django admin
  (staff only), Log out (POST → redirect to login with `next=/`).
- **Local-only CSV-attach tracking** — `warm_csv_attached_at` /
  `cold_csv_attached_at` on LArASIC, stamped only by our own successful
  attaches; merged `/hwdb/larasic/` derives "needs re-upload" purely from
  local DB + TrayCsvCache (no trust in HWDB's `qaqc_uploaded`).
- **SCRIPT_NAME-aware breadcrumbs** for the twister deployment under
  `/twister/cets/`.
- **Per-instance `manufacturer_id`** — prod=15 (TSMC), dev=59; split via the
  `HWDB_PROFILES` dict.
- **Simpler PROD gauntlet** — replaced type-to-confirm modal with a
  prominent warning + plain "Confirm upload" button.

## Architecture Overview

```
                ┌─────────────────────────────────────────┐
                │  Browser (HTMX-driven Django templates) │
                │  /larasic/ /coldadc/ /coldata/ /femb/   │
                │  /cable/ /hwdb/ /hwdb/larasic/          │
                └────────────────┬────────────────────────┘
                                 │
                ┌────────────────▼────────────────────┐
                │  Django 5.2 (cets/ project)         │
                │  ┌──────────┐  ┌──────────────────┐ │
                │  │  core/   │  │     hwdb/        │ │
                │  │  models  │  │   views, upload  │ │
                │  │  views   │  │   library, sync  │ │
                │  │  ORM     │  │   fnal/ vault    │ │
                │  └─────┬────┘  └────────┬─────────┘ │
                └────────┼────────────────┼───────────┘
                         │                │
                         ▼                ▼
              ┌─────────────────┐   ┌──────────────────────┐
              │  PostgreSQL     │   │  HWDB (cdb / cdbdev) │
              │  (chips, FEMB,  │   │  REST API + FNAL     │
              │   cables,       │   │  vault device flow   │
              │   TrayCsvCache) │   └──────────────────────┘
              └─────────┬───────┘
                        │
                        ▼
              ┌─────────────────────┐
              │  RTS_DIR on disk    │
              │  (CSV results +     │
              │  RT_FE_/LN_FE_)     │
              └─────────────────────┘
```

Upload path is parallel by default (`hwdb/upload/larasic.py`,
`ThreadPoolExecutor(max_workers=10)`); each worker shares a per-request
`requests.Session` for connection reuse. The streaming endpoint
(`/hwdb/larasic/upload/<tray>/`) emits line-buffered progress to the floating
panel; the post-stream step bulk-stamps `is_in_hwdb`, `qc_tests_uploaded`,
and `*_csv_attached_at` in a single ORM update.

## Key Technical Decisions

### Per-user bearers from a session-scoped FNAL link (ADR-0001, 0002)

**Decision:** every HWDB request mints a fresh bearer from the user's vault
token; tokens are stored encrypted in the Django session and discarded on
logout.

**Why it matters:** removes the shared `bt_u502` blast radius — every write
in HWDB now traces to a human caller.

**Concrete benefit:** when an upload posts wrong data, HWDB's audit log
names the person, not the deployment.

### Prod-scoped `is_in_hwdb`; dev syncs are no-ops (ADR-0003, 0004)

**Decision:** the local `is_in_hwdb` flag means *"this serial exists in
production HWDB."* A dev-instance sync never touches it.

**Why it matters:** prevents the dev playground from polluting the operator
view that drives daily upload decisions.

**Concrete benefit:** operators can mirror the production catalog into dev
to test the upload path without ever desynchronizing the production count
cards.

### Parallel upload with explicit worker cap (ADR-0005)

**Decision:** 10-worker `ThreadPoolExecutor`, one `requests.Session` per
worker, no retries on 4xx, single retry on 5xx with a 1s backoff.

**Why it matters:** the HWDB API is single-tenant and we are sharing it
with other sites; 10 workers is "fast enough" without flooding.

**Concrete benefit:** a 100-chip tray uploads in ~4 minutes; the 12k-chip
backlog moves from 5 hours to ~30 minutes wall-clock.

### Shape-aware test dedup (ADR-0006)

**Decision:** identify a "detailed" QC record by `"CH0 Pedestal" in
test_data`. A simple existing record + a detailed candidate is treated as
an upgrade (post both). Detailed-vs-detailed is a dedup match unless the
operator turns on Force CSV attach.

**Why it matters:** HWDB exposes no shape field and tests are not
PATCHable; without this rule we either duplicate detailed records on every
re-run or never upgrade simple records.

**Concrete benefit:** re-running an upload after CSVs arrive promotes the
simple records to detailed without operator gymnastics, and clean re-runs
are idempotent.

### Local-only CSV-attach tracking

**Decision:** stamp `warm_csv_attached_at` / `cold_csv_attached_at` only
when our own upload code successfully attaches a CSV. Never derive
"attached" from HWDB's `qaqc_uploaded` flag.

**Why it matters:** other site operators can flip `qaqc_uploaded` in HWDB
by hand; trusting it gives false-positive "done" indicators on the merged
upload page.

**Concrete benefit:** when new CSVs arrive for an already-uploaded tray,
the merged page surfaces them as work-to-do as soon as the operator
refreshes the CSV cache — no HWDB round-trip, no flag-flip race.

### Per-session HWDB instance switch (ADR-0004)

**Decision:** dev/prod is a per-session preference, not a per-deployment
config. Each user picks their instance; views read `request.session["hwdb_instance"]`.

**Why it matters:** dev exploration and prod uploads happen on the same
deployment without redeploys or env-flag flips.

**Concrete benefit:** the same operator can mint test data in dev, then
flip to prod with one click for the real run, and the UI's amber/sky
coloring makes the active instance unmistakable.

## Metrics

| Metric | Count |
|---|--:|
| Issues closed | 13 |
| Commits | 30 |
| Files changed | 75 |
| Lines added | +6,520 |
| Lines removed | −865 |
| Python files in repo | 77 |
| Templates (.html) | 38 |
| ADRs (total / new this week) | 6 / 6 |
| Upload speed-up (parallel vs serial) | ~5× |

## Current System Capabilities

1. **Track** LArASIC, ColdADC, COLDATA, FEMB, and cable inventory with
   tray/FEMB grouping and qc/chk test counts on every list view.
2. **Mirror** HWDB membership locally with a per-tray `In HWDB` count and
   a prod-only Sync action.
3. **Authenticate** to HWDB via FNAL device-flow vault links; each user
   acts under their own bearer.
4. **Switch** HWDB instance (prod/dev) per session with visually
   unmistakable coloring.
5. **Upload** LArASIC chips to HWDB on a per-tray basis with either simple
   or detailed (CSV-bearing) records, in a parallel 10-worker pool with
   a live progress panel.
6. **Detect re-upload work** when new CSV files arrive for already-uploaded
   trays, using local-only tracking that is robust to external edits of
   HWDB's `qaqc_uploaded` flag.
7. **Project** future LArASIC delivery cadence one year out on the
   dashboard, based on the last-90-day daily rate.
8. **Serve** the same Django app at the bare `/` host and under
   `FORCE_SCRIPT_NAME=/twister/cets` with SCRIPT_NAME-aware breadcrumbs.

## Open / Next

- **Twister rollout** of the local CSV-attach tracking — pull, migrate,
  `refresh_csv_cache`, `backfill_csv_attached --apply`, restart.
- **Periodic CSV-cache refresh** — currently manual; a nightly cron or
  inotify-driven scan would close the "CSVs landed but page hasn't
  noticed" window.
- **HWDB bulk-upload investigation** — verify with the DUNE-HWDB-Python
  reference whether a true batch endpoint exists that could replace the
  per-chip POST + per-test POST + per-image POST sequence. If yes, that's
  another order-of-magnitude speed-up candidate.
- **ColdADC / COLDATA HWDB integration** — only LArASIC has the
  sync+upload path today; ColdADC and COLDATA list pages exist but no
  HWDB equivalents under `/hwdb/`.
- **RTS session validity rule (ADR-0004) coverage** — only enforced for
  RT_FE_/LN_FE_ folder presence; consider extending to additional
  per-session markers as Karla flags edge cases.
