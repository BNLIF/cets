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
| `static` | `note`, `image` (URL), `url` | nothing — display only |
| `link` | `position` (optional) | scanned child PID — also PATCHed into the item's subcomponents (#96) |

Unknown types and malformed entries are dropped silently on render.

Any value-bearing field (not `photo`/`link`/`static`/`steps`) may carry
`"to_spec": true` (#96): its value ALSO folds into the item's latest
specifications `DATA` (flat `{label: value}`), alongside the test record.

## Where submissions go

HWDB only: photos post to the item first (for their image_ids), then
`link` fields patch the item's subcomponents (into the named functional
position, or the first free one matching the child's type), then `to_spec`
values patch the item's specifications, then one test record of
`test_type_name` whose `test_data.DATA` is keyed
`{section title: {field label: value}}`. The latest submission pre-fills the
next visit (the iPad's "revive"); photo references carry forward unless a
new file replaces them. The test type is auto-created on first use.
