# TODO

## Data Integrity
- [ ] `FE.tray_id` has no `null=True`/`blank=True` and no default — chips created during repairs silently get an empty string. Add `blank=True, default=""` explicitly or make it nullable.
- [ ] No validation prevents a chip from being assigned to two FEMBs simultaneously. Add a model `clean()` or DB constraint to catch this.

## Repair Workflow
- [ ] Removed chip's position before removal is lost — `femb_pos` is cleared when `removed_at_repair` is set. Add a `removed_femb_pos` field (or equivalent) so repair history shows where the chip was.
- [ ] `update_fembs_from_ocr` silently fails if the original batch hasn't been loaded before rework batches. Add an explicit error message or auto-detect processing order.

## Frontend
- [ ] FEMB detail page has no prev/next navigation — users must return to the list. Add prev/next links.
- [ ] List page search only matches exact serial numbers. Support partial matching (e.g. `00032` matching `IO-1865-1L/00032`).
- [ ] Chip detail pages (FE, ADC, COLDATA) show no indication when a chip was removed from a FEMB during a repair. Add a "Removed from FEMB X during repair #N" note.

## API
- [ ] REST API only exposes FEMBs. Add endpoints for FE, ADC, COLDATA, and FEMB_REPAIR.
- [ ] API responses have no pagination.

## Operations
- [ ] SQLite will fail on concurrent writes if management commands run in parallel. Migrate to PostgreSQL if ingestion becomes parallel.
- [ ] Management commands produce no persistent log. Add log file output so ingestion runs leave a record of what changed.
- [ ] No automated tests. Add tests at minimum for `parse_parts_file`, `parse_inspection_note`, and the repair diff logic.
