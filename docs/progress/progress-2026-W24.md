# CETS Progress Report — 2026-W24

**Period:** 2026-06-01 → 2026-06-08
**Repo:** `BNLIF/cets` — Django tracking system for DUNE cold-electronics (CE) hardware

---

## Executive Summary

This week closed the HWDB-mirror loop and stood up an AI diagnosis capability.
The `/hwdb/dashboard/` now mirrors the production Hardware Database for all three
chip families (LArASIC, ColdADC, COLDATA) and surfaces a consistency check that
flags chips BNL has cold-tested but not yet uploaded. In parallel, the
`ce-diagnose` skill (plus a `ce-video` companion) moved in-repo, giving QC-failure
triage a knowledge-base-backed agent. Seven issues closed; **~8k lines shipped
across 17 commits**.

---

## What Was Built

### HWDB Dashboard — full chip-family mirror

| Issue | Deliverable |
|-------|-------------|
| #23 | ColdADC sync end-to-end into the `HwdbChip` mirror |
| #24 | COLDATA card + Sync action on the dashboard |
| #25 | LArASIC card and sync rewire |
| #27 | LArASIC consistency-check (Δ between BNL-tested and HWDB record) |
| #26 | Force full re-sync (bypass skip-known-serials) |
| #12 | hwdb view redesign — nav placement + what-to-show design grill (human) |

**Result:** `/hwdb/dashboard/` is now the single pane for HWDB state — one card per
chip family, each independently syncable, with a consistency check that makes the
"tested-but-not-uploaded" gap visible instead of silent.

### QC-Failure Diagnosis — agent + knowledge base

| Issue | Deliverable |
|-------|-------------|
| #28 | Host the `ce-diagnose` Claude Code skill in-repo (moved from `ce-workflow`) |

**Result:** `/ce-diagnose` maps a run dir / report file / FEMB serial to the fault
taxonomy, checks test & repair history in the cets db, escalates to report plots
when ambiguous, and writes a saved report with a cost footer and web links. A
`/ce-video` companion renders a diagnosis session into a ~20s terminal demo.

### FEMB & navigation UI — shipped without standalone issues

These landed this week as direct commits (no separate issue):

| Commit | Deliverable |
|--------|-------------|
| `0beb591` / `04ea15e` | Per-board notes — append-only note entries via the web UI + a Notes column on the list |
| `fb79118` | FEMB detail Result column — pass/fail per test |
| `e72faa7` | FEMB list Chips + Repairs columns |
| `8ab7990` | Top-nav Others landing page + selection-safe row clicks |
| `6f32945` | HWDB upload csv-pending state + HWDB deep-links on the tray page |

**Result:** the FEMB list and detail views now carry chip counts, repair counts,
per-test pass/fail, and operator notes inline — the board's QC story is legible
without drilling into raw reports.

### Ingestion hardening

| Commit | Deliverable |
|--------|-------------|
| `fc733f2` | RTS import: don't drop sessions on Time-name collision in `--since-db` |
| `bf15b84` | Test ingest: full scan + ignore list + relaxed FEMB regex |
| `9f5a586` | Test fix: neutralize `FORCE_SCRIPT_NAME` so view tests resolve at `/` |
| `b14d4bc` | Diagnosis docs: corrected db table names + confirmed chip-index mapping |

---

## Architecture Overview

```
                          Browser (HTMX + Alpine.js + Bootstrap)
                                        │
                       ┌────────────────┴────────────────┐
                       │      Django (gunicorn/systemd)   │
                       │      Apache reverse proxy /cets  │
                       └────────────────┬────────────────┘
                                        │
        ┌───────────────┬───────────────┼───────────────────────┐
        │               │               │                       │
   ┌────▼────┐    ┌─────▼─────┐   ┌──────▼──────┐         ┌──────▼──────┐
   │  core   │    │   hwdb    │   │    users    │         │  AI skills  │
   │         │    │           │   │             │         │             │
   │ FEMB    │    │ dashboard │   │ session     │         │ ce-diagnose │
   │ LArASIC │    │ sync.py   │   │ auth        │         │ ce-video    │
   │ ColdADC │    │ upload/   │   └─────────────┘         └──────┬──────┘
   │ COLDATA │    │ fnal/     │                                  │
   │ CABLE   │    │ HwdbChip  │                            knowledge base
   │ repairs │    │ mirror    │                            + fault taxonomy
   └────┬────┘    └─────┬─────┘
        │               │
   ┌────▼─────────┐ ┌───▼──────────────────────┐
   │ mgmt cmds    │ │ DUNE HWDB REST API        │
   │ RTS / OCR /  │ │ (prod + dev instances)    │
   │ test ingest  │ │ FNAL vault OIDC device    │
   └────┬─────────┘ │ flow → per-request bearer │
        │           └───────────────────────────┘
   ┌────▼──────────────────────┐
   │ SMB shares (read-only)     │
   │ RTS_DIR / FEMB_OCR_DIR /   │
   │ QC report roots            │
   └────────────────────────────┘
```

---

## Key Technical Decisions

### HWDB mirror lives in its own table (ADR-0007)

**Decision:** track upstream HWDB state in a dedicated `HwdbChip` table, separate
from the BNL-tested chip models (`LArASIC`, `ColdADC`, `COLDATA`).

**Why it matters:** the two sources can legitimately disagree — BNL may have
cold-tested a chip whose results aren't uploaded yet.

**Concrete benefit:** the dashboard consistency check (#27) can show the gap
directly instead of clobbering local truth with whatever HWDB returns.

### Skip known serials on incremental sync, with a force-full escape hatch (ADR-0008, #26)

**Decision:** each chip is fetched from HWDB exactly once; subsequent syncs skip
serials already mirrored, with a "force full re-sync" button to override.

**Why it matters:** the HWDB API is slow and rate-sensitive; re-querying thousands
of known chips on every sync is wasteful.

**Concrete benefit:** routine syncs touch only new serials; the escape hatch covers
the rare case where an upstream record changed underneath us.

### Test-timestamp fallback for empty-datasheet placeholders (ADR-0009)

**Decision:** read a chip's test date from `test_data["Test Date"]` when present,
otherwise fall back to HWDB's record-creation stamp.

**Why it matters:** upstream institutions sometimes upload empty-datasheet
placeholders with no embedded test date.

**Concrete benefit:** the mirror records a usable date for every chip instead of
dropping placeholder records on the floor.

### Diagnosis skill hosted in-repo with a versioned knowledge base (#28)

**Decision:** move `ce-diagnose` out of the separate `ce-workflow` repo and into
`cets` under `.claude/skills/`, alongside `docs/knowledge/` and
`docs/agents/diagnosis.md`.

**Why it matters:** the skill's accuracy depends on data-geography and db-schema
facts that live in this repo and drift with it.

**Concrete benefit:** the fault taxonomy, QC procedures, and db-table mapping
version together with the code they describe — confirmed this week by the
table-name and chip-index corrections in `b14d4bc`.

### Ingestion is resilient to Time-name collisions (`fc733f2`)

**Decision:** `--since-db` RTS import no longer drops sessions that share a `Time_`
directory name.

**Why it matters:** colliding run-dir names were silently dropping valid sessions.

**Concrete benefit:** incremental RTS imports keep every session instead of losing
the ones that collide.

---

## Metrics

| Metric | Value |
|--------|-------|
| Issues closed this week | 7 (#12, #23–#28) |
| Commits this week | 17 |
| Lines changed this week | +7,993 / −316 |
| Total commits (repo) | 111 |
| Django apps | 3 (`core`, `hwdb`, `users`) |
| ADRs (cumulative) | 9 |
| HWDB test modules | 10 |
| AI skills in-repo | 2 (`ce-diagnose`, `ce-video`) |

---

## Current System Capabilities

1. Track FEMBs and their mounted LArASIC / ColdADC / COLDATA / CABLE chips, with full repair-iteration history keyed by `(type, position)`.
2. Ingest QC test results and OCR'd parts lists from SMB shares via management commands; resilient to Time-name collisions and FEMB-regex variation.
3. Browse FEMB list/detail with inline chip counts, repair counts, per-test pass/fail, and append-only operator notes.
4. Sync all three chip families from the DUNE HWDB into a local mirror, per-family or force-full.
5. Surface BNL-tested-but-not-uploaded chips via the `/hwdb/dashboard/` consistency check.
6. Upload LArASIC QC results to HWDB (serial or 10-worker parallel path), per-session FNAL auth, prod/dev toggle.
7. Diagnose a QC failure from a run dir / report / serial with `/ce-diagnose`, and render the session to a demo video with `/ce-video`.

---

## Open / Next

- **HWDB RTS-upload schema is thin** — the HWDB RTS test schema is only 4 fields; the right shape for uploading RTS results is still an open design question (per project notes).
- **Phase-3 HWDB writes unblocked** — all DEV write primitives (mint / create-item / submit-test) are green for the linked account; production write path beyond LArASIC QC is the next frontier.
- **#12 redesign was closed as a design grill** — the agreed hwdb nav/layout decisions still imply follow-up UI work.
- **Diagnosis knowledge base is young** — fault taxonomy and QC procedures will need expansion as `/ce-diagnose` meets more real failures.
