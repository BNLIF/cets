# Consortium checklist schemas (#95/#96)

A checklist is one JSON file uploaded to the component TYPE's images in HWDB,
named `Checklist_{typeid}_{name}.json` — e.g.
`Checklist_Z00100300041_PCB Segments Interface.json`. Re-uploading the same
filename appends a version; the newest wins. A type may carry several named
checklists; the part page lists all of them (write instances only).

The structured editor at `/hw/<inst>/checklist-config/<typeid>/` (#96)
builds and saves these schemas with a live preview — hand-editing the JSON
is never required. The `*.example.json` files here double as the editor's
"start from" templates: `pcb-segments` and `pcb-panel` replicate the iPad
app's two scenes (Hajime, 2026-08-07) and are the format reference.

## Schema shape

```json
{
  "name": "display title",
  "test_type_name": "test type the submission posts to (required)",
  "instructions": "optional intro text",
  "sections": [{"title": "…", "fields": [ … ]}]
}
```

Order is the layout — fields render top to bottom; there are no coordinates.
A `{"type": "row", "fields": [ … ]}` entry renders its children side by side
(stacked on phones). Inside a row, `{"type": "column", "fields": [ … ]}`
stacks several fields in ONE cell (#117) — e.g. a step's text on the left
with three figure links stacked on the right. In the editor each field has
a placement select: "↵ new line" (default), "→ beside" (a new cell to the
right of the field above), "↓ same cell" (below the field above, inside
its cell); a section's first field has no select.

### Section grid (#120)

A section may instead declare `"grid": N` (2–6): its fields lay out on an
N-column grid, and each field takes an optional `"col"` (start column),
`"span"` (columns occupied, or `"full"`) and `"newline": true` (start a
fresh line — `col` still applies, so "new line, columns 2–3" is
`{"newline": true, "col": 2, "span": 2}`). Unequal widths come from span
on a finer grid (#124): six columns with the text spanning 3 and three
1-wide cells beside it is a 3:1:1:1 row. Fields flow left-to-right into
the next free slot by default; a `col` already passed, or a span that
doesn't fit the remainder, wraps to the next line. Placement is computed
server-side into explicit grid coordinates, so gaps are expressible and
overlaps impossible; on phones the grid collapses to one column in field
order. Cells bottom-align (inputs beside a table share a line); a field
may set `"align": "top"` or `"middle"` (#123) — a long procedure text
at the top of its line while figures stack beside it. `row` groups don't mix with a grid — inside a grid section they're
unwrapped — but a `column` group is ONE grid cell holding a stack (#125:
a step's text on the left, a column of drawing links level with it on the
right; the group carries `col`/`span`/`newline`/`align`). In the editor,
pick "columns" on the section header; each field then shows col/span/
new-line/align, and the placement select offers "same cell" to join the
field above's cell. The section's *layout…* button opens a schematic of
the grid: click a chip and move it with the arrows, change its span or
alignment, drag it to a cell, drop it onto another chip to stack,
*unstack* to split a stack one field per row. Every change rewrites the
field order and hints (order is the layout, so the field rows reorder)
and refreshes the preview.

### Section keys (#98)

- `"collapsed": true` — the section opens folded. Every section header is a
  ▾/▸ toggle regardless, for long checklists.
- `"when": {"field": "<select label>", "equals": "<option>"}` — the section
  shows only while that `select` field holds that option (Hajime's
  "pick H or J first, then see that variant's table and figure"). The select
  may sit in any section; the rule is dropped when the label/option doesn't
  match anything (a typo shows the section rather than hiding it). Hidden
  sections' inputs are simply left blank, so they're omitted from the
  submission; values typed before switching are kept in case you switch
  back. See `variant-sections.example.json`.

## Field types (closed vocabulary)

| type | extras | value stored |
|---|---|---|
| `check` | — | `true` / `false`; untouched = omitted |
| `number` | `units`, `nominal`+`tol` or `min`/`max` | number (string if unparseable) |
| `table` | `columns` (required), `units`, tolerance as above | `{column: number}` — a column may be `{"label": …, "formula": "C1 + C2*(C3/C4)"}` (#109): computed from the row's other cells (`C<n>` = 1-based column), read-only in the form, recomputed server-side at submit; in the editor write it as `Total = C1 + C2`. A formula may reference computed columns to its left; unresolvable = the cell stays empty. A dict column may also carry its own `nominal`/`tol` or `min`/`max`, replacing the table-wide range for that cell — editor syntax `Total = C1 + C2 [11 ± 1]` or `P1 [1.4..1.6]`. `{"label": …, "check": true}` makes a pass/fail column (#116) — a compact tri-state per cell, stored as `true`/`false`, blank omitted; editor syntax `OK = check`. `{"label": …, "text": "3.1+-0.1"}` makes a fixed non-editable cell (#114, the HVS "Expected" column) — editor syntax `Expected = "3.1+-0.1"` (no commas in the text); the constant is stored with the submission, formulas can reference it when it's a plain number or a `value ± tolerance` string like `3 +- 1` (the formula reads the value, the record keeps the text), and a table where nothing was typed is still omitted. `"rows": [{"label": "Length", "texts": {"Expected": "3.1"}, "color": "yellow"}, …]` (#119) makes a multi-row table: one row per entry with a label cell on the left, the columns shared; a row's `texts`, `ranges` (per-row accepted ranges, `{column: {nominal, tol}}` or `{min, max}`) and `color` override the table's/column's; formulas and ranges apply per row (`C<n>` stays within the row). The value becomes `{row: {column: value}}`; untouched rows are omitted. No `rows` = the single implicit row, stored and rendered exactly as before. Editor: the *rows…* button opens a grid — header cells are the column syntax, body cells a row's fixed text (blank = an input), a tint per row. A table-level `"color"` (#115) tints the cells (not the header) to match the reference drawing — `yellow`/`green`/`blue`/`red`/`gray` (light shades) or `#rrggbb`, painted as picked while the inputs keep their own ground; prefer light colors. Anything else is dropped. The editor offers a color picker with those swatches predefined |
| `text` / `textarea` | — | string |
| `datetime` | — | `YYYY-MM-DDTHH:MM` string |
| `select` | `options` (required) | chosen option |
| `qr` | `type_id` (optional, #112) | scanned/typed string — with `type_id` set (e.g. `D00300100002`), a code of any other type won't register: the scanner keeps scanning, typed input paints red, and a mismatch is dropped at submit |
| `photo` | — | `{image_id, image_name[, comment]}` (posted to the item first; the optional comment becomes the HWDB image comment on upload and rides in the record) |
| `steps` | `steps` (required) | `{step: bool}` — leading spaces indent a step (2 per level, #106); the stored key is the stripped text |
| `static` | `note`, `url`, `image` (external URL) or `image_id` (reference image uploaded in the editor — e.g. a P1–P10 measurement diagram — stored on the type's HWDB images, served via the image proxy; an id of a picture already in HWDB can also be typed in directly, #108; a PDF drawing uploads too, #121 — it shows its first page as the thumbnail and opens as a PDF on click; `"thumb": false` (#122) drops the inline picture and makes the label the link that opens it — a column of drawing numbers instead of thumbnails), `checklist` (+ optional `part_type_id`, #118) — a jump link to another checklist: name only = this item's checklist of that name; with a type id = that type's PID chooser (the iPad scenes' green "Checklist" links); opens in a new tab, the current form is untouched (save a draft first if half done) | nothing — display only |
| `link` | `position` (optional), `type_id` (optional, #112 — as `qr`) | scanned child PID — also PATCHed into the item's subcomponents (#96) |
| `imagemap` | `image_id` (required), `slots` (required: `[{label, x, y}]`, percent coords), `type_id` (optional — guards every slot) | `{slot label: PID}` (#113, Top CRP) — the drawing renders with a numbered dot per slot; tapping a dot scans into that slot (green once filled), and a compact list below takes typed input. Values go to the test record only (no subcomponent linking). In the editor: pick the image, then click it to drop slots — or edit the `label @ x, y` lines directly |

Unknown types and malformed entries are dropped silently on render.

Reference figures open in a fullscreen viewer on click (#107): wheel/±
zooms, drag pans, Esc closes. A reference stored as a PDF (mechanical
drawings usually are) falls back to the browser's own PDF viewer inline —
zoom and print come with it. Inline, a PDF shows its first page (#121: the
image proxy's `?thumb=1` renders it with PyMuPDF on first request and
caches it — nothing extra is stored in HWDB); if the renderer is missing,
it shows as a "view drawing" button instead. The same `?thumb=1` shrinks a
wide PNG/JPEG to 800 px (#130) — reference pictures and a previously
uploaded photo on a revisited checklist both show as thumbnails that open
full-size in the lightbox.

Any value-bearing field (not `photo`/`link`/`static`/`steps`) may carry
`"to_spec": true` (#96): its value ALSO folds into the item's latest
specifications `DATA`, nested `{section: {label: value}}` exactly like the
test record (so variant H's and J's "Thickness" both survive), alongside the
test record. A checklist OWNS the `DATA` sections named after its sections:
each submission replaces them wholesale, and sections its previous
submission wrote that the schema no longer has are dropped — so renaming or
removing fields doesn't leave stale values behind. Keys written by anything
else (other checklists, the FNAL UI) are left alone. The part page shows the
whole blob as one "DATA" card with `section › label` rows; HWDB architects
get a ✕ per row there to remove a stale key (#102) — the FNAL UI has no
key deletion, and datasheet-level keys stay untouchable (HWDB validates
them against the type template).

### Table format rules (#109, #114–#116, #119)

Columns — the editor's columns box, one per line or comma-separated:

1. `P1` — a plain input cell.
2. `Total = C1 + C2*(C3/C4)` — a computed cell. `C<n>` is the n-th column
   of the same row, counting every column. Only `+ - * / ( )` and numbers;
   anything unresolvable leaves the cell empty.
3. `Expected = "3.1 +- 0.1"` — a fixed, non-editable cell. Formulas can use
   it when it is a number or a `value ± tolerance` string (`3 +- 1`,
   `3.1±0.1`, `3 +/- 1`), reading the value; the record keeps the text.
4. `OK = check` — a pass/fail cell (—/✓/✗), stored as true/false.
5. `Diff = C2 - C1 [0 ± 0.1]` or `P1 [1.4..1.6]` — a column's own accepted
   range, overriding the table's nominal/tol or min/max. Not for fixed or
   check columns.
6. The table's nominal/tol or min/max apply to every input and computed
   cell without its own range.

Rows — the "rows…" dialog; without rows the table is a single unnamed row:

7. Each row has a label, shown in a left cell. Labels must be unique;
   blank labels are dropped.
8. A row cell holds that row's fixed text, overriding a fixed column value
   for that row. Blank means an input. Formula and check columns take no
   row text.
8a. A row cell may also carry an accepted range in brackets — `[0 ± 0.01]`
   or `[-0.01..0.01]`, alone or after the text (`3.1 [3.0..3.2]`) — which
   beats the column's range for that row only (`ranges` on the row in the
   schema). Not on check columns.
9. A row's color overrides the table's color for that row.
10. Formulas and ranges apply per row. Untouched rows are left out of the
    record; an all-untouched table is left out entirely.

Colors:

11. Named `yellow`, `green`, `blue`, `red`, `gray`, or any `#rrggbb`. Light
    colors read best. Cells only, not the header.

## Top-level schema keys (#97, #103)

- `item_fields: [...]` (#103) — which of HWDB's standard item fields the
  checklist carries in an **Item** card above its sections: `manufacturer`
  (select from the type definition's list), `status`, `is_installed`,
  `qaqc_uploaded`, `certified_qaqc`, `location` (institution + arrival
  time), `serial_number`, `item_comments`, `test_comments`. **Absent = all
  of them** (the default; the editor shows nine ticked boxes), `[]` = none.
  The card pre-fills from the item's current HWDB record; on submit the
  changed fields go in ONE `PATCH components/{pid}`, a changed location in a
  `POST …/locations` (iPad order: item → location → test), and Test comments
  become the test record's `comments`. The values are also kept in the
  record's `DATA["Item"]` (and in the CSV/email) so a submission stays
  self-contained. HWDB has no status-vocabulary endpoint; the Dashboard's
  list is hardcoded (`STATUS_OPTIONS`).

- `roles: [41, …]` — HWDB role ids allowed to submit; empty/absent = anyone
  (the ES signee convention). Checked live against `whoami` at submit; the
  form names the required roles up front. The EDITOR stays open to every
  write-instance user — schemas are versioned in HWDB, so a bad edit is
  always recoverable, and dev culture favors low friction.

## Reaching a checklist from the type page (#110)

The type page's meta panel lists the type's checklists (filled in lazily —
the mirror-only page never waits on HWDB; no checklists or no FNAL link =
no row). Each opens the checklist's **PID chooser** — Hajime's tablet
flow: reach the checklist first, pick the item there.

- **Scan or type a PID** (must belong to this type), or **click a row** in
  the items table — the type view's mirror-backed paginated table, plus a
  column showing when THIS checklist was last submitted on each item (from
  the mirrored test events, so it reflects the last sync).
- **+ New item** goes through the #97 create page and, once minted,
  continues straight into this checklist (`?checklist=<name>` on the
  New-item URL).

Every path lands on the item's own checklist page — the familiar form,
pre-filled when a submission already exists. The chooser itself never
submits anything.

**Bookmarks (#111).** ☆ on the chooser (or on the part page's Checklists
card) lists the checklist under **My checklists** on the profile page,
grouped by the type's System › Subsystem, each linking back to its
chooser. Local-only, per user, like watches.

## New items (#97)

Item creation is a separate page, not a checklist mode: the type page's
"New item" link (`/part-new/<typeid>/`) mints the item in HWDB
(institution + optional serial/comments, the box-create payload). When the
type has exactly one checklist you land straight in it on the fresh PID —
receiving stays one continuous motion — otherwise on the item's part page,
whose Checklists card lists the choices. The checklist page reached this
way is the normal one: drafts, revive and CSV all work. The fresh item is
mirrored immediately (an incremental type sync runs on creation), so it
lists on the type page without a manual "sync new".

**Item Specs template (#100).** HWDB validates every item's specification
keys against the type's datasheet ("The input specifications do not match
the component type definition: missing fields: {'DATA'}" — seen on dev
2026-08-26), so checklist "→ Specs" fields, which write into
`specifications.DATA`, only work once the TYPE defines `DATA`. Two places
take care of it, mirroring test-type auto-creation:

- **Checklist submit** — `_ensure_spec_data` runs before the item PATCH: an
  architect submitter gets `"DATA": {}` merged into the type's template on
  first use; anyone else gets a clear error naming the missing key and who
  can add it.
- **New Item page** — shows the type's template; when it lacks `DATA`,
  architects see a pre-checked "define `DATA: {}` in the type's template
  now" box (merged into the existing keys, never replacing them), and the
  new item is then created with `DATA` too. Non-architects are told the
  "→ Specs" fields won't save on this type until an architect does that.

Existing items created before `DATA` was defined need nothing:
`_patch_spec_data` adds `DATA` to the item at its first "→ Specs" write,
which HWDB accepts once the type has it.

## Drafts, exports (#97)

- **Save draft** stores the parsed values server-side per (item, checklist,
  user) — start on the shop floor, finish at a desk. Only photos go to
  HWDB (they post to the item at draft time; the draft keeps the
  references and submit reuses them unless a new file is picked — HWDB is
  append-only, so a retaken photo leaves the first one on the item). The
  draft pre-fills the
  next visit (winning over the last submission) and is deleted the moment a
  submission lands. **Discard draft** drops it.
- **Download CSV** exports the latest submission as section/field/value
  rows (the iPad's "send via email" payload); photos flatten to their HWDB
  image name/id.
- **Print** (#105) opens the browser's print dialog — save as PDF from
  there. Folded sections open, buttons and app chrome drop out; values
  print inside their boxes, so a blank checklist doubles as a printable
  procedure sheet.
- **Email** (#99) opens your own mail client with a `mailto:` draft: a link
  back to the checklist, the submission date, and `Section / Field: value`
  lines for the filled fields. The dashboard never sends mail itself, and
  `mailto:` can't attach files — so the body is cut at ~1.8 kB with a
  pointer to the CSV, which you attach yourself when the full data matters.

## For consortium users (quickstart)

1. On your component type's page, open **Add/Edit checklists** and build a
   checklist — start from a template, add fields, watch the live preview.
   Save; it now shows on every item of the type.
2. On any item's part page, open the checklist, fill it out (phone, tablet
   or desktop), and **Submit to HWDB** — values land as a test record
   (plus Item Specifications for "→ Specs" fields). Scan QR codes with the
   ⛶ buttons; out-of-tolerance numbers turn red as you type.
3. Half done? **Save draft** and finish later from any browser.
4. Receiving new hardware? Use the type page's **New item** link — the item
   is minted first, then you land in its checklist.

## Where submissions go

HWDB only: photos post to the item first (for their image_ids), then
`link` fields patch the item's subcomponents (into the named functional
position, or the first free one matching the child's type), then `to_spec`
values patch the item's specifications, then one test record of
`test_type_name` whose `test_data.DATA` is keyed
`{section title: {field label: value}}`. The latest submission pre-fills the
next visit (the iPad's "revive"); photo references carry forward unless a
new file replaces them. The test type is auto-created on first use.
