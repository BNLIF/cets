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

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from hwdb.api_client import FnalDbApiClient

from .shipments import (
    _is_image, _is_pdf, _spec_block, current_manifest, fold_entries,
    shipment_details, spec_field,
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


def spec_sections(spec_block: dict | None) -> list[dict]:
    """Render an item's latest ``specifications`` entry into generic cards.

    Each top-level key becomes a card (a list/dict value folds into key/value
    fields + downloadable ``Image ID`` attachments); loose scalar keys collect
    into one leading "Specifications" card. The free-form ``DATA`` sub-dict
    (where checklists write, nested ``{section: {label: value}}``) is ONE
    "DATA" card, its rows labelled ``section › label`` — the hierarchy the
    FNAL web UI shows (#98 review, amending ADR-0014's in-place expansion);
    ``_meta`` is HWDB bookkeeping and stays hidden. Shipping types render
    their DATA through ``shipment_details`` instead.
    """
    if isinstance(spec_block, list):  # some specs are a bare list of entries
        fields, attachments = fold_entries(spec_block)
        return [{"title": "Specifications", "fields": fields,
                 "attachments": attachments,
                 "json": json.dumps(spec_block, indent=2, ensure_ascii=False)}
                ] if (fields or attachments) else []
    if not isinstance(spec_block, dict):
        return []
    items = []
    for key, val in spec_block.items():
        if key == "_meta":
            continue
        if key == "DATA" and isinstance(val, dict):
            # rows remember where they came from so the part page can offer
            # architects a per-row delete (#102)
            fields, attachments = [], []
            for k, v in val.items():
                rows = v.items() if isinstance(v, dict) else [(k, v)]
                for kk, vv in rows:
                    f, a = fold_entries([{(f"{k} › {kk}" if isinstance(v, dict) else k): vv}])
                    for row in f:
                        row["spec_del"] = {"section": k if isinstance(v, dict) else "", "label": kk}
                    fields += f
                    attachments += a
            if fields or attachments:
                out_data = {"title": "DATA", "fields": fields, "attachments": attachments,
                            "json": json.dumps(val, indent=2, ensure_ascii=False)}
                items.append(("DATA", out_data))
        elif key == "DATA":  # bare-list DATA blobs keep their old card title
            items.append(("Specifications", val))
        else:
            items.append((key, val))
    out, flat, flat_raw = [], [], {}
    for key, val in items:
        if key == "DATA" and isinstance(val, dict) and "fields" in val:
            out.append(val)          # the pre-built DATA card
            continue
        if isinstance(val, list) and any(isinstance(e, dict) for e in val):
            fields, attachments = fold_entries(val)
        elif isinstance(val, dict):
            fields, attachments = fold_entries([val])
        elif val not in (None, "", [], {}):
            # Scalars AND bare arrays (e.g. a pasted list of numbers) — the
            # latter get the click-to-view treatment via spec_field.
            flat.append(spec_field(key, val))
            flat_raw[key] = val
            continue
        else:
            continue
        if fields or attachments:
            # "json" feeds the card's copy-to-clipboard button.
            out.append({"title": key, "fields": fields, "attachments": attachments,
                        "json": json.dumps(val, indent=2, ensure_ascii=False)})
    if flat:
        out.insert(0, {"title": "Specifications", "fields": flat, "attachments": [],
                       "json": json.dumps(flat_raw, indent=2, ensure_ascii=False)})
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


# HWDB's pre-vocabulary-change statuses (ids 1-3) are all obsolete: the
# current vocabulary is Unknown (0) plus the 100+ values, with Unknown the
# initial default (Shipping Procedure Appendix B, #75) — yet the REST API
# still serves the old ids on parts whose status predates the change (boxes
# minted 2026-07 carry id 1 "Available"). By bare name (the mirror stores
# names only) the mapping covers the unambiguous legacy names;
# "Permanently Unavailable" doubles as modern id 170, so it passes through
# and the id-aware sync corrects obsolete rows on their next walk.
OBSOLETE_STATUS_IDS = {1, 2, 3}
_OBSOLETE_STATUS_NAMES = {"Available", "Temporarily Unavailable"}
# What the Shipping Procedure (July 2026, Appendix B) ALLOWS to be linked:
# In Fabrication / Waiting on QA/QC Tests / Passed All / Use As Is. The
# REST API accepts ANY status (2026-07-29 full-matrix probe — its only
# refusal is the per-item "not yet available" enable gate; an HWDB fix is
# requested), so the pack picker enforces the rule itself: every candidate
# is listed, but only these four are selectable (#84).
PROCEDURE_LINKABLE_STATUS_IDS = {100, 110, 120, 140}


def normalize_status(value):
    """Raw HWDB status ({id, name} ref, bare name, or None) → display name,
    with the obsolete ids 1-3 shown as Unknown."""
    if isinstance(value, dict):
        return "Unknown" if value.get("id") in OBSOLETE_STATUS_IDS else value.get("name")
    return "Unknown" if value in _OBSOLETE_STATUS_NAMES else value


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
                status = normalize_status(
                    (api.get_component(k["part_id"]).get("data") or {}).get("status"))
            except Exception as e:
                logger.warning("assembly: status for %s failed: %s", k["part_id"], e)
        k["status"] = status
    return kids


# Bound for the executive summary's contents list — one HTTP call per child;
# past this the listing stops and the cut is reported, not silent.
_SUBTREE_NODE_CAP = 300


def _manifest_children(api, pid: str, depth: int, seen: set) -> list[dict]:
    """One node's unvisited mounted children as subtree rows-in-waiting.

    Peer back-references are skipped (#72): a cable's manifest lists what its
    ends plug into — its flange/board/tray peers, including its own parent —
    which is connectivity, not contents. Keeping them would fold a cable's
    whole neighborhood into the subtree. Forward cable-end mounts
    (``END:connector``) stay: the cable is genuinely attached; recursing into
    it then yields only peer rows, so the walk terminates there."""
    kids = []
    for m in current_manifest(_safe_data("subcomponents", lambda: api.get_subcomponents(pid))):
        cid = m.get("part_id")
        if not cid or cid in seen or m.get("peer"):
            continue
        seen.add(cid)
        kids.append({**m, "depth": depth})
    return kids


_FETCH_WORKERS = 8


def _thread_client(api):
    """A fresh client for a worker thread — one keep-alive Session per
    thread, since a shared Session must not fan out across threads (see
    FnalDbApiClient). Test doubles pass through as-is."""
    if isinstance(api, FnalDbApiClient):
        bearer = (api.session.headers.get("Authorization") or "")
        return FnalDbApiClient(api.base_url, bearer.removeprefix("Bearer "))
    return api


def fetch_map(api, fn, keys, *, workers: int = _FETCH_WORKERS) -> dict:
    """``{key: fn(client, key)}`` for the unique ``keys`` across a small
    worker pool (one client per thread); a failed key maps to ``None``.
    For fanning the per-child HWDB reads of a user-facing page out — the
    latency of N sequential round-trips is what made the ES sub-components
    pane crawl (Hajime, 2026-07-30)."""
    out = {}
    uniq = list(dict.fromkeys(keys))
    if not uniq:
        return out
    local = threading.local()

    def _run(key):
        cli = getattr(local, "client", None)
        if cli is None:
            cli = local.client = _thread_client(api)
        return fn(cli, key)

    with ThreadPoolExecutor(max_workers=min(workers, len(uniq))) as pool:
        futs = {pool.submit(_run, k): k for k in uniq}
        for fut in as_completed(futs):
            key = futs[fut]
            try:
                out[key] = fut.result()
            except Exception as e:
                logger.warning("parallel fetch for %s failed: %s", key, e)
                out[key] = None
    return out


def subtree_rows(api, root_pid: str, *, max_nodes: int = _SUBTREE_NODE_CAP
                 ) -> tuple[list[dict], bool]:
    """The DIRECT sub-components of ``root_pid``, each with the three QC
    statuses — ``status`` name, ``uploaded``, ``certified`` (``None`` =
    record fetch failed). Originally the full recursive tree (Hajime's ES
    review); limited to one level on his 2026-07-30 call — a CRU's nested
    tree runs deep and slow, and "if we hear complaints, we would consider
    other ways". The root itself is excluded — its statuses already headline
    the executive summary. Per-child records are fetched in parallel
    (``fetch_map``). Returns ``(rows, truncated)``."""
    seen = {root_pid}
    kids = _manifest_children(api, root_pid, 0, seen)
    truncated = len(kids) > max_nodes
    if truncated:
        logger.warning("subtree for %s truncated at %d nodes", root_pid, max_nodes)
    kids = kids[:max_nodes]
    comps = fetch_map(api, lambda cli, pid: cli.get_component(pid).get("data") or {},
                      [row["part_id"] for row in kids])
    rows: list[dict] = []
    for row in kids:
        comp = comps.get(row["part_id"])   # None = record fetch failed
        row.update(
            status=normalize_status(comp.get("status")) if comp is not None else None,
            uploaded=comp.get("qaqc_uploaded") if comp is not None else None,
            certified=comp.get("certified_qaqc") if comp is not None else None,
            # HWDB's internal numeric id — the web UI's images page is
            # addressed by it, not by the part id
            component_id=comp.get("component_id") if comp is not None else None)
        rows.append(row)
    return rows, truncated


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
        ("Category", comp.get("category")),  # "cable" / "generic" / … (#72)
        ("Status", normalize_status(comp.get("status"))),
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


def _annotate_cable_connections(api, part_id: str, manifest: list[dict]) -> list[str]:
    """Recover which of this cable's connectors each connection uses (#72).

    A cable's reverse rows only carry the *peer's* position name — the
    ``END:connector`` on the cable side is recorded on the peer's manifest
    (``<cable PID>.<END>:<n>``). One ``/subcomponents`` call per distinct
    peer (capped, best-effort) fills each peer row's ``via`` and returns the
    sorted occupied slots for the diagram. An only-PID connection (no
    ENDs/connectors, e.g. a cable tray) keeps ``via`` None and occupies
    nothing."""
    peers = [m for m in manifest if m.get("peer") and m.get("part_id")]
    via: dict[tuple, str] = {}
    used: set[str] = set()
    for pid in sorted({m["part_id"] for m in peers})[:_STATUS_FETCH_CAP]:
        rows = current_manifest(_safe_data(
            f"peer {pid} manifest", lambda pid=pid: api.get_subcomponents(pid)))
        for row in rows:
            if row.get("part_id") == part_id and row.get("connection") and not row.get("peer"):
                used.add(row["connection"])
                via[(pid, row.get("functional_position"))] = row["connection"]
    for m in peers:
        m["via"] = via.get((m["part_id"], m.get("functional_position")))
    return sorted(used)


def cable_ends(connectors: dict | None) -> list[dict]:
    """A cable type's ENDs from its ``connectors`` keys (#72): HWDB stores the
    definition expanded into one ``<END name>:<connector #>`` slot per
    connector (``Flange:1`` … ``Flange:8``), so grouping on the name yields
    the shape Hajime defines in the type editor — ``[{"name": "Flange",
    "connectors": 8}, …]`` in key order. A key without a trailing ``:n``
    counts as a one-connector end of that name."""
    ends: dict[str, int] = {}
    for key in connectors or {}:
        name, _, conn = str(key).rpartition(":")
        if not (name and conn.isdigit()):
            name = str(key)
        ends[name] = ends.get(name, 0) + 1
    return [{"name": n, "connectors": c} for n, c in ends.items()]


def current_container(rows) -> dict | None:
    """The item's current parent from its ``/container`` rows (the reverse of
    the manifest, same mount/unmount row shape): the newest entry that isn't
    an unmount, or None. Defensive — the endpoint is undocumented in the
    official client, so unexpected shapes just mean "no parent shown"."""
    if not isinstance(rows, list):
        return None
    live = [r for r in rows
            if isinstance(r, dict) and r.get("operation") != "unmount"
            and (r.get("container") or {}).get("part_id")]
    if not live:
        return None
    top = max(live, key=lambda r: r.get("created") or "")
    c = top["container"]
    return {"part_id": c.get("part_id"),
            "type_name": _named(c.get("component_type")),
            "functional_position": top.get("functional_position")}


def part_detail(api, part_id: str, is_shipping: bool) -> dict:
    """Live detail bundle for one part. ``sections`` are the spec cards (the
    shipping lifecycle when ``is_shipping``); attachments are enriched with the
    real filename + an image flag for thumbnailing."""
    comp_body = api.get_component(part_id)  # core record — a failure here 502s
    comp = comp_body.get("data") or {}
    spec_block = _spec_block(comp_body)
    data_blob = (spec_block or {}).get("DATA")

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
    sections = shipment_details(data_blob) if is_shipping else spec_sections(spec_block)
    for sec in sections:
        for a in sec["attachments"]:
            a["filename"] = name_by_id.get(a["image_id"]) or a["label"]
            a["is_image"] = _is_image(a["filename"])
            a["is_pdf"] = _is_pdf(a["filename"])
    attachments = [{"image_id": str(i["image_id"]), "image_name": i.get("image_name"),
                    "created": i.get("created"),
                    "is_image": _is_image(i.get("image_name")),
                    "is_pdf": _is_pdf(i.get("image_name"))}
                   for i in images]

    # The item record's category tells a cable from a generic part (#72); a
    # cable's page draws its ENDs/connectors from the type definition, with
    # this item's occupied connectors recovered from its peers' manifests.
    is_cable = comp.get("category") == "cable"
    ends, used = [], []
    if is_cable:
        try:
            ends = cable_ends(
                (api.get_component_type(part_id.rsplit("-", 1)[0]).get("data") or {})
                .get("connectors"))
        except Exception as e:
            logger.warning("part detail: cable ends for %s failed: %s", part_id, e)
        used = _annotate_cable_connections(api, part_id, manifest)

    container = current_container(
        _safe_data("container", lambda: api.get_container(part_id)))
    # A cable's /container rows include its connections' back-references, so
    # the "newest" one is a single arbitrary connector out of many — not a
    # parent. Peers already render in the Connections pane; only a genuine
    # container (e.g. a shipping box, never a peer) shows as "Inside" (#72).
    if is_cable and container and any(
            m.get("peer") and m.get("part_id") == container["part_id"]
            for m in manifest):
        container = None

    ct = comp.get("component_type") or {}
    return {
        "part_id": part_id,
        "container": container,
        "type_name": _named(ct) or comp.get("type_name"),
        "is_cable": is_cable,
        "cable_ends": ends,
        "used_connectors": used,
        "status": normalize_status(comp.get("status")),
        "facts": part_facts(comp),
        # #104: the raw standard fields for the part page's edit form
        "raw": {k: comp.get(k) for k in ("status", "manufacturer", "is_installed",
                                         "qaqc_uploaded", "certified_qaqc",
                                         "serial_number", "comments", "location")},
        "tests": tests,
        "manifest": manifest,
        "timeline": timeline,
        "sections": sections,
        "attachments": attachments,
        "has_location": bool(timeline),
        "in_transit": bool(timeline and timeline[0]["location_id"] == 0),
    }
