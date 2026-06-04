---
name: ce-diagnose
description: Diagnose a FEMB QC failure from a run directory, report file/path, FEMB serial, or pasted error. Maps symptoms to the fault taxonomy, checks test/repair history in the cets db, escalates to report plots when ambiguous, and recommends next actions. Use when the user asks "what's wrong with this error/run/test", points at a report_*_F_*.md or a report_filename from the web UI, or invokes /ce-diagnose.
---

# Diagnose a FEMB QC failure

Input (`$ARGUMENTS`): a run directory, a report file path (absolute, or a `bnl/...` `report_filename` from the web UI / db), a FEMB serial number, or pasted error text. If empty, ask what to diagnose — or offer the most recent run containing a `_F_` report.

Read `docs/agents/diagnosis.md` first: environment paths (laptop vs Twister QC roots), run-dir layout, db schema, and the serial-format gotcha.

## Procedure

### 1. Locate the failure

- `bnl/...` relative path → resolve against the environment's QC report root.
- Run dir → `ls <dir>/**/report_*_F_*.md`; if none fail, check the `Final_Report_*.md` verdict — the run may have passed (say so and stop unless asked to review anyway).
- FEMB serial → newest first: `ls -dt <qc-root>/bnl/Time_*/*<serial>*/FEMB*<serial>*`; or query `core_fembtest.report_filename` for its test rows.
- Pasted error text → grep the QC root for matching strings.

### 2. Read the evidence (always)

- Read each failed `report_FEMB_*_t<N>_F_*.md` and the `Final_Report_*.md` summary line for that item. The failing-channel signature at the top reads `[[<channels>], [<chip indices>]]`.
- Map `t<N>` via `docs/knowledge/fault-taxonomy.md`: what the test exercises, fault types, granularity, recommended actions.
- Pull acceptance criteria and spec limits from `docs/knowledge/` (start at `INDEX.md`).

### 3. Check history (always)

Query the db read-only (`sqlite3 'file:db.sqlite3?mode=ro'`), matching `serial_number` (short form) + `version`:

- Test timeline: `core_fembtest` joined on `core_femb`, ordered by `timestamp`. QC-row `status` is often blank — the report file verdict is authoritative.
- Repairs between runs: `core_fembrepair` (`what_was_fixed`, `operator`, `comments`).
- Chips on the board: `core_larasic` / `core_coldadc` / `core_coldata` by `femb_id` + `femb_pos` — needed to name a suspect chip. Chip index → `femb_pos` mapping is in the taxonomy doc (idx 0–7 → F1, B1, B2, F2, F3, B3, B4, F4).

Recurrence changes the recommendation: first failure → reseat/re-run; recurring after repair → suspect the named chip or the repair itself.

### 4. Escalate to plots (only if the reports are ambiguous)

Read the PNG plots in the test's subdirectory (`RMS/`, `CHK/`, `CALI*/`, `MON_*/`, `PWR_*/`) as images — baseline, noise, and pulse-shape anomalies are usually visible there. Raw `.bin` dumps have no parser wired up yet — don't attempt them; say so if the PNGs are insufficient.

### 5. Conclude

Present, in order:

1. **What failed** — test item(s), one-line symptom each.
2. **Most likely cause** — fault type from the taxonomy, root-cause level (board / chip / channel), named suspect chip serial if the evidence supports it. State confidence and what would distinguish the alternatives.
3. **History** — first occurrence or recurrence; relevant repairs.
4. **Recommended action** — from the taxonomy, adjusted for history. If a targeted re-run would discriminate hypotheses, give the config (gain / peaking / baseline register bits are in the taxonomy doc).
5. **Sources** — report files, knowledge docs, and db rows you relied on (clickable paths).

Stay in the conversation — the user will ask follow-ups. Do not write diagnoses into the database or the run directories.
