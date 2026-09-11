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

from . import parts
from .events import _parse_created, _ref_name

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
