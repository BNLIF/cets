# `explore` — HWDB Explorer

A **read-only** web explorer for DUNE detector hardware, built on a local mirror
of the [DUNE Hardware Database](https://dune.github.io/computing-HWDB/) (HWDB).
It answers "what hardware exists, how is it assembled, and how far along is QC?"
without ever writing to HWDB.

- **Mounted at** `/hw/` (URL namespace `explore`; old `/explore/…` links 301 to
  `/hw/…`). `/hwdb/` is the separate write/API app.
- **Read-only**: browsing reads the mirror; live detail reads HWDB through a
  per-request FNAL bearer. Nothing here creates or edits HWDB records.

## What you can do

| Page | URL | What it shows |
|------|-----|---------------|
| **Overview** (home) | `/hw/` | The whole curated tree in one expandable view — Region → Family → System → Subsystem → component type. Grey = no components, green = fully synced. "Refresh hierarchy" button. |
| **Browse** | `/hw/browse/…` | The same tree as drill-in cards (one level per page) with breadcrumbs and roll-up counts. |
| **Component type** (leaf) | `/hw/<region>/<family>/[<system>/]<subsystem>/<part_type_id>` | Per-type detail: components-updated & tests-recorded time-series charts, a **component breakdown** (status / manufacturer / institution bar charts), and a paginated table of every part. Sync buttons (Sync new / Shallow re-sync / Full re-sync). |
| **Part** | `/hw/part/<part_id>` | Any single part, live from HWDB: item facts, latest-per-type test summary, a recursive **assembly tree** (subcomponents with QC status, lazy-expanded), specifications, attachments (thumbnails + download), location timeline. A shipping box additionally shows its shipment lifecycle. |
| **Shipments** | `/hw/shipments/` | Every box across curated shipping types — in-transit / delivered, latest location, contents. |
| **Search** | `/hw/search/` | Instant search over the mirror (component types + parts by id/serial). Also the header search-as-you-type box. |

Every page carries the **curated hierarchy sidebar** (collapsible via the ☰
toggle, state persisted).

## Data model (`models.py`)

The mirror is deliberately **light** — it stores structure and activity, not raw
measurements. `test_data` payloads are never mirrored; they're fetched live on a
part page when needed.

- **`HierarchyNode`** — the tree skeleton (system / subsystem / component-type
  levels) with per-type component & test counts and sync timestamps.
- **`HwdbComponentEvent`** — one row per component: `part_id`, mint/updated
  dates, `serial_number`, `created_by`, and the categorical facets `status` /
  `manufacturer` / `institution` (all pulled from the detail record the sync
  already fetches).
- **`HwdbTestEvent`** — one row per test (type name + date) behind the
  tests-over-time chart.
- **`ShipmentItem`** — one shipping box (latest location + contents count).
- **`HierarchySyncState`** — singleton tracking the last hierarchy refresh.

> Rows synced before a field existed carry it blank; a **Full re-sync** of a
> type repopulates `part_id` / `status` / `manufacturer` / `institution`.

## Curation (`curation.yaml`)

The source of truth for *what is browsable*: `Region → Family → member HWDB
system ids`. Only systems under a browsable family are walked and shown;
`curated: false` families/regions render dimmed as "not curated" placeholders. A
family owning a single system (e.g. FD CE) flattens the system tier. Keep region
/ family `key`s stable — they're the URL slugs.

Audit against live HWDB with `python manage.py list_systems` (and
`list_shippable` for shipping-box candidates).

## How it fits together

- **`navigation.py`** — resolves URL trails to nodes, builds the drill-in cards,
  the sidebar tree, and `curated_tree()` (the Overview data).
- **`hierarchy.py` / `events.py`** — sync the skeleton and the component/test
  events from HWDB production (streamed, incremental / shallow / full modes).
- **`shipments.py`** — shipment (latest-location) sync + box detail helpers.
- **`parts.py`** — the live per-part detail engine (facts, tests, assembly tree).
- **`queries.py`** — chart aggregations (time-series + component breakdowns).
- **`auth.py` / `middleware.py`** — FNAL device-flow session login + the
  "sign in as a CETS user" gate.
- **`views.py` / `urls.py`** — the pages above.

## Auth & syncing

- Read pages are **session-login gated** (`fnal_login_required`); the only login
  is FNAL device flow (ADR-0011).
- Live HWDB reads (part detail, image proxy, sync) mint a **per-request FNAL
  bearer** (`mint_for`); an unlinked user is bounced to the link page.
- Syncs read the **production** HWDB tree (canonical) regardless of the session
  instance, and stream progress to the browser. The dev server does **not**
  auto-apply migrations — run `python manage.py migrate explore` after model
  changes.

## Design decisions

See the ADRs at the repo root:

- **0010** — FD-VD component dashboard over the HWDB hierarchy (the plots).
- **0011** — standalone `explore` app + FNAL login.
- **0012** — structure-first curated explorer (`curation.yaml`, the tree).
- **0013** — shipment tracker on shipping-type leaves.
- **0014** — generic part detail page (box page as a specialization).
- **0015** — assembly tree on the part page (read-only Executive Summary).
