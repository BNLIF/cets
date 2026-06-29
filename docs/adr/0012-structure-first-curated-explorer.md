# Structure-first, curated DUNE HWDB Explorer with drill-in navigation

status: accepted

The explorer becomes a **structure-first** navigator over a **curated** slice of
the DUNE hardware tree. We mirror the full structure (System → Subsystem →
Component Type) **including empty nodes**, overlay a YAML-defined grouping
(Region → Family → System), and navigate it as a **drill-in file explorer** with
a synced, path-following **sidebar tree** — every node deep-linkable by URL.
This supersedes the leaf-first tree and the hard-coded `is_fdvd_system`
whitelist of [[0010-fd-vd-component-dashboard-over-hwdb-hierarchy]]; it keeps the
standalone app, FNAL login, and two-zone guard of
[[0011-explore-standalone-app-fnal-login]] unchanged. The site is renamed
**DUNE HWDB Explorer**.

## Context

ADR-0010 built the tree **bottom-up from component-type leaves**
(`ComponentTypeNode`), so a system with no component types in HWDB simply
vanishes. A live audit (2026-06-29, `list_systems`) showed this biting: of the 9
whitelisted FD-VD systems, only 5 have component types today — **FD-VD PDS (54),
CI (58), Calibration (59), HVS (80)** are registered upstream but empty, so they
never appear, even after a refresh. The audit also showed the real top-level
shape: 41 systems across FD-VD, FD-HD, ND, shared FD, facilities, computing, and
prototypes — far more than the flat `FD-VD *`/`FD CE` string match expressed,
and some are placeholders/stalled that we do **not** want to surface.

A clickable prototype confirmed the target UX: browse the org tree as folders,
open any node (empty or not), with a collapsible sidebar tree that expands only
along the path you've clicked.

## Decision

- **Mirror the structure, not just leaves.** Generalize the leaf-only model into
  a structural node mirror covering **System, Subsystem, and Component Type**,
  with empty intermediate nodes stored as real rows. Navigation reads the mirror
  (fast, FNAL-free; CETS members browse without a link). The test/component
  event tables are unchanged — they key to component-type leaves and still drive
  the two plots.
- **Curated browse via `explore/curation.yaml`.** The YAML is the source of
  truth for what is navigable: **Region → Family → member system ids**, with
  display names/order. Only curated systems are browsable and synced; HWDB
  systems not in the YAML (placeholders/stalled) are excluded. Families/regions
  declared but not yet browsable render **dimmed** ("in HWDB · not curated") so
  the audit→curate loop has a visible home rather than silently hiding work.
  Retires `is_fdvd_system`.
- **Region/Family are presentation, not mirrored.** They come from the YAML and
  wrap the mirrored system rows at render. The mirror stays a faithful copy of
  HWDB's `systems → subsystems → component-types`; the YAML never enumerates
  subsystems/types (those churn), keeping the file small and stable.
- **Family-flatten rule.** A family that maps to exactly **one** HWDB system
  collapses that system tier (e.g. `FD CE` → its subsystems directly), so the
  path never repeats a name (`Far Detector › FD CE › LArASIC › …`). Multi-system
  families (FD-VD) keep the system tier.
- **Navigation: drill-in file explorer + synced sidebar tree.** A breadcrumb +
  folder grid of child nodes; a component-type leaf opens the detail panel (the
  two plots + meta + HWDB part-id link). A collapsible left **sidebar tree**
  expands lazily — only along the current path — and is kept in sync with the
  body. Both ride one URL route.
- **Deep-linkable URLs.** Every node has a stable path URL
  (`/explore/<region>/<family>/<system>/<subsystem>/<part_type_id>`, flattened
  families omit the system segment), so links are shareable and the browser
  Back/Forward buttons work. The old `/explore/?node=<ptid>` keeps redirecting.
- **Manual refresh + periodic audit.** Refresh (button / `sync_hierarchy`) walks
  the curated systems into the structure mirror, including empties. `list_systems`
  is the periodic **audit**: it reports systems in HWDB but not curated (and
  curated-but-gone), so curation changes are deliberate, not automatic.
- **Data sync stays lazy per leaf** (ADR-0010/0008): opening a component type
  syncs its events on first visit; curated-but-huge systems cost nothing until
  visited.

## Consequences

- New structural node model + migration. The mirror is a disposable cache
  (rebuilt by refresh), so the model change carries no precious data
  ([[0007-hwdb-mirror-separation]], Path B of
  [[0011-explore-standalone-app-fnal-login]]).
- `curation.yaml` is a new maintained artifact. The audit detects drift, but
  adding/removing a system is a deliberate human edit — a CETS teammate must
  curate a newly-relevant system before it appears (the deny-by-default analogue
  for content).
- Refresh is a heavier walk than before (it records systems/subsystems even when
  empty), but it's manual and infrequent.
- Routing moves from a `?node=` query to path segments; one redirect preserves
  old links. The sidebar + drill-in share a single route so they can't drift.
- ADR-0010's leaf-first tree and `is_fdvd_system` are superseded; its mirror
  philosophy, lazy/incremental event sync, and physics-date resolver carry over.
