# Shipment tracking on shipping-box leaves: mirror latest, live detail

status: accepted

The explorer gains a **Shipment Tracker**, the first of the DUNE Dash dashboard's
features brought into our app (per Hajime, HWDB maintainer, 2026-06-29). A
"shipping box" is **not a new entity** — it is an ordinary component-type **leaf**
already in our tree (e.g. `D08120200001` "CE Shipping box", under FD CE ›
CE Shipping Box), whose **items are physical boxes**. Each box carries two
HWDB relationships: a **location history** (`/components/{pid}/locations`) and a
**manifest** of subcomponents (`/components/{pid}/subcomponents`). We surface
both as a **Shipments panel on the shipping-type leaf**, identified by a curated
`shipping_types` allowlist. We **mirror only each box's latest location**; the
**full location timeline and manifest are fetched live** from HWDB prod when a
user expands a box. This follows the curated/reinterpret stance (A) of bringing
Dash features in — not a literal port — and extends, without superseding,
[[0012-structure-first-curated-explorer]].

## Context

Hajime asked us to grow the explorer toward the Dash dashboard's three tabs
(Plots, Shipment Tracker, Binary/Test Downloader). He praised our **curated
default plots** over Dash's generic "plot-anything" engine, so the stance is to
**reinterpret** Dash features in our opinionated, no-typing UX — not replicate
its type-a-PID flows. Shipment was chosen first.

Studying the Dash code clarified the domain:

- There is **no "Box" object** in HWDB. Dash's "Box PID" column is just
  `item.pid`; "box" is a label for items of a shipping-container component type.
- A box means two things: **where it is/has been** (location events: `arrived`,
  `location`, `creator`, `comments`) and **what's inside** (subcomponents at
  named functional positions — what `ShippingLabel.py` prints on the crate
  label). The journey alone ("a box moved") is far less useful to DUNE ops than
  journey + contents ("the crate with these CRP parts arrived at CERN").
- Dash fetches everything **live** (all items of a type, then per-item locations,
  N+1 behind a threadpool). Our explorer's standing rule is mirror-backed,
  manual-refresh rendering (ADR-0012). Mirroring **all** location history for
  every box is more than we need: the list view only wants "where is each box
  now," and full history is read rarely, one box at a time.

We do not yet know which component types are shipping boxes beyond the one
example, nor the exact status semantics (Dash infers in-transit/delivered from a
location `id`, which the REST API docstring calls an internal oid "not of any
particular use" — a contradiction to resolve before committing schema).

## Decision

- **Shipping box = curated leaf, no new entity.** A box is an item of a
  component-type leaf. Tag shipping leaves with an explicit `shipping_types:`
  **allowlist of `part_type_id`s** in `explore/curation.yaml` — not name-matching
  ("*Shipping Box*"), which is fragile. The list is populated from the spike.
- **Spike first, narrow then broad.** Before any schema: (1) a read-only probe of
  the anchor `D08120200001` dumps real `/locations` + `/subcomponents` JSON and
  settles the **status-inference** question; (2) a `list_shippable` audit sweeps
  curated systems for component types whose items carry location data, so
  `shipping_types` is **data-driven, not guessed** — same audit→curate loop as
  `list_systems`.
- **Mirror latest location only.** A small `ShipmentItem` row per box —
  `part_type` leaf FK, box `pid`, **latest location**, **last-arrived date**,
  status, `synced_at` — populated by a **streaming "Sync shipments" action** on
  the leaf (the `StreamingHttpResponse` progress pattern already used for
  hierarchy and test-event sync). The list view reads the mirror: "where is every
  box right now," **zero live calls**.
- **History + manifest are live on expand.** Opening one box fetches its **full
  location timeline** and **manifest** (subcomponents → PID, component-type name,
  functional position) **live from HWDB prod** — 2 calls for that one item,
  always fresh, via the existing per-request bearer mint ([[0002-per-request-bearer-minting]]).
  Neither is mirrored.
- **Panel on the leaf.** A shipping-type leaf renders a **Shipments panel**
  (items table → expand to timeline + manifest) **in place of the test-plot
  cards** — a shipping box has no meaningful tests. Discovery rides the existing
  tree + sidebar; no free-typing, no new top-level nav. A cross-type "what's
  moving" ops dashboard is deferred to a later stance-C iteration.
- **Dash UI features reflected, not its mechanics.** Carry over what serves
  users: summary counts (total / in-transit / delivered), a per-box status with
  color cue, latest location + shipped/received dates, and the expandable
  detail (timeline + manifest/QA-QC info). **Drop** Dash's type-a-PID input
  (replaced by curated leaves) and its **Ship/Receive write workflow** (the
  explorer is read-only; minting/POSTing locations stays in CETS/HWDB tooling).

## Consequences

- **A deliberate carve-out from ADR-0012's "render never hits live HWDB" rule:**
  the box-detail expand *does* call HWDB prod at render time. Scoped to on-demand
  detail only (one box), it needs prod reachable and a valid bearer — every
  explore user is FNAL-authed, so this holds — and the detail can error/timeout
  independently of the (mirror-backed) list. Recorded here so it reads as
  intentional, not drift.
- New `ShipmentItem` mirror table + migration; like the rest of the mirror it is
  a **disposable cache** (rebuilt by sync), carrying no precious data
  ([[0007-hwdb-mirror-separation]]).
- `shipping_types` is a new curated artifact in `curation.yaml`; a newly-relevant
  shipping type must be curated (after the audit surfaces it) before it appears —
  the same deliberate-human-edit gate as system curation.
- Status semantics are **unresolved until the spike**; the `status` field shape
  may change once real `/locations` data is seen. The narrow spike exists to de-risk
  exactly this before the schema lands.

## Parking lot — HWDB "Updated" field

Hajime noted HWDB now exposes **Updated** alongside **Created**, but it bumps only
when something on an item's *Item View* changes — **not** when its TestLog
changes. This does **not** affect shipments, but it is a known fidelity caveat
for our existing **component-update charts**, which key off last-updated: a box or
component whose only change was a test upload will not show as "updated." Recorded
here for visibility; addressing it (or requesting an upstream change, as Hajime
suggested) is separate work.
