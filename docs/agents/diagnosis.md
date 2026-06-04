# Diagnosis data geography

Where the evidence lives when diagnosing a FEMB QC failure. Used by the `/ce-diagnose` skill; useful for any ad-hoc question about a test.

## Environments

| | QC report root | Database |
|---|---|---|
| Laptop (dev) | `tmp/femb/` (full mirror, contains `bnl/`) | `db.sqlite3` at repo root |
| Twister (production) | `/home/chao/mnt/femb/FEMB_QC` (SMB mount, fast) | `db.sqlite3` in the server's cets clone |

`FembTest.report_filename` is relative and `bnl/`-prefixed — resolve it against the QC report root (`FEMB_QC_DIR` in `.env`).

## Run directories

```
bnl/Time_<YYYY>_<MM>/
  <DD_HH_MM_SS>_<bench>_S0<femb-serial>_S1<femb-serial>_<RT|LN>_<QC|CHK>/   # RT=room temp, LN=liquid nitrogen
    FEMB<femb-serial>_S<slot>/                          # QC: one dir per FEMB slot
      Final_Report_FEMB_<serial>.md                     # overall verdict + per-item summary
      report_FEMB_<n>_t<N>_<P|F>_S<slot>.md             # per-test report; t1..t17, P=pass, F=fail
      PWR_Meas/ PWR_Cycle/ RMS/ CHK/ CALI1..6/ MON_*/   # per-test plots (.png) + raw dumps (.bin)
    Report/...report_FEMB_..._<P|F>.html                # CHK runs produce .html instead
```

- Pass/fail is **in the filename** (`_P_` / `_F_`) — find failures with `ls <dir>/report_*_F_*.md`.
- PNG plots are the richest evidence for waveform/noise questions — read them directly as images.
- `.bin` files are raw waveform dumps; no parser wired up yet — stay PNG-first (see #28).

## Test taxonomy

`docs/knowledge/fault-taxonomy.md` — t1–t17 with fault types and recommended actions. The broader knowledge base (datasheets, QC procedure docs) is catalogued in `docs/knowledge/INDEX.md`.

## Database

Query **read-only**: `sqlite3 'file:db.sqlite3?mode=ro'`. Key tables (Django models in `core/models.py`):

| Table | Model | What it holds |
|---|---|---|
| `core_femb` | FEMB | Inventory: `serial_number` (short form, e.g. `00023`), `version` (e.g. `IO-1865-1L`), `status`, `notes` (dated expert entries — debug findings, off-db repairs; appended via the web UI) |
| `core_fembtest` | FembTest | One row per test: `timestamp`, `test_type` (QC/CHK), `test_env` (RT/LN), `status`, `report_filename`, `femb_id` |
| `core_fembrepair` | FembRepair | Repair log: `iteration_number`, `date`, `operator`, `what_was_fixed`, `comments` |
| `core_larasic` | LArASIC | 8 per FEMB: `serial_number`, `femb_id`, `femb_pos` (F1–F4/B1–B4) |
| `core_coldadc` | ColdADC | 8 per FEMB, same shape |
| `core_coldata` | COLDATA | 2 per FEMB (F1, F2) |
| `core_cable`, `core_cabletest` | CABLE, CableTest | Cable inventory + tests |

Gotchas:

- Run-dir names use the **full serial** (`BNL_FEMB_IO-1865-1L_00038`); `core_femb.serial_number` stores the **short form** (`00038`) with the batch in `version`. Query with both: `WHERE serial_number='00038' AND version='IO-1865-1L'`.
- Position labels collide across chip types (`LArASIC F1` ≠ `ColdADC F1`) — key on `(chip type, femb_pos)`. See `CONTEXT.md`.
- `core_fembtest.status` is often blank for QC rows — the report file verdict is authoritative.

Recurrence check: test timeline from `core_fembtest` ordered by `timestamp`, with `core_fembrepair` for intervening repairs.
