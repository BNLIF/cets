"""Generic per-part detail engine (ADR-0014).

``part_detail(api, part_id, is_shipping)`` assembles everything the explorer
shows about a single part — item facts, a latest-per-type test summary,
subcomponents, specifications, attachments, and a location timeline — live from
HWDB. Read-only; nothing is mirrored (FNAL-gated at the view).

A shipping box is just a part whose type is curated as a shipping type: the
view passes ``is_shipping=True`` so the spec blob renders as the fixed
Pre-shipping / Shipping / Info @ Warehouse lifecycle (``shipment_details``)
instead of the generic per-key sections.
"""

from __future__ import annotations

import logging

from .shipments import (
    _is_image, _spec_data, current_manifest, fold_entries, shipment_details,
)

logger = logging.getLogger(__name__)


def _safe_data(label, fn) -> list:
    """``fn()['data']`` or ``[]`` — a single failing aux endpoint (e.g. a part
    with no /locations or /tests) degrades its section, not the whole page."""
    try:
        return fn().get("data") or []
    except Exception as e:
        logger.warning("part detail: %s fetch failed: %s", label, e)
        return []


def spec_sections(data_blob: dict | None) -> list[dict]:
    """Render an item's ``specifications[0].DATA`` blob into generic cards.

    Each top-level key becomes a card (a list/dict value folds into key/value
    fields + downloadable ``Image ID`` attachments); loose scalar keys collect
    into one leading "Specifications" card. The shipping checklists are just the
    special case of this where the keys are the three lifecycle stages (#0014).
    """
    if isinstance(data_blob, list):  # some specs are a bare list of entries
        fields, attachments = fold_entries(data_blob)
        return [{"title": "Specifications", "fields": fields,
                 "attachments": attachments}] if (fields or attachments) else []
    if not isinstance(data_blob, dict):
        return []
    out, flat = [], []
    for key, val in data_blob.items():
        if isinstance(val, list):
            fields, attachments = fold_entries(val)
        elif isinstance(val, dict):
            fields, attachments = fold_entries([val])
        elif val not in (None, "", [], {}):
            flat.append({"label": key, "value": str(val)})
            continue
        else:
            continue
        if fields or attachments:
            out.append({"title": key, "fields": fields, "attachments": attachments})
    if flat:
        out.insert(0, {"title": "Specifications", "fields": flat, "attachments": []})
    return out


def test_summary(tests: list[dict] | None) -> list[dict]:
    """Latest test record per test type: ``test_type``, ``status``, ``created``,
    ``comments`` — newest by ``created`` wins. Full payloads stay in HWDB
    (ADR-0014). Field names read defensively across HWDB shapes."""
    by_type: dict[str, dict] = {}
    for t in tests or []:
        if not isinstance(t, dict):
            continue
        # test_type may be a nested {id, name} ref or a plain string.
        name = (_named(t.get("test_type")) or _named(t.get("test_type_name"))
                or _named(t.get("name")) or "Test")
        name = str(name)
        created = t.get("created") or ""
        cur = by_type.get(name)
        if cur is None or created > (cur.get("created") or ""):
            by_type[name] = t
    return sorted(
        ({"test_type": name,
          "status": _named(t.get("status")),
          "created": t.get("created"),
          "comments": t.get("comments"),
          # oid → FNAL files view; test_type_id → our test_data JSON download.
          # has_data / has_test_data are backfilled by _enrich_test_ids.
          "test_id": t.get("id"), "test_type_id": None,
          "has_data": False, "has_test_data": False}
         for name, t in by_type.items()),
        key=lambda r: r["test_type"],
    )


def _named(v):
    """A nested ``{name: …}`` ref or a plain string → its display name."""
    return v.get("name") if isinstance(v, dict) else v


# Above this many direct children we skip the per-child status fetch so the page
# render stays fast; the children still list, just without a status until
# expanded (ADR-0015).
_STATUS_FETCH_CAP = 40


def assembly_children(api, parent_pid: str) -> list[dict]:
    """One level of the assembly tree: a part's current subcomponents, each with
    its live QC ``status`` (ADR-0015).

    The manifest (``/subcomponents``) gives id / type / position; the per-child
    component record adds ``status``. The fetch is best-effort and capped
    (``_STATUS_FETCH_CAP``) — a child whose record fails or is skipped just
    renders with no status (``None``)."""
    kids = current_manifest(_safe_data("subcomponents", lambda: api.get_subcomponents(parent_pid)))
    for i, k in enumerate(kids):
        status = None
        if k.get("part_id") and i < _STATUS_FETCH_CAP:
            try:
                status = _named((api.get_component(k["part_id"]).get("data") or {}).get("status"))
            except Exception as e:
                logger.warning("assembly: status for %s failed: %s", k["part_id"], e)
        k["status"] = status
    return kids


def _yesno(v):
    """Boolean flag → Yes/No; None (field absent) stays None so the fact is
    skipped rather than shown as a false No."""
    return None if v is None else ("Yes" if v else "No")


def part_facts(comp: dict) -> list[dict]:
    """Ordered (label, value) item facts, skipping blanks. Defensive about the
    nested-ref vs scalar shapes HWDB uses for institution/manufacturer."""
    ct = comp.get("component_type") or {}
    candidates = [
        ("Serial number", comp.get("serial_number")),
        ("Type", _named(ct) or comp.get("type_name")),
        ("Status", _named(comp.get("status"))),
        # Binary QC flags off the same record (#51).
        ("Installed", _yesno(comp.get("is_installed"))),
        ("QA/QC Uploaded", _yesno(comp.get("qaqc_uploaded"))),
        ("Certified QA/QC", _yesno(comp.get("certified_qaqc"))),
        ("Institution", _named(comp.get("institution"))),
        ("Manufacturer", _named(comp.get("manufacturer"))),
        ("Country", comp.get("country_code")),
        ("Created", (comp.get("created") or "")[:10] or None),
        ("Created by", _named(comp.get("creator"))),
        ("Comments", comp.get("comments")),
    ]
    return [{"label": k, "value": str(v)} for k, v in candidates if v not in (None, "", [])]


_TEST_IMAGE_KEYS = ("images", "test_images", "image_list", "images_list", "attachments")


def _test_has_images(rec: dict) -> bool:
    """Whether a per-type test record embeds any data files (CSV, plots)."""
    return any(isinstance(rec.get(k), list) and rec.get(k) for k in _TEST_IMAGE_KEYS)


def _enrich_test_ids(api, part_id: str, tests: list[dict]) -> None:
    """Fill each summarized test's ``test_id`` (component-test oid), real
    ``status`` and ``has_data`` from the per-type endpoint.

    The list endpoint (``components/{pid}/tests``) omits the oid, status and
    embedded files; the per-type endpoint (``…/tests/{test_type_id}``) carries
    all three. Bounded to the test types that actually have results, so a part
    with two test types costs two extra calls. Best-effort — a failure just
    leaves the FNAL data link off.
    """
    if not tests:
        return
    ptid = part_id.rsplit("-", 1)[0]
    type_ids = {tt.get("name"): tt.get("id")
                for tt in _safe_data("test types", lambda: api.get_test_types(ptid))
                if tt.get("name") and tt.get("id") is not None}
    for t in tests:
        ttid = type_ids.get(t["test_type"])
        if ttid is None:
            continue
        t["test_type_id"] = ttid
        recs = _safe_data(
            f"test {t['test_type']}",
            lambda ttid=ttid: api.get_tests(part_id, test_type_id=ttid, history=True),
        )
        latest = max(recs, key=lambda r: r.get("created") or "", default=None)
        if latest:
            t["test_id"] = latest.get("id")
            t["status"] = _named(latest.get("status")) or t["status"]
            t["has_data"] = _test_has_images(latest)
            t["has_test_data"] = bool(latest.get("test_data"))


def part_detail(api, part_id: str, is_shipping: bool) -> dict:
    """Live detail bundle for one part. ``sections`` are the spec cards (the
    shipping lifecycle when ``is_shipping``); attachments are enriched with the
    real filename + an image flag for thumbnailing."""
    comp_body = api.get_component(part_id)  # core record — a failure here 502s
    comp = comp_body.get("data") or {}
    data_blob = _spec_data(comp_body)

    locs = _safe_data("locations", lambda: api.get_locations(part_id))
    timeline = sorted(
        ({"arrived": e.get("arrived"),
          "location": (e.get("location") or {}).get("name"),
          "location_id": (e.get("location") or {}).get("id"),
          "creator": e.get("creator"),
          "comments": e.get("comments")}
         for e in locs),
        key=lambda e: e["arrived"] or "", reverse=True,
    )
    manifest = assembly_children(api, part_id)  # direct children + their QC flags
    tests = test_summary(_safe_data("tests", lambda: api.get_tests(part_id)))
    _enrich_test_ids(api, part_id, tests)

    images = [i for i in _safe_data("images", lambda: api.get_images(part_id)) if i.get("image_id")]
    name_by_id = {str(i["image_id"]): i.get("image_name") for i in images}
    sections = shipment_details(data_blob) if is_shipping else spec_sections(data_blob)
    for sec in sections:
        for a in sec["attachments"]:
            a["filename"] = name_by_id.get(a["image_id"]) or a["label"]
            a["is_image"] = _is_image(a["filename"])
    attachments = [{"image_id": str(i["image_id"]), "image_name": i.get("image_name"),
                    "is_image": _is_image(i.get("image_name"))}
                   for i in images]

    ct = comp.get("component_type") or {}
    return {
        "part_id": part_id,
        "type_name": _named(ct) or comp.get("type_name"),
        "status": _named(comp.get("status")),
        "facts": part_facts(comp),
        "tests": tests,
        "manifest": manifest,
        "timeline": timeline,
        "sections": sections,
        "attachments": attachments,
        "has_location": bool(timeline),
        "in_transit": bool(timeline and timeline[0]["location_id"] == 0),
    }
