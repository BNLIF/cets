# 15. Assembly tree on the part page (read-only Executive Summary)

Date: 2026-06-30

## Status

Accepted

## Context

The Dash dashboard's "Executive Summary" tab takes a top-level PID, recursively
walks its subcomponents, and renders the full assembly tree with each node's
**Status**, **Certified** (`certified_qaqc`) and **Uploaded** (`qaqc_uploaded`)
flags. Wrapped around that read-only tree is a *write* workflow: a sign-off
sequence (signatures), PDF generation, upload-to-HWDB, and a QR phone scanner.

Our part page (ADR-0014) already shows a part's direct subcomponents as a flat
list — part id, type, functional position — with no QC status and no way to see
deeper than one level.

## Decision

Grow the part page's subcomponents section into a **recursive assembly tree**,
the read-only half of the Dash Executive Summary. Each node shows Type,
Position and **Status**, read live from its component record. We **exclude the
sign-off / PDF / scanner write workflow** — consistent with the read-only stance
of the whole explorer (ADR-0013).

The `certified_qaqc` / `qaqc_uploaded` flags the Dash tab also shows were
initially included, then **dropped**: in practice they are unset for
essentially every component (they only flip via the excluded sign-off workflow),
so the columns were a wall of ✗ that carried no information. Status alone is the
useful per-node signal.

The tree **lazy-loads by level**, not eagerly. Building a full tree costs two
API calls per node (subcomponents + the component record for its status), so a
large assembly would be hundreds of calls on one page render. Instead:

- `part_detail` fetches the **direct** children and their status server-side (the
  headline glance), capped at `_STATUS_FETCH_CAP` children — beyond the cap,
  children render without a status rather than stalling the page.
- Deeper levels load on demand: clicking a node's caret hits
  **`/explore/assembly/<part_id>/`** (FNAL-gated JSON) for that node's children.

## Consequences

- The page stays fast on render; cost scales with how far the user expands.
- Status is never mirrored — always live, so it can't go stale, but the column
  degrades to bare ids if HWDB is slow/unreachable (best-effort per child, like
  the rest of the live detail).
- The QC sign-off remains entirely in the Dash tool.
