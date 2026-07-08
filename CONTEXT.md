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
display HWDB records, compare them against local chips, and upload LArASIC QC
results (serial path or 10-worker parallel path; see
[[0005-parallel-hwdb-uploads]]).

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
- **HWDB mirror** — a slice of CETS state tracking what the production HWDB
  says about each chip (existence + RT/LN latest-test dates), kept in a
  dedicated `HwdbChip` table separate from the BNL-tested chip models.
  The two can disagree — BNL may have cold-tested a chip whose results
  haven't been uploaded yet — and the `/hwdb/dashboard/` consistency check
  surfaces that gap. Each chip is fetched from HWDB exactly once. Test
  timestamps come from `test_data["Test Date"]` when present, else from
  HWDB's record-creation stamp (ADR-0009 — upstream institutions
  sometimes upload empty-datasheet placeholders). See
  [[0007-hwdb-mirror-separation]] and [[0008-skip-known-serials-incremental-sync]].

### Hardware hierarchy (System / Subsystem / Component Type)

HWDB organises every part under a four-level path that is encoded directly in
the part-type ID. For LArASIC P5B Prod, `D08100100003` decodes as:

| Segment | Value | Level |
|---------|-------|-------|
| `D` | DUNE | **Project** |
| `081` | FD CE | **System** |
| `001` | LArASIC | **Subsystem** |
| `00003` | LArASIC P5B Prod | **Component Type** |

- **System**: top-level grouping under a Project, one per detector-area /
  consortium (e.g. `FD-VD TDE` = id 57, `FD CE` = id 81). The numeric `id`
  from `GET systems/D` is the 2nd PID segment. FD-VD spans systems
  51/54/55/56/57/58/59/80 plus the shared `FD CE` (81), DAQ, Slow Control.
- **Subsystem**: second level (e.g. `Digital electronics`, `Chimney`). The
  `subsystem_id` is the 3rd PID segment.
- **Component Type**: the leaf type with its own QC test-types and components
  (e.g. `AMC`, `LArASIC P5B Prod`). HWDB exposes a `full_name` like
  `D.FD-VD TDE.Digital electronics.AMC`. This is what the existing models call
  the **part-type ID**.
  _Avoid_: "part type" alone when the level matters — say Component Type.
- **Consortium**: the organisation that owns a slice of the hierarchy. For
  FD-VD it maps ~1:1 onto a System (CRP → Top/Bottom CRP, TDE, PDS, HVS, CI,
  Calibration; CE and DAQ are shared across FD-VD and FD-HD).

The whole tree is live in production HWDB and walkable via the API
(`systems/D` → `subsystems/D/{sys}` → `component-types/D/{sys}/{subsys}` →
`components` → `tests`). Today CETS surfaces only 3 of the 14 `FD CE`
subsystems (the three chip families); the dashboard expansion is about
navigating the rest read-only. See [[0007-hwdb-mirror-separation]].

The read-only navigator over this tree is the **DUNE HWDB Explorer** (`/hw/`),
its own `explore` app with FNAL login, a disposable local mirror, and curated
drill-in navigation. For the full design + implementation walkthrough
(authentication, the mirror tables, curation, sync engines), see
`docs/technote/explore-tech-note.md`.

### Hierarchy chart (detector chart)

The interactive FD-VD detector chart at `/hw/hierarchy/` — a pan/zoomable,
clickable SVG replica of the consortium-maintained "FD-VD Complete detector
(v10)" PowerPoint chart. Distinct from the *hierarchy mirror/tree* above: the
mirror is HWDB's System/Subsystem/Type structure; the chart is the physicists'
box-and-arrow drawing of the physical detector, which HWDB does not encode.

Three YAML files per chart in `explore/chart_specs/`, joined by stable
**node id** slugs (see [[0016-hierarchy-chart-spec-overlay-split]]):

- **chart spec** (`fd-vd-v10.yaml`) — hand-curated semantics: nodes, edges
  (child → parent, `kind: cable` for routed arrows), bands.
- **layout overlay** (`fd-vd-v10.layout.yaml`) — generated geometry
  (`manage.py extract_chart --layout` from the consortium .pptx or PDF);
  regenerated per chart update, never hand-edited.
- **mapping overlay** (`fd-vd-v10.mapping.yaml`) — hand-curated node id →
  Component Type ids per instance; audited by `manage.py audit_chart_mapping`.

### Type vs. instance (and the terms around it)

The most confused distinction in HWDB. **System / Subsystem / Component Type
are kinds** (folders); below the Component Type live the actual physical units.

- **Component Type** = the *kind / template* (`part_type_id`, e.g.
  `D08100100003`). One of these. It defines the specs and the test types that
  apply. Also called **part type**.
- **Part / component / item** = *one physical unit* (`part_id`, e.g.
  `D08100100003-00226`). Thousands of these. A `part_id` is literally
  `part_type_id` + `-` + a sequence number. It has a serial number, status,
  location, test results and attachments.

The naming is overloaded — pin it down:

- HWDB's **REST API** uses **"component" for an *instance***:
  `component-types/{type}/components` returns the *parts*, and
  `components/{pid}` is *one* part.
- HWDB's **web UI** calls that same instance an **"Item"**.
- Colloquial "component" can mean the *kind* — so when someone says
  "component", confirm whether they mean the Component Type or one unit.

Related instance-level terms:

- **Test type** — a *kind* of test defined on a Component Type (e.g.
  `RoomT QC Test`). The template.
- **Test** (record) — one *run* of a test type on one part: a status, a date,
  a `test_data` JSON payload, and sometimes attached files. The list endpoint
  (`components/{pid}/tests`) omits the test's oid/status/files; the per-type
  endpoint (`components/{pid}/tests/{test_type_id}`) carries them.
- **Specifications** — a free-form data blob on a part (or type). For shipping
  boxes it holds the pre-shipping/shipping/warehouse checklists; for other
  parts, whatever fields that type defines.
- **Subcomponents / manifest** — parts mounted *inside* another part (chips on
  a FEMB; contents of a shipping box). Each is itself a part with its own page.
- **Shipping box** — not a special entity: a part whose Component Type is
  curated as a shipping type, so its page is the generic part page plus
  shipment sections. See [[0013-shipment-tracker-on-shipping-leaves]] and
  [[0014-generic-part-detail-page]].

### Simple vs detailed QC record

A LArASIC QC test (RoomT or CryoT) can be uploaded in two shapes:

- **Simple** — 7 summary fields (test date/time, operator, tray/socket, pass).
- **Detailed** — the simple fields plus 60 per-channel readings (`CH0
  Pedestal`, `CH0 Gain`, … `CH15 ENC`) **and** an attached raw-data CSV.

HWDB stores both as plain test records with no shape flag, and tests are not
PATCHable. The dedup matcher infers shape by looking for `CH0 Pedestal` in
`test_data`, so a simple-mode upload followed later by a detailed-mode upload
at the same timestamp posts an **upgrade record** rather than skipping. See
[[0006-shape-aware-test-dedup]].
