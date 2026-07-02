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
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from threading import local as _thread_local_cls
from typing import Iterator

from django.utils import timezone

from hwdb.api_client import FnalDbApiClient

from .models import HierarchyNode, ShipmentItem

logger = logging.getLogger(__name__)

_WORKERS = 20


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


def current_manifest(subs: list[dict] | None) -> list[dict]:
    """A box's current contents from its raw ``/subcomponents`` rows: those whose
    latest state is mounted (``operation`` of ``unmount`` excluded), each as
    part id / component-type name / functional position."""
    return [
        {"part_id": s.get("part_id"),
         "type_name": s.get("type_name"),
         "functional_position": s.get("functional_position")}
        for s in (subs or []) if s.get("operation") != "unmount"
    ]


# The FD shipping workflow writes these checklists into the box item's
# free-form spec DATA blob (see the Python dashboard). Each is (HWDB key,
# display title); we render all three as a fixed lifecycle, even when empty.
_DETAIL_SECTIONS = (
    ("Pre-Shipping Checklist", "Pre-shipping"),
    ("Shipping Checklist", "Shipping"),
    ("Warehouse", "Info @ Warehouse"),
)


def _spec_data(component_body: dict | None) -> dict | None:
    """The ``specifications[0].DATA`` blob off a full item record, or None."""
    specs = ((component_body or {}).get("data") or {}).get("specifications") or []
    return (specs[0] or {}).get("DATA") if specs else None


_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")


def _is_image(name: str | None) -> bool:
    """Whether an attachment filename is a browser-previewable raster image
    (so we can thumbnail it; PDFs/others get a download chip instead)."""
    return bool(name) and name.lower().endswith(_IMAGE_EXTS)


def _image_label(key: str) -> str:
    """A clean button label from an ``Image ID for the/this X`` key."""
    label = key.split("Image ID for", 1)[-1].strip()
    for pre in ("this ", "the "):
        if label.lower().startswith(pre):
            label = label[len(pre):]
    return label or key


def shipment_details(data_blob: dict | None) -> list[dict]:
    """Parse the box's spec DATA into the three lifecycle detail sections.

    The FD shipping workflow stores pre-shipping / shipping / warehouse
    checklists in ``specifications[0].DATA``; each is a *list of single-field
    entries*. We fold all entries of one checklist into **one** section of
    ordered key/value ``fields``, peeling any ``Image ID for …`` key into a
    downloadable ``attachment`` (bill of lading, proforma invoice, approval
    message, label). Field names are taken verbatim from HWDB — no hardcoded
    schema. All three sections are **always** returned in lifecycle order (a
    stage not yet reached has empty ``fields``/``attachments``), so the page
    can show the whole timeline (ADR-0013).
    """
    out = []
    for key, title in _DETAIL_SECTIONS:
        entries = (data_blob or {}).get(key)
        fields, attachments = fold_entries(entries if isinstance(entries, list) else [])
        out.append({"title": title, "fields": fields, "attachments": attachments})
    return out


def fold_entries(entries: list) -> tuple[list, list]:
    """Fold a list of single-/multi-field dict entries into ordered key/value
    ``fields`` plus downloadable ``attachments`` (any ``Image ID for …`` key).
    Shared by the shipping checklists and the generic spec renderer (#0014)."""
    fields, attachments = [], []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        for k, v in entry.items():
            if v in (None, "", [], {}):
                continue
            if "Image ID" in k:
                attachments.append({"label": _image_label(k), "image_id": str(v)})
            else:
                fields.append({"label": k, "value": str(v)})
    return fields, attachments


def _list_boxes(api, part_type_id: str) -> list[str]:
    """Every box's part_id across all pages (the listing paginates — the #46
    run showed 100 of 326)."""
    out, page = [], 1
    while True:
        body = api._make_request(
            "GET", f"component-types/{part_type_id}/components",
            params={"page": page, "size": 500},
        )
        rows = body.get("data") or []
        for r in rows:
            pid = r.get("part_id") or r.get("pid")
            if pid:
                out.append(pid)
        pages = (body.get("pagination") or {}).get("pages", 1)
        if page >= pages or not rows:
            return out
        page += 1


def sync_shipments(api_base_url: str, bearer: str, part_type_id: str,
                   instance: str = "prod", mode: str = "full") -> Iterator[str]:
    """Mirror boxes of one shipping type. Generator yielding progress.

    For each box (in parallel) reads its latest location + current contents.
    Empty boxes (0 contents) are mirrored too (``n_contents=0`` — the leaf
    page lists them in a separate pane). ``HwdbComponentEvent`` is NOT
    touched — boxes are regular components, so the node (test) sync owns
    those rows and the standard charts/breakdown render from them.

    Two modes (cost-tiered like the events sync):
    - ``full`` (default): re-fetch every box and rewrite the type wholesale —
      picks up location changes on known boxes.
    - ``incremental``: fetch only boxes not yet mirrored (1 listing + N-new
      fetches); known rows keep their mirrored location, vanished boxes are
      pruned. The cheap "Sync new" sweep.
    """
    bootstrap = FnalDbApiClient(api_base_url, bearer)

    yield f"sync shipments ({mode}): listing boxes for {part_type_id}\n"
    boxes = _list_boxes(bootstrap, part_type_id)
    known = set(ShipmentItem.for_instance(instance)
                .filter(part_type_id=part_type_id).values_list("part_id", flat=True))
    fetch = [p for p in boxes if p not in known] if mode == "incremental" else boxes
    yield (
        f"sync shipments ({mode}): {len(boxes)} box(es) in HWDB · "
        f"fetching {len(fetch)} (locations + contents)…\n"
    )

    tls = _thread_local_cls()

    def _init():
        tls.client = FnalDbApiClient(api_base_url, bearer)

    def _fetch(pid):
        locs = tls.client.get_locations(pid).get("data") or []
        manifest = current_manifest(tls.client.get_subcomponents(pid).get("data"))
        return pid, locs, manifest

    results, done = [], 0
    if fetch:
        with ThreadPoolExecutor(max_workers=_WORKERS, initializer=_init) as pool:
            futs = {pool.submit(_fetch, pid): pid for pid in fetch}
            for fut in as_completed(futs):
                try:
                    results.append(fut.result())
                except Exception as e:
                    logger.warning("sync shipments: %s failed: %s", futs[fut], e)
                done += 1
                if done % 50 == 0 or done == len(fetch):
                    yield f"  fetched {done}/{len(fetch)}\n"

    ship_rows = []
    for pid, locs, manifest in results:
        latest = latest_location(locs)
        loc = (latest or {}).get("location") or {}
        shipped, received = shipped_received(locs)
        ship_rows.append(ShipmentItem(
            instance=instance, part_type_id=part_type_id, part_id=pid,
            location_name=loc.get("name") or "", location_id=loc.get("id"),
            n_contents=len(manifest),
            last_arrived=_parse_dt((latest or {}).get("arrived")),
            shipped_date=shipped, received_date=received,
        ))

    if mode == "incremental":
        # Keep known rows; drop boxes that vanished from HWDB, and any stale
        # duplicates of the ones just fetched (retry safety).
        (ShipmentItem.for_instance(instance).filter(part_type_id=part_type_id)
         .exclude(part_id__in=boxes).delete())
        (ShipmentItem.for_instance(instance).filter(
            part_type_id=part_type_id, part_id__in=[r.part_id for r in ship_rows])
         .delete())
    else:
        ShipmentItem.for_instance(instance).filter(part_type_id=part_type_id).delete()
    if ship_rows:
        ShipmentItem.objects.bulk_create(ship_rows, batch_size=1000)

    # Mark the leaf synced even when 0 boxes — so the page stops
    # auto-syncing (NULL would read as "never synced" and re-trigger forever).
    HierarchyNode.for_instance(instance).filter(
        level=HierarchyNode.LEVEL_TYPE, part_type_id=part_type_id
    ).update(shipments_synced_at=timezone.now())

    mirrored = ShipmentItem.for_instance(instance).filter(part_type_id=part_type_id)
    n_full = mirrored.filter(n_contents__gt=0).count()
    in_transit = mirrored.filter(n_contents__gt=0, location_id=0).count()
    kept = f" · {len(boxes) - len(fetch)} known kept" if mode == "incremental" else ""
    yield (
        f"done ({mode}): {len(ship_rows)} box(es) fetched{kept} · "
        f"{mirrored.count()} mirrored ({n_full} with contents) · {in_transit} in transit\n"
    )
