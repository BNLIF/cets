"""Production status (#199) — pure engine, no views.

Anselmo's DPC-review table per consortium (Component · PRR date · Needed ·
Produced and tested · Completed by · Needed by · Float · Comments) lives in
HWDB as a checklist flagged ``"status": true`` on the consortium's virtual
type: one table, a named row per component, month columns for the dates,
a *Type IDs* column naming the real component types, always → Specs. This
module reads such a table off an item's specifications DATA, shapes it for
the status page, and caches the per-type plan (needed / completed by /
needed by) in ``ProductionPlan`` for the type pages' plan lines (#174) and
the Detector tab's consortia list. Column roles are recognised by label,
case-insensitively: ``Type ID`` / ``Type IDs``, ``Needed``, ``Completed by``,
``Needed by``, ``Float``. One type per row is the convention (Chao
2026-10-08): a cell naming several types still links them all and feeds
them the row's dates, but not its Needed total — the per-type split
isn't in the table.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date

from django.db import transaction

from . import checklistforms
from .models import ProductionPlan, ProductionTable

logger = logging.getLogger(__name__)

_MONTH_RX = re.compile(r"^(\d{4})-(\d{2})(?:-\d{2})?$")   # a month, or a full date read by its month
_PTID_RX = re.compile(r"[A-Z]\d{11}")
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def status_checklists(api, part_type_id: str) -> list[dict]:
    """Every checklist on the type flagged ``status`` — ``[{name, schema}]``,
    one image listing plus one fetch per checklist name."""
    out = []
    try:
        rows = api.get_component_type_images(part_type_id).get("data") or []
    except Exception as e:  # noqa: BLE001 — HWDB down = no checklists
        logger.warning("production status: image listing for %s failed: %s", part_type_id, e)
        return out
    for r in checklistforms.available(api, part_type_id, rows=rows):
        try:
            cfg = json.loads(api.get_image_response(r["image_id"]).content)
        except Exception as e:  # noqa: BLE001
            logger.warning("production status: checklist %s/%s failed to load: %s",
                           part_type_id, r["name"], e)
            continue
        if isinstance(cfg, dict) and cfg.get("status"):
            out.append({"name": r["name"], "schema": checklistforms.normalize(cfg, r["name"])})
    return out


def status_table(schema: dict) -> tuple[str, dict] | None:
    """``(section title, table field)`` of the first table with named rows
    in a status checklist; None when the checklist has none."""
    for title, f in checklistforms.leaf_fields(schema):
        if f["type"] == "table" and f.get("rows"):
            return title, f
    return None


def table_value(schema: dict, title: str, f: dict, data) -> dict:
    """The table's stored rows (``{row label: {column: value}}``) out of an
    item's specifications DATA — where ``spec_values`` put them: under the
    field's own Specs key at the top when it has one, else under the
    section title and the label."""
    if not isinstance(data, dict):
        return {}
    key = f.get("spec")
    path = [p for p in key.split(".") if p] if key else []
    titles = {t for t, _ in checklistforms.leaf_fields(schema)}
    claims = sum(1 for _t, g in checklistforms.leaf_fields(schema)
                 if g.get("to_spec") and g.get("spec") == key) if key else 0
    if path and claims == 1 and path[0] not in titles:
        node = data
        for p in path:
            node = node.get(p) if isinstance(node, dict) else None
    else:
        sec = data.get(title)
        node = sec.get(key or f["label"]) if isinstance(sec, dict) else None
    return node if isinstance(node, dict) else {}


def _col(cols: list[str], *names) -> str | None:
    """The first column whose label (lower-cased, stripped) is one of ``names``."""
    for c in cols:
        if c.strip().lower() in names:
            return c
    return None


def _type_col(cols: list[str]) -> str | None:
    for c in cols:
        if c.strip().lower().startswith("type id"):
            return c
    return None


def month_label(v) -> str:
    """``2027-03`` → ``Mar 2027``; anything else as written."""
    m = _MONTH_RX.match(str(v or "").strip())
    if m and 1 <= int(m.group(2)) <= 12:
        return f"{_MONTHS[int(m.group(2)) - 1]} {m.group(1)}"
    return str(v or "").strip()


def _ym(v) -> tuple[int, int] | None:
    m = _MONTH_RX.match(str(v or "").strip())
    return (int(m.group(1)), int(m.group(2))) if m and 1 <= int(m.group(2)) <= 12 else None


def months_between(a, b) -> int | None:
    """Whole months from month ``a`` to month ``b`` (the slide's Float)."""
    x, y = _ym(a), _ym(b)
    if x is None or y is None:
        return None
    return (y[0] - x[0]) * 12 + (y[1] - x[1])


def _text(v) -> str:
    if isinstance(v, bool):
        return "✓" if v else "✗"
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, int):
        return f"{v:,}"
    return "" if v is None else str(v)


def _int(v) -> int | None:
    try:
        n = float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return int(n) if n.is_integer() else None


def rows(f: dict, value: dict, today: date | None = None) -> dict:
    """The table shaped for the status page: ``columns`` (the table's,
    plus a computed ``Float (months)`` when it has Completed-by and
    Needed-by month columns but no Float column of its own) and ``rows``
    — per named row its cells in column order (``month`` cells carry
    ``past`` for the green tint, ``types`` cells the linked ids) and the
    plan values the cache keeps."""
    today = today or date.today()
    cols = list(f["columns"])
    months = set(f.get("months") or [])
    tcol = _type_col(cols)
    done_col = _col(cols, "completed by", "completed by date")
    need_col = _col(cols, "needed by", "needed by date")
    needed_col = _col(cols, "needed", "needed total", "total needed")
    add_float = (done_col in months and need_col in months
                 and _col(cols, "float", "float (months)") is None)
    out_cols = cols + (["Float (months)"] if add_float else [])
    out = []
    for rw in f.get("rows") or []:
        stored = value.get(rw["label"])
        merged = {**(f.get("texts") or {}), **(rw.get("texts") or {}),
                  **(stored if isinstance(stored, dict) else {})}
        cells, type_ids = [], []
        for c in cols:
            v = merged.get(c)
            if c in (f.get("dates") or []):
                ym = _ym(v)
                cells.append({"kind": "month", "text": str(v or "").strip(),
                              "past": bool(ym) and ym <= (today.year, today.month)})
            elif c in months:
                ym = _ym(v)
                cells.append({"kind": "month", "text": month_label(v),
                              "past": bool(ym) and ym <= (today.year, today.month)})
            elif c == tcol:
                type_ids = _PTID_RX.findall(str(v or "").upper())
                cells.append({"kind": "types", "text": _text(v), "ids": type_ids})
            else:
                cells.append({"kind": "text", "text": _text(v)})
        done = merged.get(done_col) if done_col else None
        need = merged.get(need_col) if need_col else None
        if add_float:
            fl = months_between(done, need)
            cells.append({"kind": "text", "text": "" if fl is None else str(fl)})
        out.append({"label": rw["label"], "cells": cells, "type_ids": type_ids,
                    "needed": _int(merged.get(needed_col)) if needed_col else None,
                    # the plan is in months: a full date is cut to its month
                    "completed_by": str(done or "").strip()[:7] if _ym(done) else "",
                    "needed_by": str(need or "").strip()[:7] if _ym(need) else ""})
    return {"columns": out_cols, "rows": out}


def shape(schema: dict, data) -> dict | None:
    """``rows()`` of the status checklist's table off an item's DATA; None
    when the checklist has no named-row table."""
    found = status_table(schema)
    if found is None:
        return None
    title, f = found
    return rows(f, table_value(schema, title, f, data))


def card(name: str, schema: dict, data, as_of: str = "") -> dict | None:
    """What one status checklist shows for one item: its title and
    instructions with the shaped table; None without a named-row table."""
    shaped = shape(schema, data)
    if shaped is None:
        return None
    return {"checklist": name, "title": schema["name"], "instructions": schema["instructions"],
            "columns": shaped["columns"], "rows": shaped["rows"], "as_of": as_of}


@transaction.atomic
def refresh(inst: str, source_type_id: str, source_part_id: str, serial: str, c: dict | None,
            checklist: str = "") -> int:
    """Rewrite what the cache holds for one (item, status checklist): the
    table itself (``ProductionTable``) and one plan row per real type a row
    names, a blank-type row for a row naming none (so the Detector tab still
    counts it). ``c`` None (the checklist lost its table) clears both. Type
    pages read only the plan rows naming them and otherwise fall back to
    their browser-stored plan."""
    name = (c or {}).get("checklist") or checklist
    ProductionTable.objects.filter(instance=inst, source_part_id=source_part_id, checklist=name).delete()
    ProductionPlan.objects.filter(instance=inst, source_part_id=source_part_id, checklist=name).delete()
    if c is None:
        return 0
    ProductionTable.objects.create(
        instance=inst, source_type_id=source_type_id, source_part_id=source_part_id,
        checklist=name, title=c["title"][:200], serial=(serial or "")[:120],
        instructions=c["instructions"], columns=c["columns"], rows=c["rows"], as_of=c["as_of"][:40])
    new = []
    for r in c["rows"]:
        one = len(r["type_ids"]) <= 1   # several types in one row: dates only, the total isn't theirs
        for tid in r["type_ids"] or [""]:
            new.append(ProductionPlan(
                instance=inst, part_type_id=tid, source_type_id=source_type_id,
                source_part_id=source_part_id, checklist=name, component=r["label"][:200],
                needed=r["needed"] if one else None,
                completed_by=r["completed_by"], needed_by=r["needed_by"]))
    ProductionPlan.objects.bulk_create(new)
    return len(new)


def latest_data(record: dict):
    """An item's latest specifications DATA (HWDB keeps a history, newest
    last) and when it was written."""
    spec = (record or {}).get("specifications")
    if isinstance(spec, list):
        spec = next((d for d in reversed(spec) if isinstance(d, dict)), None)
    if not isinstance(spec, dict):
        return None, ""
    return spec.get("DATA"), str(spec.get("created") or "")
