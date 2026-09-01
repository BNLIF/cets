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
(stacked on phones).

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
| `table` | `columns` (required), `units`, tolerance as above | `{column: number}` |
| `text` / `textarea` | — | string |
| `datetime` | — | `YYYY-MM-DDTHH:MM` string |
| `select` | `options` (required) | chosen option |
| `qr` | — | scanned/typed string |
| `photo` | — | `{image_id, image_name}` (posted to the item first) |
| `steps` | `steps` (required) | `{step: bool}` |
| `static` | `note`, `url`, `image` (external URL) or `image_id` (reference image uploaded in the editor — e.g. a P1–P10 measurement diagram — stored on the type's HWDB images, served via the image proxy; an id of a picture already in HWDB can also be typed in directly, #108) | nothing — display only |
| `link` | `position` (optional) | scanned child PID — also PATCHed into the item's subcomponents (#96) |

Unknown types and malformed entries are dropped silently on render.

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
  user) — start on the shop floor, finish at a desk. Nothing goes to HWDB;
  photos aren't drafted (attach them at submit). The draft pre-fills the
  next visit (winning over the last submission) and is deleted the moment a
  submission lands. **Discard draft** drops it.
- **Download CSV** exports the latest submission as section/field/value
  rows (the iPad's "send via email" payload); photos flatten to their HWDB
  image name/id.
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
