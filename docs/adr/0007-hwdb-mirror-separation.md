# ADR-0007: HWDB mirror lives in its own table, not on the chip models

- **Status:** Accepted
- **Date:** 2026-06-01

## Context

The `/hwdb/dashboard/` page needs to show test progress for ColdADC and
COLDATA chips, which are mostly tested at other institutions — BNL has no
local test records for them. The natural data source is HWDB itself: each
chip's latest `RoomT QC Test` and `CryoT QC Test` timestamp.

The same dashboard also shows LArASIC, but for a different reason: a
consistency check. LArASIC chips are tested at BNL and uploaded to HWDB;
the gap between the local-dashboard chart and the HWDB-dashboard chart is
the "tested but not yet uploaded" backlog.

We considered two shapes for this data:

1. **Add columns to existing models** — `latest_rt_test_at` and
   `latest_ln_test_at` on `LArASIC`, `ColdADC`, `COLDATA`. Simple, no new
   tables, joins are free.
2. **A separate mirror table** — `HwdbChip(family, serial_number,
   part_id, latest_rt_test_at, latest_ln_test_at, last_seen_at)`.
   Duplicates the serial number across tables; one extra ORM hop to relate
   to a local chip.

Option 1 muddles two domains. The CETS chip tables represent **what BNL
has tested locally** — they are CETS's system of record. Folding
HWDB-sourced test data into the same rows means the same column means two
different things across families: for LArASIC it would be derived from
BNL's RTS folders, for ColdADC/COLDATA it would be derived from HWDB.
A future reader (or a future query) cannot tell which is which.

## Decision

**HWDB-mirrored data lives in a dedicated `HwdbChip` table**, never on the
existing chip tables. The mirror is a separate slice of state with its own
provenance ("snapshotted from HWDB at sync time") and is consumed only by
the HWDB dashboard.

```python
class HwdbChip(models.Model):
    family             = CharField(choices=["larasic","coldadc","coldata"])
    serial_number      = CharField(max_length=50)
    part_id            = CharField(max_length=50)        # HWDB internal id
    part_type_id       = CharField(max_length=20)        # for multi-variant futures
    latest_rt_test_at  = DateTimeField(null=True)
    latest_ln_test_at  = DateTimeField(null=True)
    created_at         = DateTimeField(auto_now_add=True)
    last_seen_at       = DateTimeField()
    class Meta:
        unique_together = [("family", "serial_number")]
```

`HwdbChip` is **prod-only** by construction (dev sync is a no-op, same
posture as [[0003-prod-scoped-is-in-hwdb-flag]] /
[[0004-per-session-instance-toggle]]).

## Consequences

- CETS chip tables stay pure — `LArASIC.cold_tested_at` always means "BNL
  has the RTS cold folder for this chip," never "HWDB says it's cold-tested
  somewhere."
- The consistency check is a join, not a column compare:
  `LArASIC.objects.filter(cold_tested_at__isnull=False,
  hwdbchip__latest_ln_test_at__isnull=True)` enumerates the upload backlog.
- `LArASIC.is_in_hwdb` becomes structurally redundant with
  `HwdbChip.objects.filter(family="larasic", serial_number=…).exists()`.
  We do **not** drop it in this ADR — that's a follow-up cleanup once the
  mirror is established and all read sites are migrated.
- `HwdbChip` rows are never deleted on sync; a chip that disappears from
  HWDB has its `last_seen_at` stop advancing, which the dashboard surfaces
  as a count. Deletion is intentionally manual.
- Adding new component types means a new `family` enum value and a new
  `<family>_part_type` key in `HWDB_PROFILES` — no schema migration.
- `part_type_id` is stored on the row so we can later support pulling from
  multiple variants per family (e.g. `coldadc_p2prep` + `coldadc_p2prb1`
  side by side) without a migration.

Links: [[0003-prod-scoped-is-in-hwdb-flag]],
[[0008-skip-known-serials-incremental-sync]], CONTEXT.md HWDB / HWDB mirror.
