"""#206 (Anselmo 2026-10-20): the P6 schedule — the monthly
``Float_Chart_Activities_Combined.xlsx`` the project manager exports.

Every component sheet has the same columns (``Detector`` · ``Component``
· ``Prod Activity ID`` / ``Name`` · ``Install Activity ID`` / ``Name``
· ``Production End Date`` · ``Installation Start Date`` · the two date
sources · ``Float (days)`` · ``Notes``); rows are batches, so an
activity id repeats. An upload keeps one ``P6Activity`` per (id, kind):
a production id with its end date, an installation id with its start
date. ``Float`` is the sheet's own ``K-I`` formula and is not read — the
status table computes its own. Sheets without the id column (DAQ
milestones) are skipped. Not stored in HWDB: the file is project-wide,
not per instance (Chao 2026-10-20).
"""

from __future__ import annotations

import io
from datetime import date, datetime

from django.db import transaction

from .models import P6Activity, P6Upload, ProductionPlan

COL_ID = "Prod Activity ID"
_COLS = {"detector": "Detector", "component": "Component",
         "prod_id": "Prod Activity ID", "prod_name": "Prod Activity Name",
         "prod_date": "Production End Date", "prod_src": "Prod Date Source",
         "inst_id": "Install Activity ID", "inst_name": "Install Activity Name",
         "inst_date": "Installation Start Date", "inst_src": "Install Date Source",
         "notes": "Notes"}


class P6Error(ValueError):
    """What the upload page shows — the sheet and row of the first problem."""


def _text(v) -> str:
    return "" if v is None else str(v).strip()


def _date(v, where: str) -> date | None:
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(_text(v)[:10])
    except ValueError:
        raise P6Error(f"{where}: {v!r} is not a date") from None


def parse(name: str, blob: bytes) -> list[dict]:
    """The activities of every component sheet, one per (id, kind), first
    occurrence first — ``[{activity_id, kind, name, date, source,
    detector, sheet, component, notes}]``. Raises ``P6Error``."""
    if not (name or "").lower().endswith((".xlsx", ".xlsm")):
        raise P6Error("The P6 schedule is an .xlsx file.")
    import openpyxl
    try:
        wb = openpyxl.load_workbook(io.BytesIO(blob), read_only=True, data_only=True)
    except Exception as e:  # noqa: BLE001 — openpyxl raises many things for a bad file
        raise P6Error(f"Not a readable .xlsx file ({e.__class__.__name__}).") from None
    out, seen = [], set()
    try:
        for ws in wb.worksheets:
            rows = ws.iter_rows(values_only=True)
            header = [_text(h) for h in (next(rows, None) or ())]
            if COL_ID not in header:
                continue   # the DAQ milestone sheet, or anything else
            col = {k: header.index(h) for k, h in _COLS.items() if h in header}
            get = lambda r, k: r[col[k]] if k in col and col[k] < len(r) else None   # noqa: E731
            for n, r in enumerate(rows, start=2):
                if not any(v not in (None, "") for v in r):
                    continue
                base = {"detector": _text(get(r, "detector"))[:8], "sheet": ws.title[:60],
                        "component": _text(get(r, "component"))[:120], "notes": _text(get(r, "notes"))}
                for kind, k_id, k_name, k_date, k_src in (
                        (P6Activity.KIND_PROD, "prod_id", "prod_name", "prod_date", "prod_src"),
                        (P6Activity.KIND_INSTALL, "inst_id", "inst_name", "inst_date", "inst_src")):
                    aid = _text(get(r, k_id))[:60]
                    if not aid or (aid, kind) in seen:
                        continue
                    seen.add((aid, kind))
                    out.append({**base, "activity_id": aid, "kind": kind,
                                "name": _text(get(r, k_name))[:300],
                                "date": _date(get(r, k_date), f"{ws.title} row {n}"),
                                "source": _text(get(r, k_src))[:40]})
    finally:
        wb.close()
    if not out:
        raise P6Error(f"No sheet with a “{COL_ID}” column.")
    return out


@transaction.atomic
def replace(rows: list[dict], who: str, filename: str) -> P6Upload:
    """The new upload: every activity row rewritten, one upload row kept."""
    P6Activity.objects.all().delete()
    P6Activity.objects.bulk_create([P6Activity(**r) for r in rows])
    P6Upload.objects.all().delete()
    return P6Upload.objects.create(uploaded_by=who[:150], filename=(filename or "")[:200], n_rows=len(rows))


def compare(rows: list[dict]) -> dict | None:
    """Chao 2026-10-22: how an upload differs from the current table —
    guards against the wrong file. ``None`` with no table yet; else
    ``{n_old, n_new, missing, plan_missing, changed, warn}``: the current
    activities the file lacks, those of them a plan names, the dates that
    move; ``warn`` when a plan's id would go or over a fifth are missing."""
    old = {(a.activity_id, a.kind): a for a in P6Activity.objects.all()}
    if not old:
        return None
    new = {(r["activity_id"], r["kind"]): r for r in rows}
    missing = [k for k in old if k not in new]
    changed = sum(1 for k, r in new.items() if k in old and old[k].date != r["date"])
    used = set()
    for prod, inst in ProductionPlan.objects.values_list("p6_completed_id", "p6_needed_id"):
        if prod:
            used.add((prod, P6Activity.KIND_PROD))
        if inst:
            used.add((inst, P6Activity.KIND_INSTALL))
    plan_missing = sorted(k[0] for k in missing if k in used)
    return {"n_old": len(old), "n_new": len(new), "missing": len(missing), "plan_missing": plan_missing,
            "changed": changed, "warn": bool(plan_missing) or len(missing) > len(old) / 5}


def to_json(rows: list[dict]) -> list[dict]:
    """The parsed rows as the session keeps them while a warned upload waits for its confirmation."""
    return [{**r, "date": r["date"].isoformat() if r["date"] else None} for r in rows]


def from_json(rows: list[dict]) -> list[dict]:
    return [{**r, "date": date.fromisoformat(r["date"]) if r["date"] else None} for r in rows]


def current() -> P6Upload | None:
    return P6Upload.objects.order_by("-uploaded").first()


def lookup(ids: set[str]) -> dict[tuple[str, str], P6Activity]:
    """``{(activity_id, kind): activity}`` for the ids a set of plans name."""
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return {(a.activity_id, a.kind): a for a in P6Activity.objects.filter(activity_id__in=ids)}


def options() -> list[dict]:
    """Every activity for the plan page's pickers (~300 rows, inlined)."""
    return [{"id": a.activity_id, "kind": a.kind, "name": a.name,
             "date": a.date.isoformat() if a.date else "", "source": a.source,
             "detector": a.detector, "sheet": a.sheet, "component": a.component}
            for a in P6Activity.objects.all()]
