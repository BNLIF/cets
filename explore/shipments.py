"""Per-shipping-type location sync — pure engine, no views (ADR-0013, #43).

``sync_shipments(api_base_url, bearer, part_type_id)`` walks every item (box) of
a shipping-type component type, reads each box's **latest** location from HWDB
(`components/{pid}/locations`), and mirrors it into ``ShipmentItem``. Read-only
against HWDB; the local rows for the type are rewritten wholesale each run
(disposable cache). Yields plain-text progress lines for a
``StreamingHttpResponse`` to wrap — same shape as ``events.sync_test_events``.

Only the latest location is mirrored; the full timeline + manifest are fetched
live on expand (#44), not here.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterator

from hwdb.api_client import FnalDbApiClient

from .models import ShipmentItem

logger = logging.getLogger(__name__)


def _parse_dt(s) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def latest_location(locations: list[dict]) -> dict | None:
    """The most recent location event by ``arrived`` (events are returned
    newest-first, but we don't rely on order — #42)."""
    if not locations:
        return None
    return max(locations, key=lambda e: e.get("arrived") or "")


def shipped_received(locations: list[dict]) -> tuple[datetime | None, datetime | None]:
    """Derive (shipped, received) from a box's full location timeline (#45).

    shipped = the earliest time it entered transit (``location.id == 0``);
    received = the arrival time of the latest event *iff* that event is a real
    location (not in transit) — i.e. null while still moving. Guards against a
    received earlier than shipped (treated as no valid receipt yet).
    """
    events = [
        (_parse_dt(e.get("arrived")), (e.get("location") or {}).get("id"))
        for e in locations
    ]
    events = sorted((e for e in events if e[0] is not None), key=lambda e: e[0])
    if not events:
        return None, None
    shipped = next((dt for dt, lid in events if lid == 0), None)
    last_dt, last_lid = events[-1]
    received = last_dt if last_lid not in (0, None) else None
    if shipped and received and received < shipped:
        received = None
    return shipped, received


def box_detail(api, part_id: str) -> dict:
    """Live detail for one box: full location timeline + current manifest.

    Read live on expand (ADR-0013, #44) — not mirrored. ``timeline`` is newest
    first. ``manifest`` lists current contents: subcomponent rows whose latest
    state is mounted (``operation`` of ``unmount`` is excluded), each with its
    part id, component-type name, and functional position.
    """
    locs = api.get_locations(part_id).get("data") or []
    timeline = sorted(
        ({"arrived": e.get("arrived"),
          "location": (e.get("location") or {}).get("name"),
          "location_id": (e.get("location") or {}).get("id"),
          "creator": e.get("creator"),
          "comments": e.get("comments")}
         for e in locs),
        key=lambda e: e["arrived"] or "", reverse=True,
    )
    subs = api.get_subcomponents(part_id).get("data") or []
    manifest = [
        {"part_id": s.get("part_id"),
         "type_name": s.get("type_name"),
         "functional_position": s.get("functional_position")}
        for s in subs if s.get("operation") != "unmount"
    ]
    return {"part_id": part_id, "timeline": timeline, "manifest": manifest}


def sync_shipments(api_base_url: str, bearer: str, part_type_id: str) -> Iterator[str]:
    """Mirror the latest location of every box of one shipping type. Generator
    yielding progress lines; rewrites ``ShipmentItem`` rows for the type."""
    api = FnalDbApiClient(api_base_url, bearer)

    yield f"sync shipments: listing boxes for {part_type_id}\n"
    items = api.get_component_types(part_type_id).get("data") or []
    yield f"sync shipments: {len(items)} box(es)\n"

    rows = []
    for i, it in enumerate(items, 1):
        pid = it.get("part_id") or it.get("pid")
        if not pid:
            continue
        locs = api.get_locations(pid).get("data") or []
        latest = latest_location(locs)
        loc = (latest or {}).get("location") or {}
        shipped, received = shipped_received(locs)
        rows.append(ShipmentItem(
            part_type_id=part_type_id,
            part_id=pid,
            location_name=loc.get("name") or "",
            location_id=loc.get("id"),
            last_arrived=_parse_dt((latest or {}).get("arrived")),
            shipped_date=shipped,
            received_date=received,
        ))
        where = "In Transit" if loc.get("id") == 0 else (loc.get("name") or "no location")
        yield f"  [{i}/{len(items)}] {pid}: {where}\n"

    ShipmentItem.objects.filter(part_type_id=part_type_id).delete()
    if rows:
        ShipmentItem.objects.bulk_create(rows)

    in_transit = sum(1 for r in rows if r.location_id == 0)
    yield (
        f"done: {len(rows)} box(es) mirrored · {in_transit} in transit · "
        f"{len(rows) - in_transit} at a location\n"
    )
