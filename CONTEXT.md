# CETS Domain Glossary

Canonical names for the cold-electronics components tracked in this system.
Code, URLs, templates, and UI labels should all use these names.

## Components

### LArASIC

Liquid Argon ASIC — the front-end readout chip. 16-channel charge-sensitive
amplifier ASIC, mounted on a FEMB. Eight per FEMB (4 front, 4 back).

- Product name: **LArASIC**
- Code class: `LArASIC` (renamed from `FE` in migration 0008)
- Serial-number example: `009-05061`

### ColdADC

The cold-temperature ADC chip. 16-channel ADC ASIC, mounted on a FEMB.
Eight per FEMB (4 front, 4 back).

- Product name: **ColdADC**
- Code class: `ColdADC` (renamed from `ADC` in migration 0008)
- Serial-number example: `2502-18564`

### COLDATA

Data concentration / serializer ASIC. Two per FEMB (positions F1, F2).

- Product name: **COLDATA**
- Code name: `COLDATA` (matches)

### FEMB

Front-End Mother Board. The PCB onto which LArASIC, ColdADC, and COLDATA
chips are mounted. Each FEMB has a `version` (e.g. `IO-1865-1K`) plus a
`serial_number` (e.g. `00016`); the pair is unique.

### CABLE

Interconnect cable between FEMBs and the warm electronics. Tracked
separately with its own test history.

## Concepts

### Position label (`femb_pos`)

A 2-character code identifying where a chip sits on a FEMB:

- First char: `F` (front) or `B` (back)
- Second char: digit 1–4 (or 1–2 for COLDATA)

Examples: `F1`, `F3`, `B2`.

**Important:** position labels can collide *across* chip types — `LArASIC F1`
and `ColdADC F1` and `COLDATA F1` are all legitimate, distinct positions.
Code that diffs chip state must key by `(type, position)`, never by
position alone. See `compute_repair_diff` in
`core/management/commands/update_fembs_from_ocr.py`.

### Repair iteration

Each FEMB can undergo multiple repair iterations after initial assembly,
numbered `1, 2, 3, ...`. Each repair is a snapshot of which chips were
removed and which were installed. Chips carry both
`installed_at_repair` and `removed_at_repair` FKs into the `FembRepair`
table; `NULL` on `installed_at_repair` means "present since original
assembly." On `removed_at_repair`, `NULL` means "still installed."

OCR-scanned `femb_parts_*.txt` files in `FEMB_OCR_DIR` are the source of
truth; the ingestion command diffs successive snapshots to compute the
repair record.

### RTS

Readout Test System. Tests run on LArASIC chips before they're mounted
on a FEMB. RTS results live as CSV files on an SMB-mounted read-only
share (`RTS_DIR`); the LArASIC detail page parses filenames to extract
metadata. Format: `<sn>_<timestamp>_<tray>_<socket>_<temperature>.csv`.

### HWDB

The DUNE **Hardware Database** (Fermilab's "CDB") — the external system of
record for every DUNE hardware item. The `hwdb/` app talks to its REST API to
display HWDB records and compare them against local chips; uploading QC records
is future work (issue #12).

- Two **instances**: `prod` (the default we compare against) and `dev` (a
  sandbox). Users toggle between them per-session; `is_in_hwdb` is always
  **prod-scoped**.
- **`is_in_hwdb`** — a per-chip boolean (on `LArASIC`) recording whether that
  serial already exists in the production HWDB, so a sync need not re-query it.
- **FNAL link** — auth is per-session, not per-Django-user (guests share one
  login but each links their own FNAL account). A vault OIDC device flow yields
  a bearer minted fresh per request; see the `hwdb/fnal/` package.
- **part-type ID** — HWDB's identifier for a component type, e.g. LArASIC is
  `D08100100004` on dev / `D08100100003` on prod.
