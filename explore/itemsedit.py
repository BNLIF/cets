"""#166: bulk edit of items from the Type View — a pasted list (PIDs,
serial numbers, PID ranges) resolved against the mirror, the chosen
fields as one ``bulk-update`` record fragment, the mirror columns that
follow. Pure helpers; the view (``explore_items_edit_view``) does the
HWDB calls."""

from __future__ import annotations

import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from threading import local

from django.db.models import Count

from . import events, parts
from .checklistforms import ITEM_FIELD_LABELS, STATUS_OPTIONS
from .models import HwdbComponentEvent
from .plotting import pid_range

_SEP = re.compile(r"[\s,;]+")
_PID = re.compile(r"^[A-Za-z]\d{11}-\d{5}$")
FLAGS = ("qaqc_uploaded", "certified_qaqc", "is_installed")
CHUNK = 500   # rows per bulk-update call = per browser request (gunicorn's 30 s)
PICK_MAX = 500   # up to this many matched rows the preview lists them all, each with a checkbox
SHOW_MAX = 200   # above PICK_MAX only the first rows are shown, read-only
DEFAULT_COMMENT = "Patched by the Explorer"   # Hajime: HWDB skips a bulk row without a comment


def entries(text: str | None) -> list[str]:
    """The pasted list split on newline / comma / space, in order, deduped."""
    seen, out = set(), []
    for e in _SEP.split(text or ""):
        if e and e not in seen:
            seen.add(e)
            out.append(e)
    return out


def resolve(inst: str, ptid: str, text: str | None, status: str = "", sn: str = "",
            manufacturer: str = "", created_by: str = "") -> dict:
    """Mirror rows for the list: a full PID, a bare 5-digit suffix, a
    ``00120..06000`` range (#155 syntax) or a serial number per entry —
    narrowed by the match rules (status label, serial regex or substring,
    manufacturer name, creator); an empty list with a rule = every item the rule
    matches. ``unmatched`` names the entries no row answers to (a PID of
    another type, or one the rules exclude, included); ``shared`` = serials
    on more than one item, with their PIDs, which are NOT taken — the user
    pastes the PID they mean (#168)."""
    base = HwdbComponentEvent.for_instance(inst).filter(part_type_id=ptid)
    if status:
        base = base.filter(status=status)
    if manufacturer:
        base = base.filter(manufacturer=manufacturer)
    if created_by:
        base = base.filter(created_by=created_by)
    if sn:
        try:
            re.compile(sn)
            base = base.filter(serial_number__iregex=sn)
        except re.error:
            base = base.filter(serial_number__icontains=sn)
    by_pid: dict[str, HwdbComponentEvent] = {}
    unmatched, shared = [], []
    if not entries(text):
        if status or manufacturer or sn or created_by:
            for r in base.order_by("part_id"):
                by_pid[r.part_id] = r
        return {"rows": list(by_pid.values()), "unmatched": [], "shared": []}

    def add(rows) -> int:
        n = 0
        for r in rows:
            by_pid[r.part_id] = r
            n += 1
        return n

    for e in entries(text):
        rng = pid_range(e)
        if rng:
            lo, hi = rng
            qs = base
            if lo:
                qs = qs.filter(part_id__gte=f"{ptid}-{lo}")
            if hi:
                qs = qs.filter(part_id__lte=f"{ptid}-{hi}")
            if not add(qs):
                unmatched.append(e)
            continue
        pid = None
        if _PID.match(e):
            pid = e.upper()
        elif e.isdigit() and len(e) <= 5:
            pid = f"{ptid}-{e.zfill(5)}"
        if pid:
            if not add(base.filter(part_id=pid)):
                unmatched.append(e)
            continue
        hits = list(base.filter(serial_number__iexact=e))
        if len(hits) == 1:
            add(hits)
        elif hits:
            shared.append((e, sorted(h.part_id for h in hits)))
        else:
            unmatched.append(e)
    return {"rows": [by_pid[k] for k in sorted(by_pid)],
            "unmatched": unmatched, "shared": shared}


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def changes(post, manufacturers: list[dict]) -> tuple[dict, dict, list[str]]:
    """The fields the form asks to set → ``patch`` (the record fragment every
    row gets, HWDB shape), ``mirror`` (the mirror columns to write) and
    ``shown`` (one "Field → value" line each). Blank = leave alone; comments
    only when its replace box is ticked (an empty comment is a value)."""
    patch, mirror, shown = {}, {}, []
    sid = _int(post.get("status"))
    o = next((s for s in STATUS_OPTIONS if s["value"] == sid), None)
    if o:
        patch["status"] = {"id": sid}
        mirror.update(status=o["label"], status_id=sid)
        shown.append(f"{ITEM_FIELD_LABELS['status']} → {o['label']}")
    for f in FLAGS:
        v = post.get(f)
        if v in ("1", "0"):
            patch[f] = mirror[f] = v == "1"
            shown.append(f"{ITEM_FIELD_LABELS[f]} → {'yes' if v == '1' else 'no'}")
    mid = _int(post.get("manufacturer"))
    m = next((x for x in manufacturers if x["value"] == mid), None)
    if m:
        patch["manufacturer"] = {"id": mid}
        mirror["manufacturer"] = m["label"]
        shown.append(f"{ITEM_FIELD_LABELS['manufacturer']} → {m['label']}")
    if post.get("comments_set") == "on":
        patch["comments"] = (post.get("comments") or "").strip()
        shown.append(f"{ITEM_FIELD_LABELS['item_comments']} → “{patch['comments']}”")
    return patch, mirror, shown


def facet(inst: str, ptid: str, field: str) -> list[tuple[str, int]]:
    """Distinct values of a mirror column over the type with counts, biggest
    first — the match rule's choices ("" = not synced, shown as —)."""
    qs = (HwdbComponentEvent.for_instance(inst).filter(part_type_id=ptid)
          .values_list(field).annotate(n=Count("id")).order_by("-n"))
    return [(v or "", n) for v, n in qs]


def status_counts(rows) -> list[tuple[str, int]]:
    """Current status → count over the resolved rows, biggest first."""
    return Counter(r.status or "—" for r in rows).most_common()


def _page(client, ptid: str, page: int) -> dict:
    return client._make_request("GET", f"component-types/{ptid}/components",
                                params={"page": page, "size": 500})


def live_rows(api, ptid: str, make_api=None) -> dict[str, dict]:
    """The type's whole component listing, pid → row: 500 rows a page, the
    pages after the first fetched in parallel (``make_api`` builds a client
    per worker thread, the sync's pattern). Rows carry status, the flags,
    serial, comments and parent — not manufacturer. Every bulk-update row
    must echo the item's comments and serial (dev probe 2026-09-18: a row
    applies ONLY with a non-empty ``comments``; one without ``serial_number``
    NULLs the serial), and the same sweep refreshes the mirror through
    ``events.refresh_from_listing`` (Chao 2026-09-18: always the listing,
    and re-stamp the mirror to avoid staleness)."""
    tls = local()

    def _init():
        tls.client = make_api() if make_api else api

    first = _page(api, ptid, 1)
    pages = [first]
    n = (first.get("pagination") or {}).get("pages", 1)
    if n > 1:
        with ThreadPoolExecutor(max_workers=6, initializer=_init) as pool:
            pages += list(pool.map(lambda i: _page(tls.client, ptid, i), range(2, n + 1)))
    return {r["part_id"]: r for body in pages for r in body.get("data") or [] if r.get("part_id")}


def rows_for(items, patch: dict, mirror_rows, manufacturers: list[dict]) -> list[dict]:
    """``items`` = [(pid, current comments, current serial)] → the bulk-update
    rows: the chosen fields, plus ``comments`` echoed (``DEFAULT_COMMENT``
    when the item has none — blank comments make HWDB skip the row), ``serial_number``
    echoed, and ``manufacturer`` echoed from the mirror by name (a row
    without it WIPES the item's manufacturer; same probe — the listing has
    no manufacturer). Status and the flags are optional keys."""
    by_name = {m["label"]: m["value"] for m in manufacturers}
    man = {r.part_id: r.manufacturer for r in mirror_rows}
    out = []
    for pid, comments, serial in items:
        row = {"part_id": pid, **patch, "serial_number": serial}
        if "comments" not in patch:
            row["comments"] = comments or DEFAULT_COMMENT
        if "manufacturer" not in patch:
            mid = by_name.get(man.get(pid) or "")
            row["manufacturer"] = {"id": mid} if mid is not None else None
        out.append(row)
    return out
