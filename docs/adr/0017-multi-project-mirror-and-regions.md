# 17. Multi-project mirror: project in the node key, synthetic lazy regions

Date: 2026-07-24

## Status

Accepted

## Context

The explorer only knew HWDB project "D": the hierarchy walk was hardcoded to
`systems/D`, and every mirror row / navigation query treated `system_id` as a
global key. Hajime asked for at least two more projects, "Z" and "L" (#71).
System and subsystem ids are **per-project** in HWDB — a Z system 5 is not D's
system 5 — so simply walking more projects would clobber and cross-pollute the
mirror and the sidebar aggregations.

Nothing is known upfront about the content of Z/L (no curation exists for
them), and they may be small or empty on a given instance.

## Decision

- **`project` joins the `HierarchyNode` identity.** System/Subsystem rows are
  upserted and queried by `(instance, project, level, system_id[,
  subsystem_id])`. Component-type leaves stay keyed by `part_type_id`, which
  already embeds the project letter and is globally unique. Sidebar/tree
  aggregations key by `(project, system_id, …)` tuples.
- **Extra projects are curated as a list, not a taxonomy.** `curation.yaml`
  gains `extra_projects: [{id: Z, name: …}, {id: L, name: LBNF}]` per
  instance. The full refresh records each extra project's systems
  **names-only** (one `systems/{P}` call each) and each system walks lazily on
  first visit — the overflow (#49) machinery reused as-is (`sync_system` takes
  a `project`, the walk URL carries `?project=`). A failed `systems/{P}`
  listing warns and keeps the project's previous rows.
- **Each extra project renders as a synthetic region** (key `Z`) built from
  the mirror at render time, one flattened single-system family per system —
  the same dict shape as `overflow_region`, so cards, crumbs, sidebar and deep
  links (`/hw/Z/57/2/Z05700200042`) work unchanged. A project with nothing
  mirrored yet renders nothing until the next refresh.
- **Projects are display peers, with real names.** A 2026-07-24 spike on
  `GET projects` showed Z and L are *not* under DUNE: dev has `D` DUNE,
  `Z` "Sandbox", `L` "LBNF" (+ `a` "Dummy a", deliberately skipped); prod has
  `D`, `Z` "Test Project", `L` LBNF (empty). So the home tree and sidebar
  group the D regions under a `DUNE (D)` project node with the extra-project
  regions as its **siblings**, labeled from the yaml names — `Sandbox (Z)`,
  `LBNF (L)` — via `curation.project_label()`. Names are yaml-pinned per
  instance (not fetched live) and re-audited with the spike when upstream
  renames; URLs carry only the region key, so labels can change freely.
  The overview page renders the projects in parallel (no root row, like the
  sidebar), and a `test: true` yaml flag (Z on both instances) keeps a
  sandbox project visible in the tree but out of the overview stats.
- **Shipping subsystem selectors stay project-D.** The `"86.990"`-style
  curation selectors decode D-prefixed part-type ids only; other projects'
  shipping types must be listed as explicit part-type ids.

## Consequences

- No schema migration: the `project` column existed (default `"D"`); only its
  role changed from annotation to key component. Existing D rows match the new
  lookups as-is.
- Curating a real taxonomy for an extra project later (named regions/families
  in the YAML with a `project:` key) is possible: `region_project()` already
  scopes every navigation read by the region's project.
- `manage.py list_systems --project Z` audits an extra project's systems the
  same way it audits D's.
