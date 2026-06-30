# 14. Generic part detail page; shipment box page as a specialization

Date: 2026-06-30

## Status

Accepted

## Context

The shipment box page (`/explore/shipment/<pid>/`, ADR-0013) is, structurally,
"a part that happens to be a shipping box": it fetches an item's locations,
subcomponents, specifications and attachments live from HWDB and renders them.
Every other part in the explorer had nowhere to go — manifest entries linked
out to the FNAL HWDB UI, and there was no per-part view at all.

We want one place to see *everything* about any part (facts, tests,
subcomponents, specifications, attachments) and to download its binaries — the
per-part half of the Dash "Binary/Test Downloader", which is read-only and fits
our live-on-expand model.

## Decision

A single generic part page at **`/explore/part/<part_id>/`** renders any part
live from HWDB. Sections: item facts, tests (latest result per test type),
subcomponents (each linking to its own part page), specifications, attachments
(list + thumbnails + download), and a location timeline when present.

The **shipping box page is a specialization, not a separate page**. When the
part's component type is a curated shipping type, the page additionally renders
the shipment framing (shipped/received, the Pre-shipping / Shipping / Info @
Warehouse lifecycle cards). `/explore/shipment/<pid>/` permanently redirects to
`/explore/part/<pid>/`; the Shipments dashboard and the leaf Boxes card link
straight to the part page.

**Specifications rendering is generic.** The shipping checklists were always
just the box's `specifications[0].DATA` blob; we generalize the parser to turn
any top-level DATA key into a card (scalars fold into one "Specifications"
card), with the known shipping keys mapped to their display titles. The
always-three-cards lifecycle is kept only for shipping types.

**Tests are summarized, not dumped.** Per test type, the latest record's status,
date and comments — full payloads stay in HWDB. The generic test-data CSV/JSON
exporter (the same "plot/dump anything" engine as the Plots tab) is **out of
scope**, deferred with the other advanced features.

## Consequences

- One detail template and one fetch engine; no two parallel pages to drift.
- Manifest/subcomponent links now stay inside the explorer (part → part), so a
  box's contents are browsable without leaving for the HWDB UI.
- The page is live-only (FNAL-gated) like the box page — nothing is mirrored;
  an unlinked user is redirected to link.
- Item-facts and test-record field names are read defensively; exact shapes are
  confirmed against live parts (the project's spike-first habit), so early
  versions may show fewer facts than HWDB actually carries.
- Full per-part test export remains unbuilt; if demand appears it lands as the
  generic downloader, not bolted onto this page.
