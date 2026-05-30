# ADR-0006: HWDB test dedup is shape-aware

- **Status:** Accepted
- **Date:** 2026-05-29

## Context

LArASIC QC results can be uploaded in two shapes — **simple** (7 summary
fields) and **detailed** (simple + 60 per-channel readings + an attached CSV).
Both land at the same endpoint (`POST /components/{id}/tests/{type_id}`) and
HWDB stores them as plain test records with no shape flag.

Two facts about HWDB constrain dedup:

- **Tests are not PATCHable.** Once posted, the only way to "amend" a record
  is to post a new one.
- **HWDB does not dedup test POSTs server-side.** Two identical POSTs produce
  two records.

The original `find_existing_test` matched on `(Test Date, Test Time)` only.
That correctly skipped re-runs of an identical upload, but also blocked the
operator's real workflow: post simple records during a tray run, then come
back later with the raw CSV and upgrade them to detailed records at the same
timestamp. The matcher would say "already there" and the CSV data would be
lost.

We also need an operator escape hatch for the case where a detailed record
exists but its CSV upload silently failed (the bug fixed in `9a650d2`).
Without a way to force a re-post, those records stay CSV-less forever.

## Decision

Make dedup **shape-aware**, with a single signature line:

```python
def _is_detailed_record(test_data: dict) -> bool:
    return "CH0 Pedestal" in test_data
```

Rules in `find_existing_test`:

| existing | posting    | force_csv_attach | outcome    |
|----------|------------|------------------|------------|
| simple   | simple     | —                | **dedup**  |
| simple   | detailed   | —                | **upgrade** (re-post) |
| detailed | simple     | —                | **dedup**  |
| detailed | detailed   | off              | **dedup**  |
| detailed | detailed   | on               | **re-post** |

`force_csv_attach` is exposed as a checkbox on the upload tray and is the only
way to deliberately create a duplicate detailed record.

## Consequences

- `_is_detailed_record` is the single chokepoint to update if HWDB ever
  renames the channel-data keys. Tests in
  `hwdb/tests/test_upload_larasic.py` (`test_detailed_upgrade_over_simple_…`,
  `test_detailed_dedups_against_existing_detailed`,
  `test_force_csv_attach_reposts_detailed_record`) lock the behavior.
- Force CSV attach knowingly creates duplicates indiscriminately — it walks
  every chip in scope and re-posts. The operator carries that cost on purpose
  when they need to back-fill CSVs.
- We deliberately did **not**:
  - Ask HWDB for a shape field — out of our control, and the signature is
    cheap to maintain.
  - Dedup on date/time only and accept duplicates after upgrades — that's the
    behavior we're fixing.
  - PATCH existing records — HWDB does not support it.
- The matcher runs against the per-type endpoint
  (`/components/{id}/tests/{type_id}?history=True`), not the combined
  endpoint, because the combined endpoint returns "last instance of each test
  type" in a different record shape with no clear `test_type_id` — a
  collapsed-GET attempt earlier in development silently failed to dedup and
  produced duplicate posts.

Links: [[0005-parallel-hwdb-uploads]], CONTEXT.md HWDB / "Simple vs detailed
QC record".
