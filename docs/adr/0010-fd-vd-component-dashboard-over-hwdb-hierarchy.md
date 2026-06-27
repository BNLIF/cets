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
- **Canonical plot date = HWDB `created`.** Uniform and always present;
  labelled "tests *recorded* per month" (not physics test date). Physics /
  datasheet dates from the detailed `…/tests/{type_id}` endpoint are a deferred
  refinement. Extends the created-timestamp fallback of
  [[0009-hwdb-mirror-test-timestamp-fallback]].
- **Test-type facets read dynamically** from `test_type.name` — no hard-coded
  consortium knowledge (TDE's `amc_bandwidth_test` and CE's `RoomT QC Test`
  are just legend labels).
- **Navigation: sidebar folder-tree, master-detail**, served from the mirror,
  at a new URL `/hwdb/explore/`. Per-node component-count badges; a leaf gains
  a "has test data" accent only after its plot-sync runs.
- **Scope (v1): a curated FD-VD whitelist** — systems named `FD-VD *` plus
  `FD CE`. Other shared `FD *` systems (DAQ, Slow Control, Cryostat, …) are
  excluded for now; adding one is a whitelist edit.
- **Sync: skeleton eager, plot data lazy.** A `sync_hierarchy` command (+
  button) populates `ComponentTypeNode` for the whitelist; per-component-type
  test events sync on first visit to that leaf and cache, FNAL-gated like the
  existing sync. Reuses the existing streaming-sync UX.
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
