"""The Cable connections page's model (#226, the cabling tickets under #222).

One **endpoint device** — a non-cable item a cable plugs into — its positions
that take a cable, and where each connected cable goes. HWDB writes a cable
link on the device only (``<cable PID>.<END>:<n>`` at a position); the cable's
own rows say what else it is connected to (ADR-0018).

Reads are bounded by the device: its record, its type and its positions once,
each connected cable's rows and container once, each cable type's record once.
No sweep over a type, nothing written, nothing added to the mirror.
"""

from __future__ import annotations

from . import parts
from .models import HierarchyNode
from .shipments import current_manifest


def _type_id(part_id: str) -> str:
    return part_id.rsplit("-", 1)[0]


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


def _tray(container, device) -> dict | None:
    """A cable's bundle / tray from its current container; not the device itself."""
    if not container or container["part_id"] == device:
        return None
    return {"part_id": container["part_id"], "type_name": container["type_name"], "also": []}


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
    - ``status`` per row — ``available``, ``connected``, ``installed`` (every
      END:connector of the cable is connected; Hajime, slide 15) or ``noend``;
    - ``bundle`` per row — the cable's bundle / tray, the item that holds it by
      plain PID (``part_id``, ``type_name``, and ``also``: the numbers of this
      device's other rows whose cable sits in the same one); None for a cable
      in none, or held that way by this very device;
    - ``accepts`` per row — the type ids the position takes;
    - ``type_record`` — the device type's record, for the role banner;
    - ``n_connected`` — rows connected or installed;
    - ``others`` — the distinct items on the other side, each with the number
      of this device's cables going there, for Change working device.

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
           "rows": [], "n_connected": 0, "others": [], "type_record": {}}
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
    slots = parts.fetch_map(
        api, lambda c, t: len((c.get_component_type(t).get("data") or {}).get("connectors") or {}),
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
            total = slots.get(_type_id(pid)) or 0
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
                others=list(sides.values()),
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
    for row in out["rows"]:
        if row["bundle"]:
            row["bundle"]["also"] = [r["n"] for r in out["rows"] if r is not row and r["bundle"]
                                     and r["bundle"]["part_id"] == row["bundle"]["part_id"]]
    out["n_connected"] = sum(r["status"] in ("connected", "installed") for r in out["rows"])
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
