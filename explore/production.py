"""Production status (#199 → #200) — pure engine, no views.

Anselmo's DPC-review table per consortium (Component · Needed · Produced ·
Completed by · Needed by · Float · Comment) is *generated*: each component
type carries its own **production plan** in HWDB — the type image
``Production_plan_<type>.json`` (needed, completed by, needed by, a
comment, who/when) — and a consortium's virtual type carries the ordered
**component list** it reports, ``Production_list_<type>.json``. HWDB never
overwrites a type image, so every save is a kept version: the newest by
name is the current value, the older ones the milestone history. The
counts come from the mirror. ``ProductionPlan`` / ``ProductionList`` cache
what was last read, for the type pages' plan lines (#174) and the
Detector area's overview.
"""

from __future__ import annotations

import io
import json
import logging
import re
from collections import Counter
from datetime import date

from .models import HwdbComponentEvent, HierarchyNode, ProductionList, ProductionPlan

logger = logging.getLogger(__name__)

_MONTH_RX = re.compile(r"^(\d{4})-(\d{2})(?:-\d{2})?$")   # a month, or a full date read by its month
PTID_RX = re.compile(r"^[A-Z]\d{11}$")
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
PLAN_KEYS = ("needed", "completed_by", "needed_by", "comment")
HISTORY_MAX = 12   # versions the plan page loads (one fetch each)


def plan_name(part_type_id: str) -> str:
    return f"Production_plan_{part_type_id}.json"


def list_name(part_type_id: str) -> str:
    return f"Production_list_{part_type_id}.json"


# ---- HWDB: read / write -----------------------------------------------------

def versions(rows, name: str) -> list[dict]:
    """The type's image rows named ``name``, newest first —
    ``[{image_id, created, comments}]``."""
    out = [{"image_id": str(r.get("image_id")), "created": str(r.get("created") or ""),
            "when": str(r.get("created") or "")[:16].replace("T", " "),
            "comments": str(r.get("comments") or "")}
           for r in (rows or []) if isinstance(r, dict) and r.get("image_name") == name]
    return sorted(out, key=lambda v: v["created"], reverse=True)


def _listing(api, part_type_id: str) -> list:
    try:
        return api.get_component_type_images(part_type_id).get("data") or []
    except Exception as e:  # noqa: BLE001 — HWDB down = nothing on the type
        logger.warning("production: image listing for %s failed: %s", part_type_id, e)
        return []


def _load(api, image_id: str):
    try:
        raw = json.loads(api.get_image_response(image_id).content)
    except Exception as e:  # noqa: BLE001
        logger.warning("production: image %s failed to load: %s", image_id, e)
        return None
    return raw if isinstance(raw, dict) else None


def _month(v) -> str:
    """``YYYY-MM`` out of a month or a full date; "" otherwise."""
    m = _MONTH_RX.match(str(v or "").strip())
    return f"{m.group(1)}-{m.group(2)}" if m and 1 <= int(m.group(2)) <= 12 else ""


def _int(v) -> int | None:
    try:
        n = float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return int(n) if n.is_integer() and n >= 0 else None


def normalize_plan(raw) -> dict:
    """A plan as the pages use it, whatever the stored JSON holds."""
    raw = raw if isinstance(raw, dict) else {}
    return {"needed": _int(raw.get("needed")),
            "completed_by": _month(raw.get("completed_by")),
            "needed_by": _month(raw.get("needed_by")),
            "comment": str(raw.get("comment") or "").strip(),
            "updated_by": str(raw.get("updated_by") or "").strip(),
            "updated": str(raw.get("updated") or "").strip()}


def normalize_list(raw) -> list[dict]:
    """``[{type, label}]`` — rows naming a well-formed type id, in order."""
    rows = (raw or {}).get("rows") if isinstance(raw, dict) else None
    out = []
    for r in rows or []:
        if isinstance(r, str):
            r = {"type": r}
        if not isinstance(r, dict):
            continue
        tid = str(r.get("type") or "").strip().upper()
        if PTID_RX.match(tid):
            out.append({"type": tid, "label": str(r.get("label") or "").strip()})
    return out


def read_plan(api, part_type_id: str, rows=None) -> tuple[dict | None, list[dict]]:
    """``(plan, versions)`` off the type: the newest
    ``Production_plan_<type>.json`` normalised (None when the type has
    none), and every version newest first. ``rows`` skips the listing
    when the caller has it."""
    vs = versions(_listing(api, part_type_id) if rows is None else rows, plan_name(part_type_id))
    if not vs:
        return None, []
    raw = _load(api, vs[0]["image_id"])
    return (normalize_plan(raw) if raw is not None else None), vs


def plan_history(api, vs: list[dict]) -> list[dict]:
    """The plan page's history: each version (newest first, at most
    ``HISTORY_MAX``) with its values — one fetch per version."""
    out = []
    for v in vs[:HISTORY_MAX]:
        raw = _load(api, v["image_id"])
        out.append({**v, "plan": normalize_plan(raw) if raw is not None else None})
    return out


def read_list(api, part_type_id: str, rows=None) -> tuple[list[dict] | None, list[dict]]:
    """``(rows, versions)`` off the consortium type: the newest
    ``Production_list_<type>.json`` normalised (None when there is none)."""
    vs = versions(_listing(api, part_type_id) if rows is None else rows, list_name(part_type_id))
    if not vs:
        return None, []
    raw = _load(api, vs[0]["image_id"])
    return (normalize_list(raw) if raw is not None else None), vs


def write_plan(api, part_type_id: str, plan: dict, reason: str) -> dict:
    """Post a plan version onto the type; the reason is the image's HWDB
    comment. Raises what the client raises."""
    body = {k: plan.get(k) for k in PLAN_KEYS} | {
        "updated_by": plan.get("updated_by") or "", "updated": plan.get("updated") or ""}
    return api.post_component_type_image(
        part_type_id, io.BytesIO(json.dumps(body, indent=2).encode()),
        plan_name(part_type_id), comments=reason or "Production plan (Explorer)")


def write_list(api, part_type_id: str, rows: list[dict], reason: str) -> dict:
    return api.post_component_type_image(
        part_type_id, io.BytesIO(json.dumps({"rows": rows}, indent=2).encode()),
        list_name(part_type_id), comments=reason or "Component list (Explorer)")


# ---- caches -----------------------------------------------------------------

def cache_plan(inst: str, part_type_id: str, plan: dict | None) -> None:
    """One ``ProductionPlan`` row per type: rewritten from ``plan``, dropped
    when the type has none."""
    if plan is None:
        ProductionPlan.objects.filter(instance=inst, part_type_id=part_type_id).delete()
        return
    ProductionPlan.objects.update_or_create(
        instance=inst, part_type_id=part_type_id,
        defaults={"needed": plan["needed"], "completed_by": plan["completed_by"],
                  "needed_by": plan["needed_by"], "comment": plan["comment"],
                  "updated_by": plan["updated_by"][:150], "updated": plan["updated"][:40]})


def cache_list(inst: str, part_type_id: str, rows: list[dict] | None) -> None:
    if rows is None:
        ProductionList.objects.filter(instance=inst, part_type_id=part_type_id).delete()
        return
    ProductionList.objects.update_or_create(instance=inst, part_type_id=part_type_id,
                                            defaults={"rows": rows})


def cached_plans(inst: str, type_ids: list[str]) -> dict[str, dict]:
    return {p.part_type_id: {"needed": p.needed, "completed_by": p.completed_by,
                             "needed_by": p.needed_by, "comment": p.comment,
                             "updated_by": p.updated_by, "updated": p.updated}
            for p in ProductionPlan.for_instance(inst).filter(part_type_id__in=type_ids)}


# ---- the mirror -------------------------------------------------------------

def counts(inst: str, type_ids: list[str]) -> dict[str, dict]:
    """Per type: its items in the mirror and the breakdown by HWDB status
    (most common first) — ``{tid: {n, by_status: [(status, n)]}}``."""
    c = Counter()
    for tid, st in (HwdbComponentEvent.for_instance(inst).filter(part_type_id__in=type_ids)
                    .values_list("part_type_id", "status")):
        c[(tid, st or "no status")] += 1
    out = {tid: {"n": 0, "by_status": []} for tid in type_ids}
    for (tid, st), n in c.most_common():
        out[tid]["n"] += n
        out[tid]["by_status"].append((st, n))
    return out


def names(inst: str, type_ids: list[str]) -> dict[str, str]:
    return dict(HierarchyNode.for_instance(inst)
                .filter(level=HierarchyNode.LEVEL_TYPE, part_type_id__in=type_ids)
                .values_list("part_type_id", "name"))


# ---- the table --------------------------------------------------------------

COLUMNS = ["Type ID", "Needed", "In HWDB", "Completed by", "Needed by", "Float (months)", "Comment"]


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


def table(rows: list[dict], plans: dict[str, dict], cnt: dict[str, dict],
          nm: dict[str, str], today: date | None = None) -> list[dict]:
    """The consortium's table: per listed type its label (or name), plan
    values and count, shaped for the partial — ``month`` cells carry
    ``past`` for the green tint, the count cell its status breakdown."""
    today = today or date.today()
    now = (today.year, today.month)
    out = []
    for r in rows:
        tid = r["type"]
        p = plans.get(tid) or {}
        c = cnt.get(tid) or {"n": 0, "by_status": []}
        done, need = p.get("completed_by") or "", p.get("needed_by") or ""
        fl = months_between(done, need)
        out.append({
            "type": tid, "label": r.get("label") or nm.get(tid) or tid,
            "has_plan": tid in plans,
            "needed": "" if p.get("needed") is None else f"{p['needed']:,}",
            "n": f"{c['n']:,}", "by_status": ", ".join(f"{n} {st}" for st, n in c["by_status"]),
            "completed_by": month_label(done), "completed_past": bool(_ym(done)) and _ym(done) <= now,
            "needed_by": month_label(need), "needed_past": bool(_ym(need)) and _ym(need) <= now,
            "float": "" if fl is None else str(fl),
            "comment": p.get("comment") or "",
            "updated_by": p.get("updated_by") or "", "updated": p.get("updated") or "",
        })
    return out


def summary(rows: list[dict], plans: dict[str, dict], today: date | None = None) -> dict:
    """The overview's index numbers for one consortium: listed components,
    the earliest Needed-by, rows whose Completed-by month has passed."""
    today = today or date.today()
    this_month = f"{today.year:04d}-{today.month:02d}"
    ps = [plans[r["type"]] for r in rows if r["type"] in plans]
    return {"n": len(rows),
            "needed_by": min((p["needed_by"] for p in ps if p["needed_by"]), default=""),
            "due": sum(1 for p in ps if p["completed_by"] and p["completed_by"] <= this_month)}
