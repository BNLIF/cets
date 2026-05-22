# Deferred TODOs

Open items not yet filed as GitHub issues. Convert to issues when a
major design direction is settled.

## Data integrity

- **Prevent dual-FEMB chip assignment.** No validation stops the same
  chip from being assigned to two FEMBs at once. Add a model `clean()`
  or a DB constraint; needs corresponding test coverage.

## Repair workflow

- **Preserve `femb_pos` on removal.** When `removed_at_repair` is set,
  `femb_pos` is cleared so the repair history loses the position the
  chip occupied. Add a `removed_femb_pos` field (or equivalent) and a
  data migration to backfill from existing repair records.

## Frontend

- **FEMB detail prev/next navigation.** Design decisions before
  building: order by serial_number (alphabetical) or by
  latest_test_timestamp? Within the same version, or across versions?
- **Partial-match FEMB SN search.** Currently the SN search redirects
  on exact match only. Changing this changes existing search semantics
  for the team — needs a heads-up before shipping.

## API

- **Add REST endpoints** for LArASIC, ColdADC, COLDATA, and FembRepair.
- **API pagination.** Pick a style (PageNumber / LimitOffset / Cursor)
  and page size before wiring; DRF has it built-in.

## Operations

- **Persistent log for management commands.** Today they write to
  stdout/stderr only; runs leave no record of what changed.
- **SQLite → PostgreSQL.** Only required when ingestion goes parallel.
  3 gunicorn workers + management commands can serialize for now.
