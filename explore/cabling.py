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
"""

from __future__ import annotations

import io
import json

from reportlab.pdfbase.pdfmetrics import stringWidth

from . import labels, parts, production
from .models import HierarchyNode
from .shipments import current_manifest


LOCATION_KEY = "Device location"   # in the device's Item Specs DATA — the name is not yet agreed with Hajime
LOCATION_MAX = 60
LABEL_SHEET = "Letter-3x10-Avery"  # the print dialog's sheet until the browser remembers another


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


def _tray(container, device) -> dict | None:
    """A cable's bundle / tray from its current container; not the device itself."""
    if not container or container["part_id"] == device:
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
                bundle=_tray(trays.get(pid), part_id),
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
    connector free) and ``prefill`` — the PID when exactly one is open.

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
            open_ = [c["part_id"] for c in r["candidates"] if c["open"]]
            r["prefill"] = open_[0] if len(open_) == 1 else ""
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
    jobs = []
    for pid, name, lines in picked:
        lines = [] if show == "pid" else lines
        if show == "label" and not lines:
            continue
        with_code = code if show != "label" else None
        jobs.append((label_layout(sheet, lines, with_code, type_name),
                     {"part_id": pid, "part_name": name or "", "lines": lines}))
    return jobs
