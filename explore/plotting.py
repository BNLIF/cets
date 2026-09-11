"""Type-wide plot data (#144): a live Item-Specifications sweep, one flat
row per item, streamed as NDJSON so the browser can show progress on big
types and cache the result (IndexedDB) for client-side plotting.

Why live, not mirrored: ``GET components?part_type_id=`` rows carry the full
nested ``specifications`` (identical to the detail record — 2026-09-10 dev
probe), so a whole type is one paginated sweep, not a per-item fan-out. The
mirror-light rule targets the latter. Test data has no such endpoint and
will arrive via #143 as a second source.
"""

from __future__ import annotations

import json
from typing import Iterator

from django.core.cache import cache
from django.db.models import Count, Max

from . import parts
from .events import _parse_created, _ref_name
from .models import HwdbComponentEvent, HwdbTestData

PAGE_SIZE = 500


def _latest_spec_data(row: dict):
    """The free-form ``DATA`` blob of the latest specifications entry (the
    same latest-entry rule as ``shipments._spec_block``); the entry itself
    when it has no ``DATA`` key; ``{}`` when there are no specs."""
    specs = row.get("specifications") or []
    entry = specs[-1] if specs else None
    if not isinstance(entry, dict):
        return {}
    data = entry.get("DATA")
    return data if isinstance(data, dict) else entry


def flat_row(row: dict) -> dict:
    """One list row → the item fields the plot page filters on + its spec data."""
    created, updated = _parse_created(row.get("created")), _parse_created(row.get("updated"))
    return {
        "pid": row.get("part_id") or "",
        "serial": row.get("serial_number") or "",
        "status": parts.normalize_status(row.get("status")) or "",
        "creator": _ref_name(row.get("creator")),
        "manufacturer": _ref_name(row.get("manufacturer")),
        "institution": _ref_name(row.get("institution")),
        "created": created.date().isoformat() if created else "",
        "updated": updated.date().isoformat() if updated else "",
        "data": _latest_spec_data(row),
    }


def _pages(api, part_type_id: str) -> Iterator[tuple[int, int, list]]:
    """``(page, pages, rows)`` per page of ``components?part_type_id=``."""
    page = 1
    while True:
        body = api._make_request(
            "GET", "components",
            params={"part_type_id": part_type_id, "page": page, "size": PAGE_SIZE},
        )
        rows = body.get("data") or []
        pages = (body.get("pagination") or {}).get("pages") or 1
        yield page, pages, rows
        if page >= pages or not rows:
            return
        page += 1


def stream_specs(api, part_type_id: str) -> Iterator[str]:
    """NDJSON lines: ``{"pages": P}`` first, one item row per line, a
    ``{"page": n}`` marker after each page, ``{"done": N}`` last. Errors
    surface as ``{"error": "..."}`` and end the stream."""
    n = 0
    try:
        for page, pages, rows in _pages(api, part_type_id):
            if page == 1:
                yield json.dumps({"pages": pages}) + "\n"
            for r in rows:
                n += 1
                yield json.dumps(flat_row(r), default=str) + "\n"
            yield json.dumps({"page": page}) + "\n"
    except Exception as e:  # network / HWDB — the client shows the message
        yield json.dumps({"error": f"{type(e).__name__}: {e}"}) + "\n"
        return
    yield json.dumps({"done": n}) + "\n"


# ---- test_data source (#143): served per key from the HwdbTestData mirror ----

def walk_keys(node, prefix: tuple, acc: dict) -> None:
    """Every leaf path under ``node`` → ``acc[path] += 1`` once per call
    (call once per item). Lists of dicts explode (their keys join the same
    prefix); a list of scalars is one leaf. Mirrors the Plot page's JS walk,
    so specs and test_data keys look the same to the user."""
    if isinstance(node, list):
        if any(isinstance(e, dict) for e in node):
            seen: dict = {}
            for e in node:
                if isinstance(e, dict):
                    walk_keys(e, prefix, seen)
            for k in seen:
                acc[k] = acc.get(k, 0) + 1
        elif prefix:
            acc[prefix] = acc.get(prefix, 0) + 1
        return
    if isinstance(node, dict):
        for k, v in node.items():
            walk_keys(v, prefix + (str(k),), acc)
        return
    if prefix:
        acc[prefix] = acc.get(prefix, 0) + 1


def values_at(node, segs: list, i: int = 0) -> list:
    """All leaf values under a path; lists at any depth flatten (the JS
    ``valuesAt``)."""
    if isinstance(node, list):
        out = []
        for e in node:
            out.extend(values_at(e, segs, i))
        return out
    if i == len(segs):
        return [node] if node is not None and not isinstance(node, (dict, list)) else []
    if isinstance(node, dict) and segs[i] in node:
        return values_at(node[segs[i]], segs, i + 1)
    return []


def test_sources(instance: str, part_type_id: str) -> list[dict]:
    """Test types with mirrored records for this type: ``[{id, name, n}]``."""
    rows = (HwdbTestData.for_instance(instance).filter(part_type_id=part_type_id)
            .values("test_type_id", "test_type_name").annotate(n=Count("id"))
            .order_by("test_type_name"))
    return [{"id": r["test_type_id"], "name": r["test_type_name"], "n": r["n"]} for r in rows]


def _records(instance, part_type_id, test_type_id):
    return HwdbTestData.for_instance(instance).filter(
        part_type_id=part_type_id, test_type_id=test_type_id)


def test_keys(instance: str, part_type_id: str, test_type_id: int) -> dict:
    """``{"keys": [{"path": [...], "n": items-with-key}], "n_items": N}`` for
    one test type, walked over every mirrored record and cached until the
    next sync touches the type."""
    qs = _records(instance, part_type_id, test_type_id)
    stamp = qs.aggregate(m=Max("synced_at"))["m"]
    ck = f"plot-keys:{instance}:{part_type_id}:{test_type_id}:{stamp.isoformat() if stamp else 0}"
    hit = cache.get(ck)
    if hit is not None:
        return hit
    acc: dict = {}
    n = 0
    for blob in qs.values_list("test_data", flat=True):
        n += 1
        walk_keys(blob, (), acc)
    keys = sorted(acc.items(), key=lambda kv: (-kv[1], kv[0]))
    out = {"keys": [{"path": list(k), "n": v} for k, v in keys], "n_items": n}
    cache.set(ck, out, 3600)
    return out


def test_items(instance: str, part_type_id: str, test_type_id: int) -> list[dict]:
    """One row per item holding this test type — the Plot page's item list:
    pid + the component facets (from the component mirror) + the record's
    HWDB created date."""
    recs = list(_records(instance, part_type_id, test_type_id)
                .values_list("part_id", "created"))
    comps = {c.part_id: c for c in HwdbComponentEvent.for_instance(instance)
             .filter(part_type_id=part_type_id, part_id__in=[p for p, _ in recs])}
    out = []
    for pid, created in sorted(recs):
        c = comps.get(pid)
        out.append({
            "pid": pid,
            "serial": c.serial_number if c else "",
            "status": c.status if c else "",
            "creator": c.created_by if c else "",
            "manufacturer": c.manufacturer if c else "",
            "institution": c.institution if c else "",
            "created": c.created.date().isoformat() if c and c.created else "",
            "updated": c.updated.date().isoformat() if c and c.updated else "",
            "tested": created.date().isoformat() if created else "",
        })
    return out


def test_values(instance: str, part_type_id: str, test_type_id: int, path: list) -> dict:
    """``{pid: [leaf values]}`` for one key across every mirrored record
    (items without the key are omitted)."""
    out = {}
    for pid, blob in _records(instance, part_type_id, test_type_id).values_list("part_id", "test_data"):
        vals = values_at(blob, path)
        if vals:
            out[pid] = vals
    return out
