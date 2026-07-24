# 18. Cable-end sub-component refs: split at the manifest, skip peers in walks

Date: 2026-07-24

## Status

Accepted

## Context

HWDB's new cabling model (Hajime's JUL/22/2026 slides, #72) links cables to
components through **ENDs and Connectors**. In `/subcomponents` rows this
overloads `part_id` with two suffixed shapes besides the plain PID:

- on the connected component: `<cable PID>.<END name>:<connector #>`
  (e.g. `Z00100300080-00001.FCP Flange:1`) — a forward cable-end mount;
- on the cable's own rows: `<peer PID>.<functional position>` (no trailing
  `:n`, e.g. `Z00100300064-00001.Cold Bottom FCT`) — a back-reference to
  whatever the cable plugs into, **including its own parent**. A cable's
  "sub-components" are its connectivity, not its contents.

END names contain spaces and one cable can mount at many connectors (a
bundle at `Flange:1…8` is one physical item). Every per-part endpoint 404s
on a suffixed ref, so passing them through broke status fetches, part links,
and would have aborted box receiving mid-write. The REST API docs for
cabling are still pending upstream, so the contract may shift.

## Decision

- **Split once, centrally.** `shipments.split_subcomp_ref()` splits a ref at
  the first `.` *only when the prefix is PID-shaped*; `current_manifest()`
  rows carry `part_id` (base PID — every lookup, link, and location post
  uses this), `connection` (the suffix, or None), and `peer` (True when the
  suffix has no `:n` — a back-reference).
- **Item pages show everything.** The Assembly table renders a forward
  ``END:connector`` suffix as a dimmed annotation after the linked base PID.
  A peer row's suffix is its functional position, which the dedicated
  Position column already shows — so it stays out of the Part column
  (Hajime's 2026-07-24 review). A cable's page lists its peers (with live
  status), matching the HWDB UI, and suppresses the "Inside" fact when the
  container is one of those peers: a cable's ``/container`` rows include its
  connections' back-references, so the "newest" one is a single arbitrary
  connector out of many, not a parent (a genuine container — e.g. a shipping
  box, never a peer — still shows).
- **Containment walks skip peers.** `subtree_rows` (the ES contents list)
  drops `peer` rows: keeping them would fold a cable's whole neighborhood
  into the box contents. Forward cable-end mounts stay — recursing into the
  cable yields only peer rows, so the walk terminates; base-PID dedup lists
  a multi-connector bundle once.
- **Documents keep the full ref.** The ES PDF subtree and the checklist
  CSV's `Sub-component PID` re-join `part_id.connection`, since the END and
  connector identify *which* end — same string HWDB shows.
- **Cables are recognized by `category == "cable"`** on the item record (no
  extra call). A cable's page retitles Assembly to *Connections*, renders
  peer rows with an **inert caret** (expanding a peer would loop the lazy
  tree: cable → flange → cable …; the link still navigates), and adds a
  **Cable ends diagram** — the type definition's `connectors` keys arrive
  expanded one slot per connector (`Flange:1`…`Flange:8`), so grouping on
  the END name recovers Hajime's `{END: #connectors}` definition, drawn as
  an SVG fan-out (ends left/right of the PID hub, one dot per connector).
  Past 12 ends the fan-out becomes a very tall spider, so the renderer falls
  back to a compact chip grid (END name + connectors / in-use per chip).
  The diagram headlines the part page full-width above the two columns.
  A cable's reverse rows don't say which of its own connectors a connection
  uses — that lives on the peer's manifest — so the item page reads each
  distinct peer's `/subcomponents` once (capped, best-effort) to annotate
  every connection with "via `END:n`" and to fill the diagram's occupancy
  (solid dot = connected, hollow = free, "k / n in use" per end).
- **The type leaf page draws the same diagram mirror-only.** The hierarchy
  walk mirrors `category` (free — it's in the type list) onto every TYPE
  row, and for cable types fetches the type record once to store the grouped
  `cable_ends` JSON (a failed fetch keeps the previous value; non-cables
  clear it). Leaf render stays live-free; the diagram JS is shared
  (`static/explore/cable-diagram.js`). An unmirrored cable leaf hints to
  re-run the hierarchy refresh (or the system re-walk) rather than fetching.

## Consequences

- `receive_box` now posts arrival locations to base PIDs (previously a
  cable-end row would have 404'd the write and aborted the receiving flow).
- Plain PIDs and non-PID-shaped ids pass through unchanged; if upstream
  renames the suffix grammar, only `split_subcomp_ref` and the `peer`
  heuristic (`:n` = forward) need revisiting.
- Manually expanding a peer row on a cable's page can ping-pong (flange →
  cable → flange…); each step is user-driven and dedup guards the ES walk,
  so no loop can run away.
