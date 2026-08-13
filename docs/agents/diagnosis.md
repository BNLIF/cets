# Diagnosis data geography

Where the evidence lives when diagnosing a FEMB QC failure. Used by the `/ce-diagnose` skill; useful for any ad-hoc question about a test.

## Environments

| | QC report root | QC raw-data root | Database |
|---|---|---|---|
| Laptop (dev) | `tmp/femb/` (full mirror, contains `bnl/`) | `tmp/FEMB_QC/Data/` (sshfs mount — **slow**, copy files locally before decoding) | `db.sqlite3` at repo root |
| Twister (production) | `/home/chao/mnt/femb/FEMB_QC` (SMB mount, fast) | `/home/chao/mnt/femb/FEMB_QC/Data` | `db.sqlite3` in the server's cets clone |

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

## Raw data (waveform-level escalation)

Raw acquisitions live under the **QC raw-data root** (`FEMB_RAW_DIR` in `.env`), in run directories parallel to the report mirror (no `bnl/` prefix, no per-slot subdir):

```
<raw-root>/Time_<YYYY>_<MM>/<run-name>/QC/
  RMS/QC_femb_rms_t5.bin   CHK/femb_chk_pulse_t4.bin   CALI1/QC_Cali01_t6.bin   ...
```

Every test item writes a `.bin`, but only some are decodable waveforms:

| Test | File | Size | Waveforms? |
|---|---|---|---|
| t1, t2 | `PWR_Meas/QC_PWR_t1.bin`, `PWR_Cycle/QC_PWR_Cycle_t2.bin` | 6 / 10 MB | yes (`PWR_*` keys; `MON_Regular_*` keys are scalars) |
| t3 | `Leakage_Current/QC_femb_leakage_cur_t3.bin` | 20 MB | yes |
| t4 | `CHK/femb_chk_pulse_t4.bin` | 50 MB | yes |
| t5 | `RMS/QC_femb_rms_t5.bin` | 520 MB | yes |
| t6–t9, t13, t14 | `CALI1..6/QC_Cali0*_t*.bin` | 80–560 MB | yes |
| t15, t16 | `ADC_SYNC_PAT/`, `PLL_PAT/` | 30 / 8 MB | yes |
| t10, t11, t12, t17 | `MON_FE/`, `MON_ADC/`, `REG_MON/` | < 1 MB | **no** — per-chip scalar monitor readings; `femb_wave.py` raises `TypeError` on them |

Each `.bin` is a Python pickle: a dict keyed by config name (e.g. `RMS_SE_900mVBL_14_0mVfC_2_0us_0x00.bin`); `value[0]` is a list of ~10 acquisition events, each `([buf0..buf7], buf_end_addr, trigger_rec_ticks, trig_cmd)` where `bufs[femb*2 + cd]` are 256 KiB WIBEth spy-buffer dumps (2 COLDATA streams × 64 channels per FEMB slot; slot S0 → `femb=0`).

Decode and plot with **`tools/femb_wave.py`** (pure numpy port of the WIBEth frame decode from `sgaobnl/BNL_CE_WIB_SW_QC`; needs numpy + matplotlib):

```bash
python3 tools/femb_wave.py --bin <raw>/QC/RMS/QC_femb_rms_t5.bin --list-keys
python3 tools/femb_wave.py --bin <...>.bin --femb 0 --scan 16          # baseline-jump scan, one channel (t5 pedestal data only)
python3 tools/femb_wave.py --bin <...>.bin --femb 0 --ch 16,15 --key RMS_SE_900mVBL_25_0mVfC_3_0us --event 3 --out analysis/waveforms
```

On the laptop the raw mount is slow sshfs (~3 MB/s) — `cp` the `.bin` to a local scratch dir first (t5 ≈ 520 MB ≈ 3 min).

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
