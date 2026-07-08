# DUNE HWDB Explorer — User Tutorial

The **HWDB Explorer** is a web app for browsing DUNE detector hardware
recorded in the [DUNE Hardware Database
(HWDB)](https://dune.github.io/computing-HWDB/index.html): walk the hardware
tree, see how many items of each component type exist and how they are tested
over time, track shipping boxes, inspect a single item's tests and history,
and explore the FD-VD detector on an interactive hierarchy chart.

It complements the official FNAL HWDB web UI: the Explorer is for *looking
things up quickly* — pages read a local mirror of HWDB, so browsing is fast
and never blocked by Fermilab connectivity.

All paths below are relative to the Explorer root, `…/hw/` on the deployment
host. The navbar gives you the six main pages: **Overview**, **Browse**,
**Detector**, **Shipments**, **Search**, and **Docs**.

---

## 1. Signing in

You need a **Fermilab account** (the same Services account you use for
HWDB itself). The Explorer signs you in with Fermilab's device flow:

1. Open any Explorer page — you land on the sign-in page.
2. Follow the link to Fermilab's SSO in a new tab and approve the request
   (the short user code shown on the page is already filled in for you).
3. The Explorer page notices the confirmation by itself and takes you in.

The sign-in serves two purposes: it identifies you, and it links your FNAL
account for *syncing* (section 3). Browsing already-mirrored data works even
when Fermilab is unreachable; only refreshing the mirror needs the live link.

---

## 2. Overview — the whole tree at a glance

**Overview** (the home page) shows the entire curated DUNE hardware tree in
one expandable view: Region → Family → System → Subsystem → Component Type.

- The stats row on top counts **families, systems, subsystems, component
  types, and items in HWDB** across everything mirrored. ("Item" = one
  physical unit of a component type — the same word the HWDB web UI uses.)
- Click a row to expand it; counts on every row are items registered in HWDB.
- Greyed rows have no items yet. A leaf row opens that component type's page.

The same tree lives in the left **sidebar** on every page, so you can jump
anywhere without going back to the Overview.

---

## 3. Browse — component types and their items

**Browse** is the drill-in navigator over the same tree: folders render as
cards (with item and test counts), and a **component-type page** is where the
detail lives. You can reach any component-type page three ways: drill in
through Browse, expand the Overview/sidebar tree, or Search.

### The component-type page

For example, LArASIC P5B Prod: `/hw/FD/FD-CE/1/D08100100003/`.

- **Summary** — the part type ID (linked to the same type in the FNAL HWDB
  UI), how many **items** are in HWDB, and when the type was last synced.
- **Items updated** chart — items binned by their HWDB last-updated month
  (a status change or QC upload bumps it). The selector overlays the series
  by **status** or **QC flag**.
- **Tests performed** chart — test records binned by month, faceted by test
  type. For types whose datasheets carry a validated physics test date the
  binning uses that; otherwise it falls back to the HWDB record date (the
  caption tells you which).
- **Item breakdown** — items by category (e.g. status), counted from the
  mirror.
- **Items (N)** table — every mirrored item with status and test count,
  paginated. Click an item ID to open its detail page (section 4).

### Keeping a type fresh (sync)

The first time anyone visits a component type, the Explorer fetches its items
and tests from HWDB automatically and streams the progress. After that the
page always renders instantly from the mirror, and three buttons control
freshness (cheapest first):

| Button | What it does | When to use it |
|---|---|---|
| **Sync new** | fetches only items not yet mirrored | day-to-day refresh |
| **Shallow re-sync** | refreshes every item's detail (status, updated), tests only for new items | when statuses changed upstream |
| **Full re-sync** | re-fetches everything | when in doubt |

Syncing needs your FNAL link (section 1); everything else does not.

---

## 4. The item page — one physical unit

Click any item ID (e.g. `D08100100003-00226`) to get its live detail page,
fetched straight from HWDB:

- **Item** — serial number, status, QC flags (installed / QA-QC uploaded /
  certified), institution and manufacturer, plus a link to open the same
  item in the FNAL HWDB UI.
- **Tests** — every test recorded on the item; expand one to see its
  `test_data` values, and follow the *files* link to the test's uploaded
  images/CSVs in HWDB.
- **Assembly** — what the item currently contains (its manifest). Rows with a
  ▸ caret expand in place, so you can walk an assembly down to the chips.
- **Location timeline** — where the item has been, in order.
- **Specifications / Attachments** — the datasheet blocks and any files
  attached to the item itself.

---

## 5. Detector — the interactive hierarchy chart

**Detector** renders the consortium's "FD-VD Complete detector" chart —
the physicists' box-and-arrow drawing of the detector — as a faithful,
interactive SVG (source document linked in the page subtitle).

- **Scroll to zoom, drag to pan**, *Reset view* to fit the width again.
- **Click any box** for a popup: which HWDB component type(s) the box
  corresponds to, how many items exist, and their status breakdown, with a
  link to the type's Browse page. Boxes not yet registered in HWDB say so
  honestly.
- The **HWDB coverage** toggle fades every box that has no HWDB type mapped
  yet, so you can see registration progress at a glance.

---

## 6. Shipments — where every box is

**Shipments** gathers all tracked shipping-box types into one dashboard:
totals for boxes **in transit** and **delivered**, then one collapsible group
per subsystem with a per-type table.

On a shipping type's own page, the box list shows each box's current
location; expanding a box fetches its **manifest** (what's inside) and its
full **location timeline** live from HWDB. Empty registered boxes are kept in
their own collapsed pane. Boxes are ordinary items too, so the standard item
panels (charts, items table) are all still there.

---

## 7. Search

**Search** (or the search box in the navbar, from any page) matches as you
type against component-type names, part type IDs, item IDs, and serial
numbers, and jumps straight to the right page. Note that serial numbers only
match items already pulled into the mirror — if a serial isn't found, open
its component type first so it syncs (section 3).

---

## 8. Production vs. development HWDB

HWDB has two instances, and so does the Explorer:

- `/hw/` browses **production** — the system of record.
- `/hw/dev/` browses **development** — the sandbox where consortia try
  uploads and new component types.

Switch with the *prod/dev* toggle at the top of the sidebar. Dev pages carry
a banner so you always know where you are; the two mirrors are completely
separate.

---

## 9. Docs — external references

**Docs** collects the official external references: the [HWDB training
site](https://dune.github.io/computing-HWDB/index.html), the REST API
reference for the instance you're on, the FNAL HWDB web UIs, the detector
hierarchy chart's EDMS page, and where to report HWDB issues.

---

## Tips

- **Is the mirror stale?** Each component-type page shows when it was last
  synced. When numbers look off, *Sync new* is cheap — start there.
- **A whole system looks empty or missing** — structure (which
  systems/subsystems/types exist at all) is refreshed separately by an admin;
  ask the maintainers.
- **Editing and uploads.** Today the Explorer is for browsing; to edit HWDB
  records or upload data, use the FNAL HWDB web UI or the API/upload tools
  (see the Docs page). Write features — e.g. shipping workflows — are
  planned for the Explorer itself.
