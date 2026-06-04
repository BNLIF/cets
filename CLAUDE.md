# CETS

Django project for tracking CE (cold electronics) hardware in the DUNE detector.

## Agent skills

### Backlog

Issues live as GitHub issues in `BNLIF/cets`. Use the `gh` CLI. See `docs/agents/backlog.md`.

### Triage labels

Default label vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.

### Diagnosis

QC-failure diagnosis runs via the `/ce-diagnose` skill (`.claude/skills/ce-diagnose/`). Data geography (per-environment QC report roots, db schema, run-dir layout): `docs/agents/diagnosis.md`. Knowledge base (fault taxonomy, datasheets, QC procedures): `docs/knowledge/INDEX.md`.
