# Physics test-date registry

> Source: live-HWDB spikes (`.idea/spike/hwdb_sipm_test_date.py`), issue #70.
> Code: `TEST_DATE_SPECS` / `test_date_spec()` in `explore/events.py` — the
> registry there is authoritative; this page records the evidence behind it.

Where each mapped component type stores its real (physics) test date inside a
test record's `test_data`, and in what format. Types NOT listed here bin their
"Tests recorded" chart by the HWDB record `created` stamp (upload time) and
sync via the cheap summary endpoint (`components/{pid}/tests` — which returns
`test_data: {}`; the datasheet only comes back from the detailed
`components/{pid}/tests/{test_type_id}` endpoint).

## Mapped types

### CE chips — LArASIC, ColdADC, COLDATA

- **Type ids**: per instance, from `HWDB_PROFILES[*]["{larasic,coldadc,coldata}_part_type"]`
  (prod: D08100100003 / D08100200002 / D08100300003).
- **Path**: top-level `test_data["Test Date"]`.
- **Format**: `YYYY/MM/DD` or `YYYY-MM-DD` (a separate `Test Time` field holds
  time-of-day; ignored — chart bins are daily/monthly). ADR-0009 covers the
  `created` fallback when the field is missing.

### SiPM board — D00400100003 (prod)

- **Path**: `test_data["Test Results"][0]["Date"]` — `Test Results` is a
  **list**; `_meta` sits beside it. Only single-entry lists observed so far.
- **Format**: `DD-MM-YYYY-HH:MM UTC` (e.g. `20-07-2023-10:19 UTC`) on current
  uploads. An early batch (`-00001…-00005`, uploaded 2025-12-17) wrote
  `MM-DD-YYYY-HH:MM UTC` (e.g. `05-17-2024-09:23 UTC`) on three of the four
  test types — HWDB is append-only, so those records keep the old format
  forever.
- **Parsing rule** (spike-verified 2026-07-16 on `-00001/-00002/-00047`):
  try both orderings per record; a day > 12 settles it (covers every record
  seen in both batches); when both orderings parse, defer to the declared
  default (`day_first: true`). Worst case an ambiguous old record lands
  day/month-swapped within the same year — invisible at monthly bins.

## Adding a type

1. Spike the real records first (copy `.idea/spike/hwdb_sipm_test_date.py`) —
   path AND format must be verified, never guessed: date-order is ambiguous
   for days ≤ 12, and formats have flipped between upload batches before.
2. Add the entry to `TEST_DATE_SPECS` in `explore/events.py` and record the
   evidence here.
3. Cost: a registry type syncs via one **detailed** call per test type per
   component (instead of one summary call per component). Fine at SiPM scale;
   think before mapping very large families.
4. Existing mirrors keep binning by `created` until a **full** re-sync of the
   type re-fetches the dates.
