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

## Update 2026-11-20: the Cable connections page, read-only (#226)

Hajime's mock-up (slides 12–20) in the layout Chao picked on #225: the list
under the picture, ten columns folded. `cabling.device_connections()` is
the page's model; `part/<PID>/cables/` shows it, `cables/?pid=` is the way
in for a typed or scanned PID.

- **The page works from an endpoint device, not from a cable.** A cable's
  PID gets one line and a link to its item page.
- **A row per position that takes a cable**: one whose accepted types
  include a cable type (the mirror's category, or the type record for a
  type the mirror lacks), or one that holds a cable end. Numbered in the
  type's order.
- **Other side = what the cable's other ENDs are connected to**, read off
  the cable's own rows. Connectors of one END sit at the same end of the
  cable, so a bundle's eight `Flange:n` are not each other's other side
  (dev's `Z00100300034-00007` listed eight of them in one row before this
  rule). HWDB does not say which END is opposite which, so a cable with
  three ENDs has two other sides. Each other device is listed once with
  its positions; a short cable's other END may sit on the working device
  itself ("this device"). A row of the older shape, with no connector
  named, counts every other connection.
- **Status** (Hajime, slide 15): Available — nothing at the position;
  Connected — a cable end is there; Installed — every END : connector of
  that cable is connected, counted against its type's connectors. A cable
  held without an END ("No END") is a bundle / tray link, not a
  connection, and is not counted.
- **Reads, bounded by the device**: its record, its type, its positions;
  each connected cable's rows once; each cable type's record once (the
  connector count); a type record for an accepted type the mirror cannot
  name. The other side's type name comes with the cable's rows, so no
  other-side item is read until device locations exist (#229). Nothing is
  written to the mirror.
- **The item page links there** when the item holds a cable end, or — on
  an instance open to writes, where its positions are read anyway — one of
  them accepts a cable type by the mirror's word. No read is added for it.

## Update 2026-11-20: connecting and removing on the page (#227)

On an instance open to writes the Cable connections page writes the working
side. Checked on dev with the probe flange `Z00100300037-00006` and the free
`Z00100300035-00002`, both left unlinked again.

- **Connect is one dialog for every free position.** The cable is named by
  a scan, by the pick list of the position's types (mirror rows; its search
  takes a PID or a serial number) or by a typed PID; the page then asks
  HWDB for that cable's END : connector slots (`?slots=<cable>&pos=`: the
  device's type, the cable's type, the cable's own rows) and shows them as
  one choice, those in use not pickable, a single free one chosen already.
  Which END goes here is the installer's to say — nothing tells it until
  the other side is connected.
- **A cable of a type the position does not take is refused before any
  write**, by the dialog's read and again by the POST, naming the expected
  type(s) — the mirror's names, the type record for a type it lacks.
- **Remove empties one position; Remove all asks once and empties every
  position holding a cable end.** A cable held by plain PID (the device is
  its bundle / tray) and every non-cable item stay. The other side is never
  written: it is another item's position.
  Both ask first since 2026-11-23 (Hajime's first try; #233): a row's
  Remove names the position, the cable and its END : connector; Remove all
  is a warning that lists what goes. Cancel holds the focus in both.
  Connect stays grey until an END : connector is chosen.
- **Scanning with a phone** (Chao 2026-11-23): the page's own Scan uses
  the camera of the device it is open on; a phone button beside it, in the
  Connect dialog and at the bundle box, uses the checklists' phone route
  instead — the scanner page opened with `?target=<device>&for=cables`,
  each code queued for the same user and that device, the page polling the
  feed while a box listens and telling the phone where the scan went. A
  scan fills the box as a local scan does (the cable is read and its
  END : connectors offered; a bundle opens). Scans that arrive while
  nothing listens are not placed. In the Connect dialog the choice is kept
  in the browser, so the next Connect listens at once. Not offered for the
  device box: the feed is keyed by an item, and the way in has none yet.
- **The write is Link items' write** (the complete positions, each as
  read, #224), the status rule and the occupied-position check included;
  HWDB's refusal is shown as it comes and the page is read again.
- **Bundle / tray of a cable = its current container** (`/container`, the
  newest row that is not an unmount): the item holding it by plain PID. One
  read per connected cable. The column shows it with the device's other
  rows whose cable sits in the same one ("also at 2"); under 900px it folds
  into the cable's cell.
- **A bundle / tray scanned first offers its cables** (`?bundle=<PID>`):
  the items it holds by plain PID whose type is a cable type, each at the
  free positions that take its type, with the bundle's own position name
  and whether it is connected (here, elsewhere, or free). A position with
  exactly one cable still open — not connected here, a connector free — has
  it filled in when its dialog opens. Nothing is written until Connect.
  Reads: the bundle's positions, each of its cables' rows, a cable type's
  record.
- **Not here**: connecting every free position in one step, swapping two
  cables, and anything on the other side.

## Update 2026-11-20: the type's picture and its editor (#228)

A picture of the endpoint device over the connections list, a numbered
marker on each position. It belongs to the device's **type** and is
prepared once.

- **Stored on the type in HWDB**, as a checklist's pictures are:
  `Cable_map_<type id>.json` among the type's images, the newest version
  read — `{"image_id": …, "slots": [{"label", "x", "y"}]}`, the checklist
  image map's slot shape, `label` a position name, `x` / `y` in percent of
  the picture. The picture is another of the type's images, uploaded
  through the checklist editor's endpoint (`ChecklistImage_<type>_<time>`).
  Another Explorer or tool reads both with the type's image listing.
- **The editor** (`cables/picture/<type id>/`) lists the type's positions
  that accept a cable type, numbered as the page numbers them. A position
  is picked, a click on the picture drops its marker and the next position
  not yet placed is picked; a marker is moved by a drag and removed from
  the list. A stored marker whose position the type no longer has is
  flagged there and can only be removed.
- **Who may save**: anyone on a write instance, HWDB arbitrating by the
  type's roles — as for the type's checklists. The role banner says so
  beforehand, and the page links to the editor only for an account that
  holds one of the roles.
- **The page** shows a marker per slot named like one of its rows, with the
  row's number and status colour; a slot with no row is left off. A marker
  stands for its row: a tap is the row's Connect or View, and each lights
  the other up. A type with no picture shows the list alone.
- **Zoom**: fitted to the width and at most 42% of the window's height;
  − / + / Fit buttons, a two-finger pinch, Ctrl + wheel (a plain wheel
  scrolls the page), a drag to pan once zoomed. Markers keep their size.
- **Reads**: two more per page — the type's image listing and the map
  file. The picture itself goes through the image proxy.
- **Checked against HWDB**: the read side on dev, and — at Chao's word — an
  upload and a save through the editor's own endpoints: a drawn mock-up and
  18 markers on the sandbox type `Z00100300037`, where they stay.

## Update 2026-11-20: device location, labels and Print (#229)

- **Device location**: typed by hand in the page's header and saved in the
  device's Item Specs as `DATA["Device location"]` — the checklists'
  envelope, so the type's spec template must define `DATA` (added on first
  use for an architect, a message for anyone else, as for "→ Specs"
  fields). The save rewrites that one key and sends the rest as read; a
  blank removes it. The key's name is ours until Hajime agrees one. The
  field is shown only where writes are open and the account holds one of
  the type's roles; elsewhere the location is plain text.
- **The other side's location** is read off each other-side device's
  record: one read per distinct device, per page.
- **Cable label**: worked out on every page load, never stored (HWDB has no
  text field on a cable item yet). A cable gets one when it is connected at
  exactly two positions on two different ENDs — two connectors of one END
  sit at the same end of the cable and say nothing of where it goes. One
  line per side, `<device location>.<position>`; as one string the lines
  are joined with `-`. The sides are ordered by the cable's own connector
  names, so either working side gives the same text. A side whose device
  has no location is its position alone, and the label is marked
  incomplete.
- **Bundle label**: `<location>/<location>` when the bundle's cables *on
  this page* all go to one same other device and both locations are saved;
  the two in PID order. The bundle's cables that are not connected at the
  working device are not read, so a bundle split between more than two
  devices is only noticed from a device that sees both.
- **Print**: one dialog for a row, a bundle and "Print labels" (every
  connected row, in row order): label and PID, label only or PID only; the
  PID as the label generator's QR (the item's HWDB address) or bar code
  (the external ID, one record read per item, the bare PID if that read
  fails); the type name on request. A cable with no label prints its PID
  only and is left out of a labels-only sheet. The sheet is one of the
  label generator's (`labels.TEMPLATES`), the layout made for it
  (`cabling.label_layout`): text along the label's longer side, the
  label's lines at one size, a QR left of the text on a wide label and
  above it on a squarish one. `?print=` answers the PDF, without the
  generator's intro pages; it opens in a new tab, and the sheet, code and
  type-name choices are kept in the browser. Reads only, any instance.
- **Left out**: a consortium's short label (BDE's `A07` and its lookup
  table); where on the sheet a single label lands (always the first).

## Consequences

- `receive_box` now posts arrival locations to base PIDs (previously a
  cable-end row would have 404'd the write and aborted the receiving flow).
- Plain PIDs and non-PID-shaped ids pass through unchanged; if upstream
  renames the suffix grammar, only `split_subcomp_ref` and the `peer`
  heuristic (`:n` = forward) need revisiting.
- Manually expanding a peer row on a cable's page can ping-pong (flange →
  cable → flange…); each step is user-driven and dedup guards the ES walk,
  so no loop can run away.
