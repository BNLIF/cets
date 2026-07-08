# 16. Hierarchy chart: semantic spec + generated layout overlay + mapping overlay

Date: 2026-07-06

## Status

Accepted

## Context

Hajime asked for an interactive version of the FD-VD detector hierarchy chart
(the "FD-VD Complete detector (v4)" page of a consortium-maintained PowerPoint,
circulated as a PDF export): clickable component-type boxes with HWDB detail,
zoom/pan, fixed layout, read-only for users. HWDB has no type-level topology to
derive the chart from — the PPT/PDF **is** the semantic source. Consortia will
keep updating it (new PDF exports), and most box types are not registered in
HWDB yet.

Two designs were tried and rejected in one day (#55–#57):

1. **Hand-maintained exact coordinates** — transcribe every box/arrow position
   into the spec. Rejected as churn-heavy: any slight shift in the next PDF
   export invalidates every coordinate by hand.
2. **Pure computed layout** — a coordinate-free semantic spec laid out by a
   house algorithm (parent above indented child stack). Stable, but a
   side-by-side review of the render against the PDF showed physicists would
   lose spatial recognition: they receive the PDF, and the on-screen chart must
   look like it.

## Decision

Split each chart across **three YAML files** in `explore/chart_specs/`, with
different provenance, joined by stable **node id** slugs (labels duplicate —
two "Adapter board (12)" boxes are different types):

- **`<id>.yaml` — semantic spec, hand-curated.** Nodes (id, label, fill,
  band, note), edges (`from` child → `to` parent; `kind: cable` renders a
  routed arrow instead of a bracket), bands. Never overwritten by tooling;
  transcription uncertainties live as comments at the end of the file.
- **`<id>.layout.yaml` — geometry overlay, generated.**
  `manage.py extract_chart --layout` pulls box positions, band strips and
  loose annotation texts from the consortium chart — .pptx (stdlib) or PDF
  (PyMuPDF, dev-only dependency); both emit the same 1920x1080 pt coordinates,
  so one can cross-check the other. Regenerated wholesale on each chart
  update and reviewed as a diff.
- **`<id>.mapping.yaml` — hand-curated.** Node id → Component Type ids, per
  instance (prod/dev), FD-VD only. Grows as consortia register types;
  `manage.py audit_chart_mapping` reports stale/unknown entries and
  paste-ready fuzzy-matched candidates (advisory only, never writes).

Rendering: `explore/charts.py` builds an inline SVG server-side — overlay
positions plus orthogonal edge routing in the PDF's idiom (the house layout
remains the fallback for charts without an overlay). Vanilla-JS viewBox
pan/zoom; clicking a box opens a popup fed by the mirror-only
`/hierarchy/summary/` endpoint; an "HWDB coverage" toggle fades unmapped boxes
(off by default so the chart matches the PDF).

## Consequences

- **A chart update costs one command + a diff review** (`extract_chart --layout`);
  the spec and mapping only churn on real topology or type changes.
- Unmapped boxes are first-class: honest "not registered yet" popup, coverage
  toggle, and the audit command's candidate list drive the curation loop.
- The popup shows counts + status breakdown only — no per-item listing (a type
  can hold thousands of parts); the Type View page is the browse surface.
- Chart pages stay FNAL-free and mirror-only (the ADR-0007 stance): rendering
  reads YAML + `HierarchyNode`, never HWDB.
- Multi-chart-ready: one file set per chart id; consortium charts or a v5 drop
  in beside `fd-vd-v4` without code changes.
