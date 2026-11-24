"""The Cable connections page's model (#226, the cabling tickets under #222).

One **endpoint device** — a non-cable item a cable plugs into — its positions
that take a cable, and where each connected cable goes. HWDB writes a cable
link on the device only (``<cable PID>.<END>:<n>`` at a position); the cable's
own rows say what else it is connected to (ADR-0018).

Reads are bounded by the device: its record, its type and its positions once,
each connected cable's rows and container once, each cable type's record once,
the type's picture (its image listing and one small file), each other-side
device's record once for its location. No sweep over a type, nothing written,
nothing added to the mirror.

The picture (#228) belongs to the device's **type**: ``Cable_map_<type>.json``
among the type's HWDB images names a picture (another of those images) and a
marker per position — the checklist image map's shape, ``slots`` of ``label``,
``x``, ``y`` in percent of the picture.

The **device location** (#229) is typed by hand and kept in the device's Item
Specs, ``DATA["Device location"]``. A **cable label** is worked out each time
from the connections and the saved locations, never stored: one line per
side, ``<device location>.<position>``; a bundle / tray's label is the two
locations alone, ``<location>/<location>``.

The **Cable dashboard** (#230) is the other way round: the cables of one
cable type, each with how many of its END : connectors are connected and
where. It reads the mirror alone — a cable's connections are kept on its
mirror row (``cable_links``), read by the type's sync and again after this
page's own connects and removes.
"""

from __future__ import annotations

import io
import json

from reportlab.pdfbase.pdfmetrics import stringWidth

from django.core.paginator import Paginator

from . import curation, labels, parts, production
from .models import HierarchyNode, HwdbComponentEvent
from .shipments import current_manifest


LOCATION_KEY = "Device location"   # in the device's Item Specs DATA — the name is not yet agreed with Hajime
LOCATION_MAX = 60
LABEL_SHEET = "Letter-3x10-Avery"  # the print dialog's sheet until the browser remembers another
DASH_PER = 25                      # the dashboard's page: bundles, and cables in none
DASH_STATES = (("", "All cables"), ("none", "Not connected"), ("connected", "Connected"), ("installed", "Installed"))


def _type_id(part_id: str) -> str:
    return part_id.rsplit("-", 1)[0]


def location_of(comp: dict) -> str:
    """The device location saved in an item record's Item Specs; "" for none."""
    specs = (comp.get("specifications") or [{}])[-1]
    data = specs.get("DATA") if isinstance(specs, dict) else None
    value = data.get(LOCATION_KEY) if isinstance(data, dict) else None
    return value.strip() if isinstance(value, str) else ""


def _end_name(connector) -> str:
    """``"FCP Flange"`` of ``"FCP Flange:1"`` — the END a connector belongs to."""
    name, _, n = str(connector or "").rpartition(":")
    return name if name and n.isdigit() else str(connector or "")


def type_facts(api, inst: str, type_ids) -> dict:
    """``{type id: (name, category)}`` — the mirror's word first, HWDB's type
    record for a type the mirror lacks or has no category for."""
    facts = {t: (name, category) for t, name, category in
             HierarchyNode.for_instance(inst)
             .filter(level=HierarchyNode.LEVEL_TYPE, part_type_id__in=type_ids)
             .values_list("part_type_id", "name", "category")}
    missing = [t for t in type_ids if not facts.get(t, ("", ""))[1]]
    records = parts.fetch_map(api, lambda c, t: c.get_component_type(t).get("data") or {}, missing)
    for t, record in records.items():
        if record:
            # full_name is project.system.subsystem.name; the name may hold periods
            name = (record.get("full_name") or "").split(".", 3)[-1]
            facts[t] = (facts.get(t, ("", ""))[0] or name or t, record.get("category") or "")
    return facts


def map_name(part_type_id: str) -> str:
    return f"Cable_map_{part_type_id}.json"


def normalize_map(raw) -> dict:
    """``{image_id, slots}`` out of a stored or posted map: each slot a
    ``label`` (a position name) with ``x``, ``y`` in percent; a slot off the
    picture, unnamed or named twice is dropped."""
    raw = raw if isinstance(raw, dict) else {}
    slots, seen = [], set()
    for s in raw.get("slots") or []:
        if not isinstance(s, dict):
            continue
        label = str(s.get("label") or "").strip()
        try:
            x, y = float(s.get("x")), float(s.get("y"))
        except (TypeError, ValueError):
            continue
        if label and label not in seen and 0 <= x <= 100 and 0 <= y <= 100:
            seen.add(label)
            slots.append({"label": label, "x": round(x, 2), "y": round(y, 2)})
    return {"image_id": str(raw.get("image_id") or "").strip(), "slots": slots}


def read_map(api, part_type_id: str) -> dict | None:
    """The newest ``Cable_map_<type>.json`` on the type, normalised; None
    when the type has none or it names no picture. Two reads."""
    vs = production.versions(production._listing(api, part_type_id), map_name(part_type_id))
    raw = production._load(api, vs[0]["image_id"]) if vs else None
    cmap = normalize_map(raw) if raw is not None else None
    return cmap if cmap and cmap["image_id"] else None


def write_map(api, part_type_id: str, cmap: dict, who: str, when: str) -> dict:
    """Post a version of the type's picture and markers. Raises what the client raises."""
    return api.post_component_type_image(
        part_type_id, io.BytesIO(json.dumps({**cmap, "updated_by": who, "updated": when}, indent=2).encode()),
        map_name(part_type_id), comments="Cable connections picture and markers (Explorer)")


def cable_positions(api, inst: str, connectors: dict) -> list[str]:
    """The type's positions that accept a cable type, in its order — the ones
    the picture's editor offers a marker for."""
    facts = type_facts(api, inst, parts.child_types(connectors))
    return [pos for pos, accepted in connectors.items()
            if any(facts.get(t, ("", ""))[1] == "cable" for t in parts.accepted_types(accepted))]


def takes_cables(inst: str, connectors: dict) -> bool:
    """Whether one of the positions accepts a cable type by the mirror's word
    alone — no HWDB read; what an item's page and its type's page go by."""
    return HierarchyNode.for_instance(inst).filter(
        level=HierarchyNode.LEVEL_TYPE, category="cable",
        part_type_id__in=parts.child_types(connectors)).exists()


def _tray(inst: str, container, device) -> dict | None:
    """A cable's bundle / tray from its current container; not the device
    itself, and not a shipping box — a cable still recorded in the box it
    came in is in no bundle."""
    if (not container or container["part_id"] == device
            or curation.is_shipping_type(inst, _type_id(container["part_id"]))):
        return None
    return {"part_id": container["part_id"], "type_name": container["type_name"], "also": [], "label": ""}


def device_connections(api, inst: str, part_id: str) -> dict:
    """The page's model for ``part_id``:

    - ``is_cable`` — the item is itself a cable: no rows;
    - ``rows`` — one per position that accepts a cable type (or holds a cable
      end), numbered in the type's order: ``n``, ``position``, ``expected``
      (type names), and when something is linked there ``cable``,
      ``cable_type``, ``end`` (``END:connector``, None for a link without
      one — the device is then the cable's bundle / tray), ``others`` (the
      other side, one entry per item: ``part_id``, ``type_name``, ``here``
      when it is this very device, and its ``connections`` — ``position``,
      ``end``), ``connected`` / ``connectors`` (how many of the cable's
      END:connectors are connected, of how many) and ``unread`` when the
      cable's rows could not be read;
    - ``slots`` per connected row — every END : connector of the cable, in its
      type's order: ``name``, ``end`` (the END it belongs to), ``n`` (the
      rest of the name, ``:1``) and, when connected, ``part_id``,
      ``type_name``, ``position``, ``location``, ``here`` (on this device)
      and ``this`` (the connection at this very row); ``part_id`` None for a
      free one;
    - ``status`` per row — ``available``, ``connected``, ``installed`` (every
      END:connector of the cable is connected; Hajime, slide 15) or ``noend``;
    - ``bundle`` per row — the cable's bundle / tray, the item that holds it by
      plain PID (``part_id``, ``type_name``, and ``also``: the numbers of this
      device's other rows whose cable sits in the same one); None for a cable
      in none, or held that way by this very device;
    - ``accepts`` per row — the type ids the position takes;
    - ``type_record`` — the device type's record, for the role banner;
    - ``picture`` — the type's picture: ``image_id`` and ``markers``, one per
      slot named like a row's position (``row``, ``x``, ``y``); a slot whose
      position the page has no row for is left off. None without a picture;
    - ``n_connected`` — rows connected or installed; ``n_labelled`` — those
      with a cable label;
    - ``others`` — the distinct items on the other side, each with the number
      of this device's cables going there, for Change working device;
    - ``location`` — the device's saved location, and ``location`` on every
      other-side entry and connected slot (one record read per device a
      cable of this page is connected to);
    - ``label`` per row — the cable label, for a cable connected at exactly
      two positions on two different ENDs: ``lines`` (one per side,
      ``<device location>.<position>``, in the order of the cable's own
      connectors so that either working side gives the same text), ``text``
      (the lines joined with ``-``) and ``incomplete`` when a side's device
      has no location saved — that side is the position name alone. None
      for any other cable;
    - ``label`` on a row's ``bundle`` — ``<location>/<location>`` when the
      bundle's cables on this page all go to one same other device and both
      locations are saved (in PID order, the same from either side); "" else.

    The other side of a connection is what the cable's *other ENDs* are
    connected to: connectors of one END sit at the same end of the cable, so
    a bundle's eight ``Flange:n`` are not each other's other side. HWDB does
    not say which END is opposite which, so a cable with three ENDs has two
    other sides. Both ENDs of a short cable may sit on the device itself."""
    comp = api.get_component(part_id).get("data") or {}
    ptid = _type_id(part_id)
    out = {"part_id": part_id, "part_type_id": ptid,
           "type_name": (comp.get("component_type") or {}).get("name") or ptid,
           "is_cable": comp.get("category") == "cable",
           "location": location_of(comp),
           "rows": [], "n_connected": 0, "others": [], "type_record": {}, "picture": None}
    if out["is_cable"]:
        return out
    out["type_record"] = api.get_component_type(ptid).get("data") or {}
    connectors = out["type_record"].get("connectors") or {}
    held = {m["functional_position"]: m
            for m in current_manifest(api.get_subcomponents(part_id).get("data"))
            if m["part_id"] and not m["peer"]}
    facts = type_facts(api, inst, parts.child_types(connectors))

    def is_cable(type_id):
        return facts.get(type_id, ("", ""))[1] == "cable"

    positions = [pos for pos, accepted in connectors.items()
                 if any(is_cable(t) for t in parts.accepted_types(accepted))
                 or (held.get(pos) or {}).get("connection")]
    cables = [held[pos]["part_id"] for pos in positions
              if pos in held and (held[pos]["connection"] or is_cable(_type_id(held[pos]["part_id"])))]
    cable_rows = parts.fetch_map(
        api, lambda c, pid: current_manifest(c.get_subcomponents(pid).get("data")), cables)
    names = parts.fetch_map(                                 # each cable type's END : connectors, in its order
        api, lambda c, t: list((c.get_component_type(t).get("data") or {}).get("connectors") or {}),
        [_type_id(pid) for pid in cables])
    trays = parts.fetch_map(
        api, lambda c, pid: parts.current_container(c.get_container(pid).get("data")), cables)

    there: dict[str, dict] = {}
    for n, pos in enumerate(positions, 1):
        row = {"n": n, "position": pos, "status": "available", "cable": None, "bundle": None,
               "accepts": parts.accepted_types(connectors[pos]),
               "expected": [facts.get(t, ("", ""))[0] or t for t in parts.accepted_types(connectors[pos])]}
        m = held.get(pos)
        if m:
            pid = m["part_id"]
            mine = cable_rows.get(pid)                       # None: not a cable, or its rows could not be read
            links = [c for c in mine or [] if c["peer"]]
            total = len(names.get(_type_id(pid)) or [])
            my_end = _end_name(m["connection"])
            sides: dict[str, dict] = {}
            for c in links:
                if c["part_id"] == part_id and c["functional_position"] == pos:
                    continue                                 # this very connection
                if my_end and c["via"] and _end_name(c["via"]) == my_end:
                    continue                                 # the same end of the cable
                side = sides.setdefault(c["part_id"], {
                    "part_id": c["part_id"], "type_name": c["type_name"],
                    "here": c["part_id"] == part_id, "connections": []})
                side["connections"].append({"position": c["functional_position"], "end": c["via"]})
            row.update(
                cable=pid, end=m["connection"],
                cable_type=m["type_name"] or facts.get(_type_id(pid), ("", ""))[0] or _type_id(pid),
                others=list(sides.values()), links=links, label=None,
                connected=len(links), connectors=total, unread=pid in cables and mine is None,
                bundle=_tray(inst, trays.get(pid), part_id),
                status=("noend" if not m["connection"]
                        else "installed" if total and len(links) >= total else "connected"))
            for o in row["others"]:
                if not o["here"]:
                    d = there.setdefault(o["part_id"], {"part_id": o["part_id"], "type_name": o["type_name"],
                                                        "cables": set()})
                    d["cables"].add(pid)
        out["rows"].append(row)
    devices = dict.fromkeys(c["part_id"] for r in out["rows"] for c in r.get("links") or [] if c["part_id"] != part_id)
    locs = parts.fetch_map(api, lambda c, pid: location_of(c.get_component(pid).get("data") or {}), list(devices))
    locs[part_id] = out["location"]
    for row in out["rows"]:
        if not row["cable"]:
            continue
        for o in row["others"]:
            o["location"] = locs.get(o["part_id"]) or ""
        by_name = {c["via"]: c for c in row["links"] if c["via"]}
        known = names.get(_type_id(row["cable"])) or []
        row["slots"] = []
        for name in [*known, *(n for n in by_name if n not in known)]:   # a connection on a name the type lacks is still shown
            c, end = by_name.get(name), _end_name(name)
            slot = {"name": name, "end": end, "n": name[len(end):] or name, "part_id": None}
            if c:
                slot.update(part_id=c["part_id"], type_name=c["type_name"], position=c["functional_position"],
                            location=locs.get(c["part_id"]) or "", here=c["part_id"] == part_id,
                            this=c["part_id"] == part_id and c["functional_position"] == row["position"])
            row["slots"].append(slot)
        ends = sorted(row["links"], key=lambda c: (str(c["via"] or ""), c["part_id"], str(c["functional_position"])))
        if row["end"] and len(ends) == 2 and _end_name(ends[0]["via"]) != _end_name(ends[1]["via"]):
            lines = [".".join(x for x in (locs.get(c["part_id"]), c["functional_position"]) if x) for c in ends]
            row["label"] = {"lines": lines, "text": "-".join(lines),
                            "incomplete": not all(locs.get(c["part_id"]) for c in ends)}
    for row in out["rows"]:
        if row["bundle"]:
            same = [r for r in out["rows"] if r["bundle"] and r["bundle"]["part_id"] == row["bundle"]["part_id"]]
            row["bundle"]["also"] = [r["n"] for r in same if r is not row]
            far = {o["part_id"] for r in same for o in r["others"] if not o["here"]}
            pair = sorted([part_id, *far]) if len(far) == 1 else []
            row["bundle"]["label"] = "/".join(locs[p] for p in pair) if pair and all(locs.get(p) for p in pair) else ""
    cmap = read_map(api, ptid) if out["rows"] else None
    if cmap:
        by_pos = {r["position"]: r for r in out["rows"]}
        out["picture"] = {"image_id": cmap["image_id"],
                          "markers": [{"row": by_pos[s["label"]], "x": s["x"], "y": s["y"]}
                                      for s in cmap["slots"] if s["label"] in by_pos]}
    out["n_connected"] = sum(r["status"] in ("connected", "installed") for r in out["rows"])
    out["n_labelled"] = sum(bool(r.get("label")) for r in out["rows"])
    out["others"] = [{**d, "cables": len(d["cables"])} for d in there.values()]
    return out


def offer_bundle(api, inst: str, device: dict, bundle_id: str) -> dict:
    """A bundle / tray scanned first (#227): its cables, offered at the
    device's free positions so that each need not be scanned.

    Returns ``part_id``, ``type_name``, ``offered`` (a free position takes one
    of them) and ``cables`` — the items the bundle
    holds by plain PID whose type is a cable type: ``part_id``,
    ``part_type_id``, ``held_at`` (the bundle's position), ``connected`` /
    ``connectors`` and ``here`` (the device's row numbers it is connected at).
    Each free row of ``device`` gets ``candidates`` (the bundle's cables of a
    type the position takes, with ``open``: not connected here and with a
    connector free), ``offered`` — the PIDs of the open ones, shown in the
    row — and ``prefill`` — the PID when exactly one is open.

    Reads: the bundle's positions once, each of its cables' rows once, a cable
    type's record once."""
    held = [m for m in current_manifest(api.get_subcomponents(bundle_id).get("data"))
            if m["part_id"] and not m["peer"] and not m["connection"]]
    facts = type_facts(api, inst, [_type_id(bundle_id)] + [_type_id(m["part_id"]) for m in held])
    held = [m for m in held if facts.get(_type_id(m["part_id"]), ("", ""))[1] == "cable"]
    pids = [m["part_id"] for m in held]
    used = parts.fetch_map(
        api, lambda c, pid: sum(1 for r in current_manifest(c.get_subcomponents(pid).get("data")) if r["peer"]), pids)
    slots = parts.fetch_map(
        api, lambda c, t: len((c.get_component_type(t).get("data") or {}).get("connectors") or {}),
        [_type_id(pid) for pid in pids])
    here: dict[str, list] = {}
    for r in device["rows"]:
        if r["cable"]:
            here.setdefault(r["cable"], []).append(r["n"])
    cables = []
    for m in held:
        pid, total = m["part_id"], slots.get(_type_id(m["part_id"])) or 0
        n = used.get(pid)
        cables.append({"part_id": pid, "part_type_id": _type_id(pid), "held_at": m["functional_position"],
                       "connected": n or 0, "connectors": total, "here": here.get(pid, []),
                       "open": pid not in here and (n is None or not total or n < total)})
    for r in device["rows"]:
        if not r["cable"]:
            r["candidates"] = [c for c in cables if c["part_type_id"] in r["accepts"]]
            r["offered"] = [c["part_id"] for c in r["candidates"] if c["open"]]
            r["prefill"] = r["offered"][0] if len(r["offered"]) == 1 else ""
    return {"part_id": bundle_id, "type_name": facts.get(_type_id(bundle_id), ("", ""))[0] or _type_id(bundle_id),
            "cables": cables, "offered": any(r.get("candidates") for r in device["rows"])}


def label_layout(sheet: str, lines: list[str], code: str | None, type_name: bool) -> dict:
    """A label generator layout for one cable or bundle label on ``sheet``
    (one of ``labels.TEMPLATES``): the code (``"qr"``, ``"bar"`` or None) with
    the PID readable beside it, the label's ``lines`` (``${lines.n}`` of the
    item's data, all at one size — the longest one's fit) and the type name
    when asked. The text runs along the label's longer side; a QR sits left
    of it on a wide label and above it on a squarish one, a bar code always
    above."""
    w, h = labels.template_for({"label template": sheet})["label"]     # in points
    wide, high = max(w, h), min(w, h)
    texts = [{"element type": "text", "text": "${lines.%d}" % i} for i in range(len(lines))]
    if code:
        texts.append({"element type": "external id" if code == "bar" else "part id", "font face": "Helvetica"})
    if type_name:
        texts.append({"element type": "part name", "font face": "Helvetica"})
    x0, x1, y0, y1 = 4.0, 96.0, 8.0, 92.0             # the text block, in percent of the label
    elements = []
    if code == "bar":
        elements.append({"element type": "bar", "alignment": "top-center", "anchor": ["50%", "8%"],
                         "size": ["88%", "34%"], "preserve aspect ratio": False})
        y0 = 48.0
    elif code and wide / high >= 1.5:
        side = min(84.0 * high / wide, 30.0)          # a square, in percent of the width: the text keeps most of it
        tall = side * wide / high
        elements.append({"element type": "qr", "alignment": "top-left", "anchor": ["3%", f"{(100 - tall) / 2:.2f}%"],
                         "size": [f"{side:.2f}%", f"{tall:.2f}%"], "preserve aspect ratio": True})
        x0 = 3.0 + side + 3.0
    elif code:
        elements.append({"element type": "qr", "alignment": "top-center", "anchor": ["50%", "5%"],
                         "size": ["90%", "50%"], "preserve aspect ratio": True})
        y0 = 58.0
    pitch = (y1 - y0) / max(1, len(texts))
    size = min(pitch / 1.7, 16.0)                     # the generator draws text 1.35 × its font size tall
    mid = (x0 + x1) / 2
    room = min(x1 - x0, 2 * min(mid, 100 - mid) - 200 * labels.FIT_MARGIN) / 100 * wide   # the generator's fit width
    longest = max([stringWidth(t, "Helvetica-Bold", 1.35 * size / 100 * high) for t in lines] or [0])
    own = size * min(1.0, room / longest) if longest else size
    for i, el in enumerate(texts):
        fs = own if i < len(lines) else min(size, own)    # the PID and type name never larger than the label
        elements.append({**el, "alignment": "top-center", "fit width": True,
                         "anchor": [f"{mid:.2f}%", f"{y0 + i * pitch + (pitch - 1.35 * fs) / 2:.2f}%"],
                         "size": [f"{x1 - x0:.2f}%", f"{pitch:.2f}%"], "font size": f"{fs:.2f}%"})
    return {"label template": sheet, "orientation": "landscape" if h > w else "portrait", "elements": elements}


def label_jobs(device: dict, what: str, show: str, code: str, type_name: bool, sheet: str) -> list[tuple[dict, dict]]:
    """The labels to print (#229), as the label generator's (layout, item)
    pairs in row order. ``what``: ``"all"`` — every connected row; a row's
    number — that row's cable; ``"b<n>"`` — the bundle / tray of row n, with
    its bundle label. ``show``: ``"both"`` (label and PID), ``"label"`` or
    ``"pid"``. A cable with no label prints its PID only, and is left out when
    only labels are asked for; the PID is drawn as ``code`` (``"qr"`` or
    ``"bar"``) with its text."""
    rows = {str(r["n"]): r for r in device["rows"] if r["cable"]}
    if what == "all":
        picked = [(r["cable"], r["cable_type"], (r["label"] or {}).get("lines") or [])
                  for r in rows.values() if r["status"] in ("connected", "installed")]
    elif what[:1] == "b" and (rows.get(what[1:]) or {}).get("bundle"):
        b = rows[what[1:]]["bundle"]
        picked = [(b["part_id"], b["type_name"], [b["label"]] if b["label"] else [])]
    elif what in rows:
        r = rows[what]
        picked = [(r["cable"], r["cable_type"], (r["label"] or {}).get("lines") or [])]
    else:
        picked = []
    jobs = (label_job(pid, name, lines, show, code, type_name, sheet) for pid, name, lines in picked)
    return [j for j in jobs if j]


def label_job(pid: str, name: str, lines: list[str], show: str, code: str, type_name: bool,
              sheet: str) -> tuple[dict, dict] | None:
    """One label as the label generator's (layout, item) pair — what
    ``label_jobs`` makes of a row and what the Print dialog previews; None
    when only labels are asked for and the item has none."""
    lines = [] if show == "pid" else lines
    if show == "label" and not lines:
        return None
    return (label_layout(sheet, lines, code if show != "label" else None, type_name),
            {"part_id": pid, "part_name": name or "", "lines": lines})


def cable_links(subs) -> list[dict]:
    """A cable's connections as its mirror row keeps them (#230), from the
    cable's own ``/subcomponents`` rows: the END : connector (``via``), the
    device and its position. ``location`` and ``status`` are the device's,
    filled by ``stamp_devices``."""
    return [{"via": m["via"] or "", "part_id": m["part_id"], "position": m["functional_position"] or "",
             "type_name": m["type_name"] or "", "location": "", "status": ""}
            for m in current_manifest(subs) if m["peer"] and m["part_id"]]


def stamp_devices(api, links_by_cable: dict, known: dict | None = None) -> int:
    """Fill each link's ``location`` and ``status`` from its device's record,
    one read per device; a device that cannot be read keeps what ``known``
    (``{device: (location, status)}``) has for it. Returns the device count."""
    devices = sorted({l["part_id"] for links in links_by_cable.values() for l in links})

    def facts(client, pid):
        comp = client.get_component(pid).get("data") or {}
        return location_of(comp), parts.normalize_status(comp.get("status")) or ""

    read = parts.fetch_map(api, facts, devices)
    for links in links_by_cable.values():
        for l in links:
            l["location"], l["status"] = read.get(l["part_id"]) or (known or {}).get(l["part_id"]) or ("", "")
    return len(devices)


def known_devices(rows) -> dict:
    """``{device: (location, status)}`` out of mirror rows' ``cable_links``."""
    return {l["part_id"]: (l.get("location") or "", l.get("status") or "")
            for r in rows for l in r.cable_links or []}


def mirror_cables(api, inst: str, cable_ids) -> None:
    """After a connect or a remove of the Explorer's own: these cables'
    connections read again into their mirror rows. A cable the mirror lacks
    is skipped, one that cannot be read keeps what it had."""
    rows = {r.part_id: r for r in HwdbComponentEvent.for_instance(inst).filter(part_id__in=list(cable_ids))}
    read = parts.fetch_map(api, lambda c, pid: cable_links(c.get_subcomponents(pid).get("data")), list(rows))
    read = {pid: links for pid, links in read.items() if links is not None}
    stamp_devices(api, read, known_devices(rows.values()))
    for pid, links in read.items():
        rows[pid].cable_links = links
    HwdbComponentEvent.objects.bulk_update([rows[pid] for pid in read], ["cable_links"])


def mirror_location(inst: str, device_id: str, location: str) -> None:
    """A device location saved on the Cable connections page, carried to the
    mirrored connections that name the device."""
    rows = [r for r in HwdbComponentEvent.for_instance(inst).filter(cable_links__icontains=device_id)
            if any(l["part_id"] == device_id for l in r.cable_links or [])]
    for r in rows:
        for l in r.cable_links:
            if l["part_id"] == device_id:
                l["location"] = location
    HwdbComponentEvent.objects.bulk_update(rows, ["cable_links"])


def _link_state(links, total: int) -> str:
    """A cable's state on the dashboard from its mirrored connections:
    ``unread`` (never mirrored), ``none``, ``connected`` or ``installed``
    (every one of its ``total`` END : connectors connected)."""
    if links is None:
        return "unread"
    return "none" if not links else "installed" if total and len(links) >= total else "connected"


def _tally(states) -> dict:
    """How many of ``states`` are installed, connected, not connected and
    unread, with the two bar widths in percent."""
    states = list(states)
    t = {k: states.count(k) for k in ("installed", "connected", "none", "unread")}
    n = len(states) or 1
    return {**t, "pct_installed": round(100 * t["installed"] / n), "pct_connected": round(100 * t["connected"] / n)}


def overview(inst: str, leaves) -> list[dict]:
    """The dashboard before a type is chosen: the cable types grouped by
    subsystem (``system``, ``subsystem``, ``types``, in the order of
    ``leaves``), one row per type — ``leaf``, its mirrored ``cables`` and
    their tally by state. Mirror only."""
    totals = {leaf.part_type_id: sum(e["connectors"] for e in leaf.cable_ends or []) for leaf in leaves}
    states: dict[str, list] = {t: [] for t in totals}
    for ptid, links in (HwdbComponentEvent.for_instance(inst).filter(part_type_id__in=list(totals))
                        .values_list("part_type_id", "cable_links")):
        states[ptid].append(_link_state(links, totals[ptid]))
    groups: dict[tuple, dict] = {}
    for leaf in leaves:
        g = groups.setdefault((leaf.project, leaf.system_id, leaf.subsystem_id),
                              {"system": leaf.system_name, "subsystem": leaf.subsystem_name, "types": []})
        g["types"].append({"leaf": leaf, "cables": len(states[leaf.part_type_id]), **_tally(states[leaf.part_type_id])})
    return list(groups.values())


def bundle_cable_types(api, inst: str, part_type_id: str) -> tuple[list, list[str]]:
    """The other cable types the bundles of this type's mirrored cables take
    (#238), for the dashboard's sync to go on with: the type nodes in id
    order, and the bundle types whose record could not be read. A bundle is a
    mirrored cable's parent, a shipping box left out; what its type takes is its record's positions —
    one read per bundle type — kept where the mirror knows a cable type."""
    parents = (HwdbComponentEvent.for_instance(inst).filter(part_type_id=part_type_id)
               .exclude(parent_part_id="").values_list("parent_part_id", flat=True))
    bundle_types = sorted(t for t in {_type_id(p) for p in parents} if not curation.is_shipping_type(inst, t))
    taken = parts.fetch_map(
        api, lambda c, t: parts.child_types((c.get_component_type(t).get("data") or {}).get("connectors")), bundle_types)
    wanted = {t for types in taken.values() for t in types or ()} - {part_type_id}
    nodes = list(HierarchyNode.for_instance(inst).filter(
        level=HierarchyNode.LEVEL_TYPE, category="cable", part_type_id__in=wanted).order_by("part_type_id"))
    return nodes, [t for t in bundle_types if taken.get(t) is None]


def _connector_names(leaf) -> list[str]:
    """A cable type's END : connectors in order, from its mirrored ENDs."""
    return [f"{e['name']}:{i}" for e in leaf.cable_ends or [] for i in range(1, e["connectors"] + 1)]


def _dash_cable(row, names: list[str]) -> dict:
    """One cable of the dashboard from its mirror row: ``slots`` — every
    END : connector of the type, in its order, each with its ``link`` or None,
    a connection on a name the type lacks after them; ``state``
    (``_link_state``); ``places`` — the devices it goes to,
    each with its location and the positions used."""
    links = row.cable_links
    by_name = {l["via"]: l for l in links or [] if l["via"]}
    slots = [{"name": n, "end": _end_name(n), "link": by_name.get(n)}
             for n in [*names, *(n for n in by_name if n not in names)]]
    places: dict[str, dict] = {}
    for l in links or []:
        places.setdefault(l["part_id"], {"part_id": l["part_id"], "location": l.get("location") or "",
                                         "positions": []})["positions"].append(l["position"])
    n, total = len(links or []), len(names)
    return {"part_id": row.part_id, "serial": row.serial_number, "status": row.status, "bundle": row.parent_part_id,
            "slots": slots, "places": list(places.values()), "connected": n, "connectors": total,
            "state": _link_state(links, total),
            "hay": " ".join([row.part_id, row.serial_number, row.parent_part_id,
                             *(x for l in links or [] for x in (l["part_id"], l.get("location") or "", l["position"]))]).lower()}


def dashboard(inst: str, leaf, *, state: str = "", q: str = "", status: str = "", page=None) -> dict:
    """The Cable dashboard's model for one cable type (#230, Hajime's
    cables-first list), from the mirror alone:

    - ``names`` — the type's END : connectors, from its mirrored ENDs;
    - ``statuses`` — the Component Statuses its cables have, for the filter;
    - ``counts`` — cables per state among those matching ``q`` and
      ``status``, with ``all``; ``n_unread`` — those never read;
      ``connected`` / ``connectors`` — END : connectors connected, of how
      many, over the same cables;
    - ``page`` — a page of the list after the ``state`` filter: one entry per
      bundle (``bundle``: ``part_id``, ``type_name``, ``status`` when the
      mirror has the item, its ``cables``, how many are ``installed``,
      ``connected``, ``none`` and ``unread``, and the ``places`` they go
      to), then one per cable in no bundle (``cable``). A cable's bundle is
      its mirrored parent, the item that holds it by plain PID — a
      shipping box, which holds it the same way, is not one. A bundle's
      ``cables`` are the type's cables that pass the filters, then the
      mirrored cables of other cable types it holds (#238), each with its
      ``type_name`` and ``part_type_id`` — these are not filtered and not in
      ``counts``, and the bundle's own tally covers all it lists."""
    names = _connector_names(leaf)
    rows = HwdbComponentEvent.for_instance(inst).filter(part_type_id=leaf.part_type_id).order_by("part_id")
    cables = [_dash_cable(r, names) for r in rows]
    boxes = {t for t in {_type_id(c["bundle"]) for c in cables if c["bundle"]} if curation.is_shipping_type(inst, t)}
    for c in cables:
        if _type_id(c["bundle"]) in boxes:       # packed in a shipping box: in no bundle
            c["bundle"] = ""
    statuses = sorted({c["status"] for c in cables if c["status"]})
    needle = q.lower()
    cables = [c for c in cables if (not needle or needle in c["hay"]) and (not status or c["status"] == status)]
    counts = {"all": len(cables), **{k: sum(c["state"] == k for c in cables) for k, _ in DASH_STATES if k}}
    shown = [c for c in cables if not state or c["state"] == state]
    groups, by_bundle = [], {}
    for c in sorted(shown, key=lambda c: (not c["bundle"], c["bundle"], c["part_id"])):
        if not c["bundle"]:
            groups.append({"cable": c})
            continue
        if c["bundle"] not in by_bundle:
            by_bundle[c["bundle"]] = {"part_id": c["bundle"], "cables": []}
            groups.append({"bundle": by_bundle[c["bundle"]]})
        by_bundle[c["bundle"]]["cables"].append(c)
    page_obj = Paginator(groups, DASH_PER).get_page(page)
    held = [g["bundle"] for g in page_obj if "bundle" in g]
    kin = list(HwdbComponentEvent.for_instance(inst).filter(parent_part_id__in=[b["part_id"] for b in held])
               .exclude(part_type_id=leaf.part_type_id).order_by("part_id"))
    kin_types = {n.part_type_id: n for n in HierarchyNode.for_instance(inst).filter(
        level=HierarchyNode.LEVEL_TYPE, category="cable", part_type_id__in={r.part_type_id for r in kin})}
    for r in kin:
        node = kin_types.get(r.part_type_id)
        if node:
            by_bundle[r.parent_part_id]["cables"].append(
                {**_dash_cable(r, _connector_names(node)), "type_name": node.name, "part_type_id": node.part_type_id})
    type_names = dict(HierarchyNode.for_instance(inst)
                      .filter(level=HierarchyNode.LEVEL_TYPE, part_type_id__in={_type_id(b["part_id"]) for b in held})
                      .values_list("part_type_id", "name"))
    item_status = dict(HwdbComponentEvent.for_instance(inst).filter(part_id__in=[b["part_id"] for b in held])
                       .values_list("part_id", "status"))
    for b in held:
        b.update(_tally(c["state"] for c in b["cables"]))
        b.update(type_name=type_names.get(_type_id(b["part_id"]), ""), status=item_status.get(b["part_id"], ""),
                 places=list({p["part_id"]: p for c in b["cables"] for p in c["places"]}.values()))
    return {"names": names, "statuses": statuses, "counts": counts,
            "n_unread": sum(c["state"] == "unread" for c in cables),
            "connected": sum(c["connected"] for c in cables), "connectors": len(names) * len(cables),
            "page": page_obj}
