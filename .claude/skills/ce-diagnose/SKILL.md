---
name: ce-diagnose
description: Diagnose a FEMB QC failure from a run directory, report file/path, FEMB serial, or pasted error. Maps symptoms to the fault taxonomy, checks test/repair history in the cets db, escalates to report plots when ambiguous, and recommends next actions. Use when the user asks "what's wrong with this error/run/test", points at a report_*_F_*.md or a report_filename from the web UI, or invokes /ce-diagnose.
---

# Diagnose a FEMB QC failure

Input (`$ARGUMENTS`): a run directory, a report file path (absolute, or a `bnl/...` `report_filename` from the web UI / db), a FEMB serial number, or pasted error text. If empty, ask what to diagnose — or offer the most recent run containing a `_F_` report.

Read `docs/agents/diagnosis.md` first: environment paths (laptop vs Twister QC roots), run-dir layout, db schema, and the serial-format gotcha.

## Procedure

### 0. Start the clock

In your **first** tool call, record the start timestamp for the cost footer (§6):

```bash
date -u +%Y-%m-%dT%H:%M:%SZ
```

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

- Board notes: `core_femb.notes` — dated, expert-entered entries (debug findings, off-db repairs, known marginal chips). Read them first; they can short-circuit or redirect the whole diagnosis.
- Test timeline: `core_fembtest` joined on `core_femb`, ordered by `timestamp`. QC-row `status` is often blank — the report file verdict is authoritative.
- Repairs between runs: `core_fembrepair` (`what_was_fixed`, `operator`, `comments`).
- Chips on the board: `core_larasic` / `core_coldadc` / `core_coldata` by `femb_id` + `femb_pos` — needed to name a suspect chip. Chip index → `femb_pos` mapping is in the taxonomy doc (idx 0–7 → F1, B1, B2, F2, F3, B3, B4, F4).

Recurrence changes the recommendation: first failure → reseat/re-run; recurring after repair → suspect the named chip or the repair itself.

### 4. Escalate to plots (only if the reports are ambiguous)

Read the PNG plots in the test's subdirectory (`RMS/`, `CHK/`, `CALI*/`, `MON_*/`, `PWR_*/`) as images — baseline, noise, and pulse-shape anomalies are usually visible there.

### 4b. Escalate to raw waveforms (channel-level anomalies)

For a channel-level anomaly, decode the raw acquisition and look at the waveform. **t1–t9 and t13–t16 all write a decodable spy-buffer `.bin`** (per-test paths and sizes: `docs/agents/diagnosis.md` § Raw data, which also has the pickle/frame format). **t10–t12 and t17 do not** — those bins hold per-chip scalar monitor readings, not waveforms, and `femb_wave.py` dies on them with a `TypeError`; for those items the report plots in `MON_*/` and `REG_MON/` are the deepest evidence available.

What the waveform buys you depends on the test:

- **t5 (pedestal, no injection)** — the case steps 2–3 below are written for. Only the waveform separates `high_noise` from `baseline_jump`; the RMS plots show just the elevated RMS.
- **Pulse-injection tests (t3, t4, t6–t9, t13, t14)** — compare the suspect channel against a same-chip neighbour and read pulse **height, shape, and timing**. Skip `--scan` and the histogram: both assume a flat baseline, and the injected pulse dominates them (in a healthy t4, suspect and neighbour both report ~660 ADC max step — the metric is measuring the pulse, not a defect).
- **t15/t16 (pattern tests)** — the waveform shows whether the channel tracks the expected pattern at all.

1. Find the raw file: `$FEMB_RAW_DIR/Time_<YYYY>_<MM>/<run-name>/QC/<TEST>/*_t<N>.bin` (`FEMB_RAW_DIR` from `.env`; same run-name as the report dir; slot S`<n>` → `--femb <n>`). Use `--list-keys` to get the exact config key. On the laptop the raw root is a slow sshfs mount at ~3 MB/s — copy the `.bin` to local scratch first (t5 ≈ 520 MB ≈ 3 min, CALI1 ≈ 560 MB; loading the pickle straight off the mount takes minutes and can time out); on Twister read it in place.
2. **t5 only:** `python3 tools/femb_wave.py --bin <file> --femb <slot> --scan <channel>` — ranks configs/events by baseline step size. Meaningless on pulse-injection tests (see above).
3. Render the evidence plots into `analysis/waveforms/<run-date>_FEMB-<serial>/` (one directory per diagnosis) and Read each PNG before citing it. The two plots below are the t5 recipe; on a pulse test render the neighbour comparison only, without `--hist`, and cite pulse height/shape instead of the histogram:
   - `wave_ch<N>_jump.png` — the step waveforms: the suspect channel across the top few events, `--event <a>,<b>,<c>` (one column per event). Steps that move in time event-to-event are the telegraph signature; the red per-frame-mean overlay makes the levels readable.
   - `wave_ch<N>.png` — the neighbour comparison: `--ch <N-1>,<N>,<N+1> --hist`. The amplitude histogram is the decisive panel — a `baseline_jump` channel is **bimodal** while its neighbours are single Gaussians; `high_noise` stays unimodal but wide.

   ```bash
   python3 tools/femb_wave.py --bin <file> --femb <slot> --ch 16 --key <config> --event 6,3,4 \
     --out analysis/waveforms/<run-date>_FEMB-<serial> --out-name wave_ch16_jump.png
   python3 tools/femb_wave.py --bin <file> --femb <slot> --ch 15,16,17 --hist --key <config> --event 6 \
     --out analysis/waveforms/<run-date>_FEMB-<serial> --out-name wave_ch16.png
   ```
4. Embed both plots in the conclusion (relative `![...](waveforms/<dir>/<file>.png)` links, so they render in the saved report and the PDF) together with the step/spread/RMS numbers the tool prints.

### 5. Conclude

Present, in order:

1. **What failed** — test item(s), one-line symptom each.
2. **Most likely cause** — fault type from the taxonomy, root-cause level (board / chip / channel), named suspect chip serial if the evidence supports it. State confidence and what would distinguish the alternatives.
3. **History** — first occurrence or recurrence; relevant repairs.
4. **Recommended action** — from the taxonomy, adjusted for history. If a targeted re-run would discriminate hypotheses, give the config (gain / peaking / baseline register bits are in the taxonomy doc).
5. **Sources** — report files, knowledge docs, and db rows you relied on (clickable paths).

Wherever the report mentions a board, chip, or report/plot file, link the Twister website so the reader can click through:

- FEMB: `https://www.phy.bnl.gov/twister/cets/femb/<version>/<serial>/` — e.g. `https://www.phy.bnl.gov/twister/cets/femb/I0-1865-1K/00020/`
- Chips: `https://www.phy.bnl.gov/twister/cets/{larasic|coldadc|coldata}/<chip-serial>/`
- Any file under the QC mirror (reports, plots, run dirs): `https://www.phy.bnl.gov/twister/static/cetsdata/femb/<path relative to the QC root>` (i.e. the `bnl/...` part)

In Sources, give the web link as the primary reference with the local path alongside for in-terminal use.

### 6. Save the report

After presenting the diagnosis, save it (without being asked) to `analysis/` (gitignored) as `<run-date>_FEMB-<serial>_<short-slug>_<model-slug>.md` — e.g. `analysis/2026-03-27_FEMB-00032_LN-QC_t5-noise-fail_opus-4-8.md`. The model slug comes from the `model` field below (strip the `claude-` prefix); it keeps reports from different models side by side instead of overwriting. Same content as presented, plus a header line with the run path and diagnosis date, and a cost footer:

```bash
T=$(ls -t ~/.claude/projects/*/*.jsonl | head -1)   # live session transcript
jq -s --arg since "<START from §0>" '[.[] | select(.timestamp >= $since) | .message | select(.usage != null)]
  | {model: ([.[].model] | unique), output: ([.[].usage.output_tokens] | add), input: ([.[].usage.input_tokens] | add),
     cache_read: ([.[].usage.cache_read_input_tokens] | add), cache_write: ([.[].usage.cache_creation_input_tokens] | add)}' "$T"
```

Cost estimate — USD per million tokens, by model family; adjust here if prices change (dollar signs deliberately omitted: a literal `$` followed by a digit gets eaten as a positional-arg reference when the skill prompt is expanded). If `model` returns more than one ID (mid-run model switch), price each segment by its own model — re-run the jq with `select(.model == ...)` per model — and note the switch in the footer.

| model | input | output | cache read | cache write |
|---|---|---|---|---|
| `claude-opus-5` | 5 | 25 | 0.50 | 6.25 |
| `claude-opus-4-*` | 5 | 25 | 0.50 | 6.25 |
| `claude-sonnet-4-*` | 3 | 15 | 0.30 | 3.75 |
| `claude-haiku-4-*` | 1 | 5 | 0.10 | 1.25 |

Footer format (elapsed = now − §0 timestamp; $ = tokens × rate, rounded to cents):

```
---
*Generated by `/ce-diagnose` with `<model>` in <Xm Ys>.*

| | output | input | cache read | cache write | total |
|---|---|---|---|---|---|
| tokens | <N> | <N> | <N> | <N> | |
| cost | $<x.xx> | $<x.xx> | $<x.xx> | $<x.xx> | **$<x.xx>** |
```

### 7. Render the PDF

After the markdown is final (footer included), render it to `analysis/pdf/` under the same basename — this is the shareable copy, so the embedded plots must come through:

```bash
cd analysis && mkdir -p pdf && pandoc <report>.md -o pdf/<report>.pdf \
  --pdf-engine=xelatex --resource-path=. \
  -V geometry:margin=1in -V colorlinks=true -V linkcolor=blue -V urlcolor=blue
```

`--resource-path=.` is what resolves the relative `waveforms/...` image links. Check the result (`pdfinfo <pdf>` — page count and a file size in the hundreds of KB mean the PNGs embedded) and give the user both paths.

Stay in the conversation — the user will ask follow-ups. Do not write diagnoses into the database or the run directories.
