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
        rows.append(ShipmentItem(
            part_type_id=part_type_id,
            part_id=pid,
            location_name=loc.get("name") or "",
            location_id=loc.get("id"),
            last_arrived=_parse_dt((latest or {}).get("arrived")),
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
