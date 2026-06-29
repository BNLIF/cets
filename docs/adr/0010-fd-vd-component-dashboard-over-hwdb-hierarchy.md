# Read-only FD-VD component dashboard over a locally-mirrored HWDB hierarchy

status: accepted

To extend the dashboard beyond cold electronics, we add a **read-only**,
navigation-first view of the full FD-VD component hierarchy. The hierarchy is
the one already live in production HWDB (`systems/D` → `subsystems/D/{sys}` →
`component-types/D/{sys}/{subsys}` → `components` → `tests`); we mirror it into
**new, dedicated local tables** and render per-component-type "tests recorded
per month" plots. Everything here is **purely additive** — it must not change
any existing model, table, view, URL, or the CE QC/upload pipeline.

## Context

The current app tracks only cold electronics (FEMB + LArASIC/ColdADC/COLDATA),
which is 3 of the 14 subsystems of just one HWDB system (`FD CE`, id 81). A
spike (2026-06-26) confirmed the FD-VD hierarchy is fully populated in
production HWDB and walkable via the API, and that every test record — across
every consortium — shares a uniform summary shape: `created` (HWDB record
timestamp) + `test_type {id, name}`, with no `test_data` payload at the list
level. So generic count-plots need zero per-consortium logic.

## Decision

- **Source of truth: live prod HWDB, mirrored locally.** Navigation and plots
  read from local mirror tables, never live per-click. Generalizes the mirror
  philosophy of [[0007-hwdb-mirror-separation]].
- **New tables only.** `ComponentTypeNode` (skeleton: project/system/subsystem
  ids + names, `part_type_id`, component count, sync state) and `HwdbTestEvent`
  (`part_type_id`, `part_id`, `test_type_name`, `created`). Plots aggregate
  these on the fly (`GROUP BY` month, test_type). The existing `HwdbChip`
  mirror is left untouched — it stores a *different* metric (each chip's latest
  RT/LN date → "chips reaching tested-state per month"), whereas this stores
  raw test events → "tests recorded per month".
- **Plot date = physics `Test Date` where a component type provides one, else
  HWDB `created`.** A `physics_date_field(part_type_id)` resolver registry maps
  component types to their datasheet date field; only the CE chip families are
  mapped today (→ `test_data["Test Date"]`, via the detailed
  `…/tests/{type_id}` endpoint, reusing the dashboard's parser), everyone else
  falls back to the uniform `created` upload stamp. Extends
  [[0009-hwdb-mirror-test-timestamp-fallback]]. **Update (issue #30 follow-up):**
  originally `created`-only; switched after the LArASIC plot was found to
  bunch on the bulk-upload date (2026-05-29) instead of the real Dec-2025/
  Jan-2026 test dates. Cost: the physics path fetches one detailed call per
  defined test type per component (vs one summary call), so CE syncs are
  heavier; non-CE types are unchanged.
- **Component inventory chart uses `updated`, not `created`.** A second chart
  ("Components updated per month") bins each component by its HWDB last-modified
  date (status change / QC upload bumps it) — a better activity signal than the
  mint date. Requires a per-component detail fetch (the listing lacks
  `updated`).
- **Test-type facets read dynamically** from `test_type.name` — no hard-coded
  consortium knowledge (TDE's `amc_bandwidth_test` and CE's `RoomT QC Test`
  are just legend labels).
- **Navigation: sidebar folder-tree, master-detail**, served from the mirror,
  at a new URL `/hwdb/explore/`. Per-node component-count badges; a leaf gains
  a "has test data" accent only after its plot-sync runs.
- **Scope (v1): a curated FD-VD whitelist** — systems named `FD-VD *` plus
  `FD CE`. Other shared `FD *` systems (DAQ, Slow Control, Cryostat, …) are
  excluded for now; adding one is a whitelist edit.
- **Sync: skeleton eager, plot data lazy + incremental.** A `sync_hierarchy`
  command (+ button) populates `ComponentTypeNode` for the whitelist;
  per-component-type events sync on first visit to that leaf and cache,
  FNAL-gated, reusing the streaming-sync UX. Three cost-tiered modes mirror the
  dashboard's skip-known policy ([[0008-skip-known-serials-incremental-sync]]):
  `incremental` (new components only — default), `components` (re-fetch detail
  for all to refresh the `updated` chart, tests for new only), and `full`
  (everything, incl. all tests). Test/component event rows carry `part_id` so
  incremental can append without disturbing existing rows.
- **CE stays as-is.** CE leaves render the same generic plots but link out to
  the existing `/hwdb/larasic/`, CE detail, and `/hwdb/dashboard/` pages. The
  demoted generic browse (`subsystem_list_view` / `part_type_list_view`) is
  superseded only once `/hwdb/explore/` ships, and is left in place until then.

## Consequences

- **Non-interference is a hard constraint.** No migrations alter existing
  tables; no existing view/template/URL/model changes behaviour. New code =
  new tables + new views + new URLs + one new API-client method (`systems/D`).
  If a change would touch existing CE behaviour, it's out of scope for this
  work.
- Two coexisting, complementary CE views (chip-progress on `/hwdb/dashboard/`,
  test-events under `/hwdb/explore/`) measure different things; this is
  intentional, and the labels make the distinction explicit.
- `HwdbTestEvent` can grow large (CE alone is ~10^5 rows); acceptable on
  SQLite for the lazy, per-visited-type sync of v1.
- "Tests recorded per month" can spike from bulk uploads (some consortia
  bulk-load); the axis label owns this rather than pretending it's a test rate.
