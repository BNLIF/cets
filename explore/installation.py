"""Installation plan (#217) — pure engine, no views.

Anselmo + Hajime 2026-11-12: production tables go by component type, but
installation is a sequence of **steps**, each needing certain components.
A plan is the type image ``Installation_plan_<type>.json`` — on a
detector's virtual type, or on a component's own type for its detailed
plan — kept the way the production list is (``production.py``): every
save a version, the newest by name the current one, the image comment
the reason.

A step: its number, name, zone, the earlier steps it comes ``after``
(advisory), a P6 installation activity, a one-line note and longer
Markdown details, and its parts. A part: a
component type, how many, and the name of the checklist on that type
whose record means "installed". Progress is then the mirror's test
events of that checklist's test type — no HWDB call. ``InstallationPlan``
caches the plan as last read, with each part's test type resolved, for
the overview.

A component's own plan sits on the component's type: its steps list the
type itself as their part (``<own type> x 80 | Hang the CRP``), so every
step is a record on the item. A detector plan's part of that type names
the checklist that counts itself, as any part does.

#218 (Anselmo's units table): a part may also name the checklists that
record its QC before and after installation (``before`` / ``after``); the
units page lists the type's items with a tick per stage, and the position
and readout port the installation record left in the item's
Specifications.

A step's status is worked out from its parts' counts unless someone set
it by hand (``status``: ``todo`` / ``prog`` / ``done`` / ``hold``, with
who and when) — a step without parts, or one finished before its records
are in, has no other way to read Done. The hand-set status is part of the
plan file: setting it is a new version.
"""

from __future__ import annotations

import io
import json
import re

from . import p6, production
from .models import HwdbTestEvent, InstallationPlan, P6Activity

PTID_RX = production.PTID_RX
_PART_RX = re.compile(r"^([A-Za-z]\d{11})\s*[x×]\s*([\d,]+)$")
_STEP_RX = re.compile(r"^(\d+)\s*\*?$")   # a trailing * was the "installed" mark of the first drafts: read, ignored
_STATUS_RX = re.compile(r"^status\s*:\s*(.*)$", re.I)
RESOLVED = ("test_type", "own_plan", "used", "procedures", "before_tt", "after_tt")   # what a live read adds to a part
STATUSES = {"todo": "Not started", "prog": "In progress", "done": "Done", "hold": "On hold"}
_STATUS_OF = {v.lower(): k for k, v in STATUSES.items()} | {k: k for k in STATUSES}


def plan_name(part_type_id: str) -> str:
    return f"Installation_plan_{part_type_id}.json"


def normalize(raw) -> list[dict]:
    """The steps as the pages use them, whatever the stored JSON holds:
    ``[{n, name, zone, after, p6, note, details, status, status_by,
    status_on, parts: [{type, count, checklist}]}]`` in the stored order;
    ``status`` "" = worked out from the counts."""
    out, seen = [], set()
    for s in (raw.get("steps") if isinstance(raw, dict) else None) or []:
        if not isinstance(s, dict):
            continue
        n = production._int(s.get("n"))
        if not n or n in seen:
            continue
        seen.add(n)
        parts = []
        for p in s.get("parts") or []:
            tid = str((p or {}).get("type") or "").strip().upper() if isinstance(p, dict) else ""
            if PTID_RX.match(tid):
                parts.append({"type": tid, "count": production._int(p.get("count")) or 0,
                              "checklist": str(p.get("checklist") or "").strip(),
                              "before": str(p.get("before") or "").strip(), "after": str(p.get("after") or "").strip()})
        status = s.get("status") if s.get("status") in STATUSES else ""
        out.append({"n": n, "name": str(s.get("name") or "").strip(), "zone": str(s.get("zone") or "").strip(),
                    "after": [a for a in (production._int(x) for x in s.get("after") or []) if a],
                    "p6": str(s.get("p6") or "").strip()[:60], "note": " ".join(str(s.get("note") or "").split()),
                    "details": str(s.get("details") or "").strip(), "status": status,
                    "status_by": str(s.get("status_by") or "")[:150] if status else "",
                    "status_on": str(s.get("status_on") or "")[:10] if status else "",
                    "parts": parts})
    return out


def parse_text(text: str) -> tuple[list[dict], list[str]]:
    """The edit page's text form → ``(steps, errors)``. A line without
    indentation is a zone; under it a step, ``number | name | after 3, 4 |
    P6 activity | note``; under a step its parts, ``TYPEID x count |
    checklist | QC-before checklist | QC-after checklist``, its details, Markdown, on lines starting ``>`` (the note
    of the step line is the short description), and ``status: Done`` when
    its status is set by hand. What follows the first field may be left
    out."""
    steps, errors, zone, cur = [], [], "", None
    for i, raw in enumerate((text or "").splitlines(), 1):
        if not raw.strip():
            continue
        if raw.strip().startswith(">"):
            if cur is None:
                errors.append(f"Line {i}: details need a step above them.")
            else:
                cur["details"] += ("\n" if cur["details"] else "") + raw.strip()[1:].removeprefix(" ").rstrip()
            continue
        st = _STATUS_RX.match(raw.strip())
        if st and cur is not None:
            key = _STATUS_OF.get(st.group(1).strip().lower())
            if key is None:
                errors.append(f"Line {i}: a status is one of {', '.join(STATUSES.values())}.")
            else:
                cur["status"] = key
            continue
        f = [x.strip() for x in raw.strip().split("|")]
        m = _PART_RX.match(f[0])
        if m:
            if cur is None:
                errors.append(f"Line {i}: a component needs a step above it.")
                continue
            cur["parts"].append({"type": m.group(1).upper(), "count": int(m.group(2).replace(",", "")),
                                 "checklist": f[1] if len(f) > 1 else "",
                                 "before": f[2] if len(f) > 2 else "", "after": f[3] if len(f) > 3 else ""})
        elif _STEP_RX.match(f[0]):
            n = int(_STEP_RX.match(f[0]).group(1))
            if not n or any(s["n"] == n for s in steps):
                errors.append(f"Line {i}: step {n} is already there." if n else f"Line {i}: steps count from 1.")
                cur = None
                continue
            after = [int(a) for a in re.findall(r"\d+", f[2])] if len(f) > 2 else []
            cur = {"n": n, "name": f[1] if len(f) > 1 else "", "zone": zone, "after": after,
                   "p6": (f[3] if len(f) > 3 else "")[:60], "note": " | ".join(f[4:]), "details": "",
                   "status": "", "status_by": "", "status_on": "", "parts": []}
            steps.append(cur)
        elif len(f) == 1 and raw[:1] not in " \t":
            zone, cur = f[0], None
        else:
            errors.append(f"Line {i}: write a step as “number | name”, a component as “TYPEID x count | checklist”.")
    return steps, errors


def to_text(steps: list[dict]) -> str:
    """The steps as the text form (the inverse of ``parse_text``, but for
    who set a status and when — ``stamp`` carries those over a save)."""
    out, zone = [], None
    for s in steps:
        if s["zone"] != zone:
            zone = s["zone"]
            if zone:
                out.append(zone)
        f = [str(s["n"]), s["name"], ("after " + ", ".join(map(str, s["after"]))) if s["after"] else "", s["p6"], s["note"]]
        while len(f) > 2 and not f[-1]:
            f.pop()
        out.append("  " + " | ".join(f))
        if s.get("status"):
            out.append("    status: " + STATUSES[s["status"]])
        for p in s["parts"]:
            f = [f"{p['type']} x {p['count']}", p["checklist"], p.get("before") or "", p.get("after") or ""]
            while len(f) > 1 and not f[-1]:
                f.pop()
            out.append("    " + " | ".join(f))
        out += [("    > " + ln).rstrip() for ln in (s.get("details") or "").splitlines()]
    return "\n".join(out)


def stamp(new: list[dict], old: list[dict] | None, who: str, when: str) -> list[dict]:
    """``new`` with each hand-set status signed: who and when carried over
    from ``old`` where the step's status is unchanged, ``who`` / ``when``
    where it was set or changed in this save."""
    was = {s["n"]: s for s in old or []}
    for s in new:
        o = was.get(s["n"]) or {}
        if not s.get("status"):
            s["status_by"] = s["status_on"] = ""
        elif o.get("status") == s["status"]:
            s["status_by"], s["status_on"] = o.get("status_by") or "", o.get("status_on") or ""
        else:
            s["status_by"], s["status_on"] = who, when
    return new


def read(api, part_type_id: str, rows=None) -> tuple[list[dict] | None, list[dict]]:
    """``(steps, versions)`` off the type: the newest plan normalised
    (None when the type has none), every version newest first."""
    vs = production.versions(production._listing(api, part_type_id) if rows is None else rows, plan_name(part_type_id))
    if not vs:
        return None, []
    raw = production._load(api, vs[0]["image_id"])
    return (normalize(raw) if raw is not None else None), vs


def write(api, part_type_id: str, steps: list[dict], reason: str, who: str = "", when: str = "") -> dict:
    """Post a plan version onto the type — the plan alone, without what a
    live read resolved onto its parts."""
    body = [{**s, "parts": [{k: v for k, v in p.items() if k not in RESOLVED} for p in s["parts"]]} for s in steps]
    return api.post_component_type_image(
        part_type_id, io.BytesIO(json.dumps({"steps": body, "updated_by": who, "updated": when}, indent=2).encode()),
        plan_name(part_type_id), comments=reason or "Installation plan (Explorer)")


def cache(inst: str, part_type_id: str, steps: list[dict] | None) -> None:
    """One ``InstallationPlan`` row per type: rewritten from ``steps``
    (parts carrying their resolved ``test_type`` when the caller has
    them), dropped when the type has no plan."""
    if steps is None:
        InstallationPlan.objects.filter(instance=inst, part_type_id=part_type_id).delete()
        return
    InstallationPlan.objects.update_or_create(instance=inst, part_type_id=part_type_id, defaults={"steps": steps})


def keep_resolved(inst: str, part_type_id: str, steps: list[dict]) -> list[dict]:
    """A just-saved plan's steps with what the cache already resolved for the same (type, checklist) — the plan page
    resolves the rest on its next read."""
    old = InstallationPlan.for_instance(inst).filter(part_type_id=part_type_id).first()
    known = {(p["type"], p["checklist"]): p for s in (old.steps if old else []) for p in s.get("parts") or []}
    return [{**s, "parts": [{**p, **{k: v for k, v in known.get((p["type"], p["checklist"]), {}).items()
                                    if k in RESOLVED}} for p in s["parts"]]} for s in steps]


def installed(inst: str, steps: list[dict]) -> dict[tuple[str, str], int]:
    """``{(type, test type): items with a record}`` off the mirror's test
    events, for every part whose checklist resolved to a test type."""
    want = {(p["type"], p["test_type"]) for s in steps for p in s["parts"] if p.get("test_type")}
    if not want:
        return {}
    rows = (HwdbTestEvent.for_instance(inst)
            .filter(part_type_id__in={t for t, _ in want}, test_type_name__in={tt for _, tt in want})
            .values_list("part_type_id", "test_type_name", "part_id").distinct())
    out: dict[tuple[str, str], int] = {}
    for tid, tt, _pid in rows:
        if (tid, tt) in want:
            out[(tid, tt)] = out.get((tid, tt), 0) + 1
    return out


def table(steps: list[dict], done: dict, names: dict[str, str]) -> list[dict]:
    """The steps table's rows — zone (level 0), step (1), part (2) — with
    each part's installed count, each step's sum, its P6 start and status
    (``state``: the hand-set one, else from the counts — ``auto``), and a
    warning on a started step that comes after an unfinished one."""
    acts = p6.lookup({s["p6"] for s in steps})
    state, rows, zone = {}, [], None
    for s in steps:
        parts = []
        for p in s["parts"]:
            n = done.get((p["type"], p.get("test_type") or ""), 0) if p.get("test_type") else None
            pst = "todo" if not n else ("done" if p["count"] and n >= p["count"] else "prog")
            parts.append({"kind": "part", "level": 2, "key": f"{s['n']}-{p['type']}", "type": p["type"],
                          "label": names.get(p["type"]) or p["type"], "count": p["count"], "n": n, "shown": min(n or 0, p["count"]),
                          "checklist": p.get("used") or p["checklist"], "own_plan": bool(p.get("own_plan")),
                          "procedures": p.get("procedures") or [], "state": pst, "state_label": STATUSES[pst],
                          "problem": "" if p.get("test_type") else (
                              f"No checklist “{p['checklist']}” with a test type on this type" if p["checklist"]
                              else "No checklist named for this component")})
        total = sum(p["count"] for p in parts)
        got = sum(min(p["n"] or 0, p["count"]) for p in parts)
        auto = "todo" if not got else ("done" if all(p["state"] == "done" for p in parts) else "prog")
        st = s.get("status") or auto
        state[s["n"]] = st
        act = acts.get((s["p6"], P6Activity.KIND_INSTALL))
        if s["zone"] != zone:
            zone = s["zone"]
            rows.append({"kind": "zone", "level": 0, "key": f"z{s['n']}", "label": zone or "Steps", "has_children": True})
        rows.append({"kind": "step", "level": 1, "key": str(s["n"]), "step": s["n"], "label": s["name"], "note": s["note"], "details": s.get("details") or "",
                     "count": total, "n": got if parts else None, "state": st, "state_label": STATUSES[st], "after": s["after"],
                     "status": s.get("status") or "", "status_by": s.get("status_by") or "", "status_on": s.get("status_on") or "",
                     "auto_label": STATUSES[auto],
                     "p6": s["p6"], "p6_date": act.date if act else None, "p6_name": act.name if act else "",
                     "p6_missing": bool(s["p6"]) and act is None, "has_children": bool(parts),
                     "parts": parts})   # the step's panel lists them
        rows += parts
    by = {r["step"]: r for r in rows if r["kind"] == "step"}
    for r in by.values():
        r["after_steps"] = [{"n": a, "label": by[a]["label"], "state": by[a]["state"], "state_label": by[a]["state_label"]} for a in r["after"] if a in by]
        if r["state"] in ("prog", "done"):
            late = [a for a in r["after"] if state.get(a, "done") != "done"]
            r["warn"] = ("Started before step " + ", ".join(map(str, late)) + " is done") if late else ""
    return rows


POSITION_KEYS, PORT_KEYS = ("position", "geographical location"), ("readout port",)


def spec_find(obj, names: tuple[str, ...]) -> str:
    """The first scalar value under a key named (any case) one of
    ``names``, anywhere in an item's specifications; "" when none."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).strip().lower() in names and isinstance(v, (str, int, float)) and str(v).strip():
                return str(v).strip()
        obj = list(obj.values())
    if isinstance(obj, list):
        for v in obj:
            got = spec_find(v, names)
            if got:
                return got
    return ""


UNITS_PAGE = 50   # items a units table reads and draws at a time


def unit_columns(part: dict, own_steps: list[dict] | None = None) -> list[dict]:
    """#218: the stage columns of a part's units table, in order —
    ``[{label, name, tt, kind}]``: Anselmo's three (``before`` /
    ``install`` / ``after``; ``name`` "" when the plan names no checklist
    for it), or, when the part's type has a plan of its own
    (``own_steps``, resolved), one per step of that plan recorded on the
    type itself (``kind`` ``step``)."""
    own = [{"label": f"{s['n']} · {s['name']}", "name": p.get("used") or p["checklist"], "tt": p.get("test_type") or "", "kind": "step"}
           for s in own_steps or [] for p in s["parts"] if p["type"] == part["type"] and p["checklist"]]
    return own or [
        {"label": "QC before installation", "name": part.get("before") or "", "tt": part.get("before_tt") or "", "kind": "before"},
        {"label": "Installed", "name": part.get("used") or part["checklist"], "tt": part.get("test_type") or "", "kind": "install"},
        {"label": "QC after installation", "name": part.get("after") or "", "tt": part.get("after_tt") or "", "kind": "after"}]


def units(cols: list[dict], listing: list[dict], records: dict) -> list[dict]:
    """#218: one page of a type's items as a units table's rows —
    ``listing`` the type's live component rows (status, location,
    specifications), ``records`` ``{(pid, test type): (when, by)}`` off
    the mirror. ``cells`` follow ``cols``: None when the column names no
    checklist, else ``{name, when, by, known}`` (``when`` None: not
    recorded; ``known`` False: the checklist was not found on the type)."""
    out = []
    for r in listing:
        pid = r.get("part_id") or ""
        if not pid:
            continue
        cells = []
        for c in cols:
            when, by = records.get((pid, c["tt"]), (None, "")) if c["tt"] else (None, "")
            cells.append({"name": c["name"], "when": when, "by": by, "known": bool(c["tt"]), "kind": c["kind"]} if c["name"] else None)
        out.append({"pid": pid, "serial": r.get("serial_number") or "", "status": r.get("status"), "location": r.get("location"),
                    "position": spec_find(r.get("specifications"), POSITION_KEYS),
                    "port": spec_find(r.get("specifications"), PORT_KEYS), "cells": cells})
    return out


def summary(rows: list[dict]) -> dict:
    steps = [r for r in rows if r["kind"] == "step"]
    return {"n_steps": len(steps), "n_done": sum(r["state"] == "done" for r in steps),
            "n_prog": sum(r["state"] == "prog" for r in steps)}
