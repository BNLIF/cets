# Consortium checklist schemas (#95)

A checklist is one JSON file uploaded to the component TYPE's images in HWDB,
named `Checklist_{typeid}_{name}.json` — e.g.
`Checklist_Z00100300041_PCB Segments Interface.json`. Re-uploading the same
filename appends a version; the newest wins. A type may carry several named
checklists; the part page lists all of them (write instances only).

`pcb-segments.example.json` replicates the iPad app's "PCB Segments
Interface" scene (Hajime, 2026-08-07) and is the reference for the format.

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

Unknown types and malformed entries are dropped silently on render.

## Where submissions go

HWDB only: photos post to the item first (for their image_ids), then one
test record of `test_type_name` whose `test_data.DATA` is keyed
`{section title: {field label: value}}`. The latest submission pre-fills the
next visit (the iPad's "revive"); photo references carry forward unless a
new file replaces them. The test type is auto-created on first use.
