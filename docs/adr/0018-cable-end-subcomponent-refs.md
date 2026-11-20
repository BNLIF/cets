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

## Update 2026-11-20: the cable API as released on dev (#223)

Hajime's two emails of November 2026 and a read-only look on dev
(`Z00100300037-00001`, `Z00100300073-00020`, `Z00100300035-00001`, bundle
`Z00100300072-00004`). Prod was not looked at; the older row shape below
is still read.

What dev answers now:

- **Country / institution codes on every id.** `part_id` and
  `parent_part_id` come as `Z00100300073-00020-US186` on the item record,
  the type listing, `/subcomponents` and `/container` rows (there also on
  the nested `container.part_id`). In a cable-end ref the codes sit
  *before* the suffix: `Z00100300035-00001-US186.Flange:7`,
  `Z00100300064-00004-US186.Warm Outer CRP SH`. A per-item GET accepts
  either form; `/tests` refuses the long one (2026-09-28).
- **A cable's own rows** carry `cable_connector` (`"FCP Flange:1"`, the
  cable's END:connector) and **no `functional_position`**; the connected
  item's position is the ref's suffix.
- **A bundle / tray** is a generic item whose positions accept the cable
  type and hold cables by plain PID. It does not appear on the cable's
  `/subcomponents` rows at all. It is the cable's `/container` row and
  its `parent_part_id`. A cable's `/container` no longer lists its
  connections: `Z00100300035-00001`, connected at eight positions, has
  none.

What changed here:

- **The API client strips the codes** wherever it already did for plain
  ids, now also inside a cable-end ref (the suffix is kept) and on a
  row's `container`. `split_subcomp_ref` is unchanged — it never sees the
  codes.
- **`current_manifest`** takes `cable_connector` as the mark of a cable's
  own row: such a row is a peer whatever its suffix looks like (a generic
  type's position may end in `:2`), `via` holds the connector, and
  `functional_position` is filled from the suffix.
- **No call per connected item** on a cable's page when its rows name
  their connectors. Rows of the older shape still get the one read per
  distinct peer.
- **A cable's Connections table has one row per END:connector** of its
  type, in the type's order, a free connector's row empty (Hajime). It is
  a table of its own, without carets; the heading counts connected over
  connectors. A connection with no known connector follows the list.
- **"Inside" reads "Bundle / tray"** on a cable whose container is not a
  shipping box.

## Update 2026-11-20: writing cable links (#224)

Hajime's second email (cable links are written from the non-cable item
only: `<PID>.<END>:<n>` for one end, the plain `<PID>` when the item is the
cable's bundle / tray, `null` to remove) and a write probe on dev with two
new flanges (`Z00100300037-00005`, `-00006`) and the unconnected
`Z00100300035-00002`, all left unlinked again. Prod was not probed.

What dev answers to `PATCH components/<PID>/subcomponents`:

- **It merges.** A position not named keeps what it holds; naming two
  positions and then a third leaves all three linked.
- **A ref with the country / institution codes is accepted**
  (`…-00002-US186.Flange:2`), and so is one without.
- **A complete dict with every ref as read answers "No changes".**
- **A bare PID where a cable end sits is taken, with OK**: the end is
  dropped ("replaces …Flange:7" in the cable's `/container` comment), the
  item becomes the cable's parent — a bundle link. This is what the Link
  items page and the scan link would have done on any write to an item
  holding a cable end, since they rebuilt the dict from base PIDs.
- **Whole cable**: the plain PID makes the item the cable's
  `parent_part_id` and newest `/container` row. The cable's ends can still
  be connected, also to that same item.
- **Refusals**: a connector in use → 409 "The component
  '…-US186.Flange:7' is already in use in '<item>/<position>'"; an END the
  type lacks → 400 "the cable '…' has no end 'Nope:1'"; the whole cable a
  second time → 409 "already in use in …".
- **A cable item cannot be created over the API with the type's empty
  spec template** (`{}` → "A 'specifications' object matching the
  ComponentType difinition is required!"). Not pursued.

What changed here:

- **Still the complete dict, now with refs.** `shipments.position_ref()`
  gives a manifest row back as the write wants it; the Link items page and
  the scan link build their state from it. The checklist link field, the
  linking image map (and a table's link column), the map's unlink and the
  sheet upload already sent each `part_id` back as read, which since #223
  is the ref without codes. Child minting writes only to an item created a
  moment before. Sending the changed positions alone would also do on
  dev; it was left, prod being unprobed.
- **A cable is linked at a position its user names, and is asked for its
  END : connector there** — the type's connectors in order, those in use
  not pickable (two reads: the cable's type, its own rows), or "No END —
  bundle / tray" for the plain PID. That is the PID typed at the
  position's row ("Link here").
- **From the candidate list a cable is linked in one step** (Chao
  2026-11-20): one cable picked by a radio button, the position and the
  END : connector chosen under the list, "Link". That END list is the
  type's, from the mirrored `cable_ends` — no HWDB call, so a connector
  in use is not marked there and HWDB's refusal says where it is used.
  With no END chosen (or no ends mirrored) the position's row asks as
  above.
- **No first free position for a cable.** Ticked candidates, Add by PID
  and a phone scan pick the position themselves and could only write the
  plain PID — a bundle link nobody asked for on a flange. A cable type's
  list has no tick boxes, and the three paths refuse a cable (one type
  read each). A shipping box is excepted: it just holds the cable.
- **Only a plain link stamps the mirror parent.** A cable connected at an
  END stays among the candidates, as HWDB itself keeps its
  `parent_part_id` empty.
- **A cable has no Link items page** (403), and its part page no "Link
  items…".
- **Not changed**: a checklist link field or image-map slot given a cable
  item links its plain PID, as before (open in #222); the image map's
  contents table shows a cable end's whole ref as the item.

## Consequences

- `receive_box` now posts arrival locations to base PIDs (previously a
  cable-end row would have 404'd the write and aborted the receiving flow).
- Plain PIDs and non-PID-shaped ids pass through unchanged; if upstream
  renames the suffix grammar, only `split_subcomp_ref` and the `peer`
  heuristic (`:n` = forward) need revisiting.
- Manually expanding a peer row on a cable's page can ping-pong (flange →
  cable → flange…); each step is user-driven and dedup guards the ES walk,
  so no loop can run away.
