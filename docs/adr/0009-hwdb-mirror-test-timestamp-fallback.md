# ADR-0009: HWDB mirror falls back to record-creation time when `Test Date` is missing

- **Status:** Accepted
- **Date:** 2026-06-01

## Context

The HWDB mirror (`HwdbChip`, [ADR-0007](0007-hwdb-mirror-separation.md))
stores `latest_rt_test_at` and `latest_ln_test_at` per chip, sourced by
parsing the `test_data["Test Date"]` + `["Test Time"]` fields out of each
test record returned by `GET /components/{id}/tests`.

Empirically (`D08100300003-01425`, 2026-06-01 probe), some upstream
institutions upload QC test records with **empty `test_data`**:

```json
{
  "comments": "No comment",
  "created": "2026-05-27T14:10:33.115371-05:00",
  "test_type": {"id": 36, "name": "RoomT QC Test"},
  "test_data": {}
}
```

The record carries the test-type name and a top-level `created` timestamp
(HWDB's server-side ingestion stamp), but no lab-time fields. Our original
sync silently skipped these — leaving the chip flagged as "no RT test on
record" even though HWDB clearly contains an RT test record for it.

CETS-side uploads always populate `Test Date / Test Time` (see
`hwdb/upload/larasic.py`), so this only affects records uploaded by
non-CETS workflows — almost entirely ColdADC and COLDATA, which are
tested at other institutions.

## Decision

When `test_data["Test Date"]` is missing on a recognized test type, fall
back to the record's top-level `created` timestamp:

```python
def _test_record_dt(test_record):
    return (
        _parse_test_dt(test_record.get("test_data") or {})
        or _parse_created(test_record.get("created"))
    )
```

The mirror's per-chip timestamp therefore carries one of two semantics:

- **Lab time** — when the chip was physically tested, when the upload
  filled the datasheet.
- **Upload time** — when HWDB ingested the test record, when the upload
  left `test_data` empty.

`Test Date` is preferred when both are available.

## Consequences

- ColdADC and COLDATA chips uploaded with empty-datasheet placeholders
  now show up on the chart — usually within the same day as the actual
  lab test, because upstream institutions typically upload promptly.
- LArASIC sync is unaffected. CETS-uploaded LArASIC records always carry
  `Test Date / Test Time` from the RTS folder name, so lab time wins
  every time.
- The dashboard UI does not distinguish the two semantics. A hover
  tooltip or footnote could be added later if operators need to know the
  difference (e.g. for delivery-rate reporting that depends on lab time
  specifically).
- The fallback is silent — sync does not currently report how many
  chips landed on `created` vs `Test Date`. Worth surfacing in the sync
  progress stream as a follow-up if the question arises.
- We deliberately did **not** invent a third timestamp source (e.g.
  `comments` parsing) — the two stamps named here are the only ones HWDB
  exposes consistently across instances and part types.

Links: [[0007-hwdb-mirror-separation]],
[[0008-skip-known-serials-incremental-sync]].
