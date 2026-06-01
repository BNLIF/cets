# ADR-0008: HWDB mirror sync skips known serials

- **Status:** Accepted
- **Date:** 2026-06-01

## Context

Populating `HwdbChip` ([[0007-hwdb-mirror-separation]]) for ColdADC,
COLDATA and LArASIC requires two HWDB calls per chip:

1. List components by `part_type_id` — paginated, ~48 pages for 24k chips,
   ~5–10 seconds total.
2. `GET /components/{part_id}/tests` — per chip, ~200 ms per call.

The per-chip step is the cost driver. At ~24k chips × 200 ms ÷ 10 workers,
the first sync is ~8 minutes. Re-running this on every Sync click is a
non-starter operationally — the dashboard would feel broken.

HWDB's REST API does not help: there is no `updated_after` / `modified_since`
filter on either the component listing or the tests endpoint, and the
official DUNE-HWDB-Python library (`get_hwitems` / `get_hwitem_tests`)
exposes no equivalent. We have to invent incrementality client-side.

We considered three policies:

- **Re-fetch all chips on every sync.** Always-fresh but always slow.
  ~8 min/sync forever.
- **Re-fetch chips whose latest test is partial** (one of RT/LN set, the
  other NULL). Costs whatever fraction is partial — probably 5–20% in
  steady state. Still slow when the unfinished tail is large.
- **Fetch each chip exactly once, ever.** Cheap forever after the initial
  pass. Misses HWDB-side edits to chips we've already seen.

## Decision

**Once a chip's tests have been fetched and recorded in `HwdbChip`, the
sync never re-fetches that chip.** A serial number that's already in the
table is treated as immutable from our point of view.

The sync algorithm:

1. Paginate the component listing for the family's `part_type_id`. Cheap.
2. Build the set difference `hwdb_serials - local_serials` — these are the
   only chips for which we call `GET /tests`.
3. Stamp `last_seen_at = now()` on every listed chip (whether new or known).
4. For chips no longer in HWDB but still in our table, leave the row in
   place. Their `last_seen_at` stops advancing; the dashboard reports
   "N disappeared since last sync" as a stat.

A **Force full re-sync** checkbox on the dashboard bypasses step 2 — it
re-fetches every chip's tests. This is the escape hatch for the rare case
where an operator suspects HWDB-side edits to historical chips.

This mirrors our existing posture against `qaqc_uploaded`: we don't trust
HWDB state we didn't write ourselves. The mirror represents "what HWDB
showed us the first time we asked," and we accept that this can lag silent
upstream edits.

## Consequences

- Steady-state sync cost is `listing pages + per-new-chip get_tests`. Once
  the backlog stabilizes, every sync is sub-second.
- The "skip" semantics applies to all three families, including LArASIC.
  An RT-only LArASIC chip whose CryoT QC arrives in HWDB after we've
  cached it will **not** show up as LN-tested on the HWDB dashboard until
  someone clicks Force full re-sync.
- The consistency-check value of the LArASIC chart is bounded by how
  recently a force-full has run — important for Karla to understand.
  Document the caveat on the dashboard ("HWDB-side edits to known chips
  are picked up only on Force full re-sync").
- `last_seen_at` is the freshness signal, not `last_tests_fetched_at`. The
  former advances every sync; the latter is set once per chip and never
  again under the default policy.
- We deliberately did **not**:
  - Add a `latest_test_arrived_at` heuristic that re-fetches chips with
    RT-but-no-LN past N days. Initially considered as a "safety net" but
    rejected on the same grounds as `qaqc_uploaded`: any rule less strict
    than "fetch every time" is a guess about HWDB behavior we don't own.
    Force full re-sync covers the rare case and is operator-visible.
  - Build a webhook / push from HWDB. Out of our control.

Links: [[0003-prod-scoped-is-in-hwdb-flag]],
[[0007-hwdb-mirror-separation]], CONTEXT.md HWDB / HWDB mirror.
