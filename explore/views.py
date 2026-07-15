import io
import json
import logging
import re
from datetime import datetime, timedelta
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.core.paginator import Paginator
from django.db.models import F, Q
from django.http import (
    HttpResponse, HttpResponseForbidden, JsonResponse, StreamingHttpResponse,
)
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.queries import chart_config
from hwdb.api_client import FnalDbApiClient
from hwdb.fnal import flow
from hwdb.fnal import session as fnal_session
from hwdb.fnal.bearer import FnalLinkRequired, FnalUnavailable, mint_for

from . import charts, checklists, curation, execsummary, navigation, scanning
from .auth import fnal_login_required, provision_and_login
from .events import physics_date_field, sync_test_events
from .hierarchy import sync_hierarchy, sync_system
from .instances import instance_of, namespace_of
from .models import (
    BoxChecklist, HierarchyNode, HierarchySyncState, HwdbComponentEvent,
    PackScan, ShipmentItem,
)
from .queries import (
    component_breakdowns, component_qc_flags, component_type_progress,
    component_update_filters, component_update_progress,
)
from .parts import assembly_children, current_container, part_detail
from .shipments import _spec_data, current_manifest, refresh_box, sync_shipments

logger = logging.getLogger(__name__)
FNAL_UNAVAILABLE = "FNAL authentication service is unavailable. Please try again later."

# How long a started device flow stays valid before the user must reload.
DEVICE_FLOW_LIFETIME = timedelta(minutes=10)


def _safe_next(request, default):
    """Return the next= target (GET or POST) if it's a safe internal URL."""
    nxt = request.POST.get("next") or request.GET.get("next")
    if nxt and url_has_allowed_host_and_scheme(
        nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return nxt
    return default


def _rev(request, viewname, args=None):
    """``reverse()`` pinned to this request's instance namespace, so a dev-page
    view reverses explore URLs back onto /hw/dev/ (#47)."""
    return reverse(viewname, args=args, current_app=namespace_of(instance_of(request)))


@login_not_required
def login_view(request):
    """Sign in with FNAL — the explore site's only login (ADR-0011).

    Starts a device flow with the ``login_user`` intent set, so completion
    (in ``login_poll_view``) provisions + logs in a Django user keyed on the
    credkey. An already-authenticated visitor skips straight to ``next``.
    """
    next_url = _safe_next(request, _rev(request, "explore:home"))
    if request.user.is_authenticated:
        return redirect(next_url)
    try:
        start = flow.start()
    except Exception:
        logger.exception("FNAL device-flow start failed")
        return render(request, "hwdb/error.html", {"error_message": FNAL_UNAVAILABLE})

    fnal_session.set_flow(
        request, start.poll_body, timezone.now() + DEVICE_FLOW_LIFETIME, next_url,
        login_user=True,
    )
    return render(
        request,
        "explore/login.html",
        {
            "auth_url": start.auth_url,
            "user_code": start.user_code,
            "poll_url": _rev(request, "explore:login_poll"),
        },
    )


@login_not_required
def login_poll_view(request):
    """One poll tick for the explore login. On completion, store the link and
    provision + log in the Django user. Returns JSON: pending / ok (+next) / error.
    """
    state = fnal_session.get_flow(request)
    if not state:
        return JsonResponse(
            {"status": "error", "detail": "no login in progress; reload to start"},
            status=404,
        )
    if datetime.fromisoformat(state["expires_at"]) <= timezone.now():
        fnal_session.clear_flow(request)
        return JsonResponse(
            {"status": "error", "detail": "login timed out; reload to start again"},
            status=410,
        )

    try:
        result = flow.poll(state["poll_body"])
    except Exception:
        logger.exception("FNAL device-flow poll failed")
        return JsonResponse({"status": "error", "detail": FNAL_UNAVAILABLE}, status=502)

    if result.outcome in ("pending", "slow_down"):
        return JsonResponse({"status": "pending"})

    try:
        login_result = flow.complete(result.auth or {})
    except Exception:
        logger.exception("FNAL device-flow completion failed")
        return JsonResponse({"status": "error", "detail": FNAL_UNAVAILABLE}, status=502)

    fnal_session.store_link(request, login_result)
    if state.get("login_user"):
        provision_and_login(request, login_result)
    next_url = state.get("next") or _rev(request, "explore:home")
    fnal_session.clear_flow(request)
    return JsonResponse({"status": "ok", "next": next_url})


@login_not_required
@fnal_login_required
def explore_tree_view(request):
    """The hierarchy homepage (#tree): the whole curated Region → Family →
    System → Subsystem → type tree in one expandable view, built from
    ``curation.yaml`` + the ``HierarchyNode`` mirror. Leaf rows link to their
    explorer page. Mirror-only (no live HWDB); session-login gated."""
    inst = instance_of(request)
    legacy = request.GET.get("node")  # old /explore/?node=<ptid> deep links
    if legacy:
        dest = navigation.leaf_path_for(inst, legacy)
        if dest:
            return redirect(dest)
    return render(request, "explore/tree.html", {
        "active_nav": "hierarchy",
        "tree": navigation.curated_tree(inst),
        "sidebar": navigation.sidebar_tree(inst, {}),
        "sync_state": HierarchySyncState.get(inst),
    })


@login_not_required
@fnal_login_required
def explore_view(request, trail=None):
    """Drill-in navigator over the curated DUNE hardware tree (ADR-0012, #40).

    A URL trail resolves to a node; folders render a breadcrumb + a grid of
    child cards, a component-type leaf renders the detail panel + plots. Reads
    the local mirror (no live HWDB on render). The legacy ``?node=<ptid>`` link
    permanently redirects to the node's path URL.
    """
    inst = instance_of(request)
    legacy = request.GET.get("node")
    if legacy:
        dest = navigation.leaf_path_for(inst, legacy)
        if dest:
            return redirect(dest)

    view = navigation.resolve(inst, trail)  # raises Http404 on an unknown path

    charts = []
    leaf = view.get("leaf")
    is_shipping = bool(leaf and curation.is_shipping_type(inst, leaf.part_type_id))
    shipments = shipment_synced_at = shipment_summary = empty_boxes_page = None
    # New-box pane (issue #62) on write-enabled instances. The leaf page stays
    # mirror-only on render: the form's institution list lazy-loads via the
    # explore:institutions JSON endpoint when the pane is first opened.
    can_create_box = is_shipping and inst in settings.HWDB_WRITE_INSTANCES
    # ES config editor link (any leaf type, even ones without a config yet —
    # saving a config there is what marks a type as requiring an exec summary).
    can_edit_es = bool(leaf) and inst in settings.HWDB_WRITE_INSTANCES
    empty_pids = []
    if is_shipping:
        # Shipping extras — boxes are regular components too (charts/breakdown
        # below render like any other leaf); these panes add the box view.
        ptid = leaf.part_type_id
        rows = list(ShipmentItem.for_instance(inst).filter(part_type_id=ptid, n_contents__gt=0))
        # Empty boxes get their own paginated pane (they're mirrored too, but
        # kept out of the main table, summary cards and the Shipments tab).
        # Paged by ?bpage= — ?page= belongs to the components table.
        empty_boxes_page = Paginator(
            ShipmentItem.for_instance(inst).filter(part_type_id=ptid, n_contents=0),
            50).get_page(request.GET.get("bpage"))
        if can_create_box:
            # "Use an existing box" picker — newest empty boxes first.
            empty_pids = list(
                ShipmentItem.for_instance(inst)
                .filter(part_type_id=ptid, n_contents=0)
                .order_by("-part_id").values_list("part_id", flat=True)[:200])
        shipments = rows
        # Sync marker on the leaf — NOT inferred from rows, so a synced type with
        # 0 non-empty boxes reads as synced (no auto-sync loop).
        shipment_synced_at = leaf.shipments_synced_at
        in_transit = sum(1 for r in rows if r.location_id == 0)
        delivered = sum(1 for r in rows if r.location_id not in (0, None))
        shipment_summary = {
            "total": len(rows), "in_transit": in_transit, "delivered": delivered,
        }
    if leaf and leaf.tests_synced_at:
        ptid = leaf.part_type_id
        comp_chart = chart_config(
            slug=f"{ptid}_comp", name="Items updated", href="",
            ranges=component_update_progress(inst, ptid),
        )
        comp_chart["caption"] = (
            "By HWDB last-updated date (status change / QC upload bumps it), "
            "not the original mint date."
        )
        # Status / QC-flag overlay menu (#52) — mirror-only, precomputed so the
        # selector swaps series client-side without a reload.
        comp_chart["filters"] = component_update_filters(inst, ptid)
        phys = physics_date_field(inst, ptid)
        test_chart = chart_config(
            slug=f"{ptid}_test",
            name="Tests performed" if phys else "Tests recorded",
            href="", ranges=component_type_progress(inst, ptid),
        )
        test_chart["caption"] = (
            f"By physics test date (test_data “{phys}”), faceted by test type."
            if phys else
            "By HWDB record date (upload time, not physics test date), "
            "faceted by test type."
        )
        charts = [comp_chart, test_chart]

    # Paginated parts table for a synced non-shipping leaf — every component of
    # the type from the mirror (HwdbComponentEvent), each row opening its part
    # page. Mirror-backed like the box table, so no live HWDB on render.
    parts_page = None
    breakdowns, qc_flags = [], []
    if leaf and leaf.tests_synced_at:
        part_rows = (HwdbComponentEvent.for_instance(inst)
                     .filter(part_type_id=leaf.part_type_id)
                     .order_by(F("updated").desc(nulls_last=True),
                               F("created").desc(nulls_last=True), "part_id"))
        parts_page = Paginator(part_rows, 50).get_page(request.GET.get("page"))
        # Mirror-only categorical breakdowns (status / manufacturer / institution)
        # + binary QC flags (#51).
        breakdowns = component_breakdowns(inst, leaf.part_type_id)
        qc_flags = component_qc_flags(inst, leaf.part_type_id)

    # htmx pager clicks swap just their pane (keyed by hx-target), so the page
    # keeps its scroll position instead of reloading and jumping to the top.
    if getattr(request, "htmx", False):
        fragment = {"parts-pane": "explore/_parts_table.html",
                    "empty-boxes-pane": "explore/_empty_boxes_table.html",
                    }.get(request.htmx.target)
        if fragment:
            return render(request, fragment, {
                "parts_page": parts_page, "empty_boxes_page": empty_boxes_page})

    return render(
        request,
        "explore/explore.html",
        {
            "view": view,
            "sidebar": navigation.sidebar_tree(inst, view["ctx"]),
            "leaf": leaf,
            "charts": charts,
            "parts_page": parts_page,
            "breakdowns": breakdowns,
            "qc_flags": qc_flags,
            "is_shipping": is_shipping,
            "shipments": shipments,
            "shipment_synced_at": shipment_synced_at,
            "shipment_summary": shipment_summary,
            "empty_boxes_page": empty_boxes_page,
            "can_create_box": can_create_box,
            "can_edit_es": can_edit_es,
            "empty_pids": empty_pids,
            # Deep-link the part type to this instance's FNAL web UI.
            "hwdb_ui_base": settings.HWDB_PROFILES[inst]["ui"],
            "sync_state": HierarchySyncState.get(inst),
        },
    )


@login_not_required
@fnal_login_required
def explore_hierarchy_view(request):
    """The detector hierarchy chart (#55): the consortium component-type
    chart, rendered server-side as SVG from its spec in ``chart_specs/``.
    The chart model is instance-independent; the node → part-type mapping
    (#58) and sidebar are per-instance."""
    inst = instance_of(request)
    return render(request, "explore/hierarchy.html", {
        "active_nav": "detector",
        "sidebar": navigation.sidebar_tree(inst, {}),
        "chart": charts.svg_chart("fd-vd-v10"),
        "type_mapping": charts.type_mapping("fd-vd-v10", inst),
    })


_PTID_RX = re.compile(r"^[A-Z]\d{11}$")


@login_not_required
@fnal_login_required
def explore_type_summary_view(request):
    """Compact per-type summaries for the chart popup (#58): mirror-only, no
    live HWDB. ``?ids=`` takes comma-separated part type ids (the mapping may
    attach several flavors to one chart box); unknown ids come back with
    ``name: null`` so the popup can say "not in the mirror yet". Counts and
    status breakdowns only — no per-item listing (types can hold thousands;
    the Type View link is the place to browse items)."""
    inst = instance_of(request)
    ids = [i for i in (request.GET.get("ids") or "").split(",") if i]
    if not ids or len(ids) > 20 or not all(_PTID_RX.match(i) for i in ids):
        return JsonResponse({"error": "ids must be 1-20 part type ids"}, status=400)
    types = []
    for ptid in ids:
        leaf = HierarchyNode.for_instance(inst).filter(
            level=HierarchyNode.LEVEL_TYPE, part_type_id=ptid).first()
        if leaf is None:
            types.append({"part_type_id": ptid, "name": None})
            continue
        events = HwdbComponentEvent.for_instance(inst).filter(part_type_id=ptid)
        statuses: dict[str, int] = {}
        for s in events.values_list("status", flat=True):
            key = s or "(no status)"
            statuses[key] = statuses.get(key, 0) + 1
        types.append({
            "part_type_id": ptid,
            "name": leaf.name,
            "subsystem": f"{leaf.system_name} › {leaf.subsystem_name}",
            "n_components": leaf.n_components,
            "statuses": statuses,
            "url": navigation.leaf_path_for(inst, ptid),
        })
    return JsonResponse({"types": types})


@login_not_required
@fnal_login_required
def shipments_view(request):
    """Top-level Shipments dashboard (Hajime's ask): all boxes across the
    curated shipping types in one view, each linking into the box's existing
    leaf node view. Reads the mirror (skip-empties, like the leaf panel)."""
    inst = instance_of(request)
    boxes, n_types = [], 0
    agg = {"total": 0, "in_transit": 0, "delivered": 0}
    # Explicit ids + every mirrored type under a curated shipping subsystem
    # (the "86.990" selectors).
    ptids = set(curation.shipping_types(inst))
    for sid, ssid in curation.shipping_subsystems(inst):
        ptids.update(HierarchyNode.for_instance(inst).filter(
            level=HierarchyNode.LEVEL_TYPE, system_id=sid, subsystem_id=ssid,
        ).values_list("part_type_id", flat=True))
    # Tracked types grouped by subsystem — the page renders one collapsible
    # card per group with a compact per-type table (boxes-first, 0-box rows
    # dimmed). sync_targets feeds the "Sync all types" button.
    groups, sync_targets = {}, []
    for ptid in sorted(ptids):
        leaf = HierarchyNode.for_instance(inst).filter(
            level=HierarchyNode.LEVEL_TYPE, part_type_id=ptid).first()
        if not leaf:  # curated but not yet refreshed into the mirror
            continue
        n_types += 1
        sync_targets.append({
            "ptid": ptid, "name": leaf.name,
            "url": _rev(request, "explore:shipment_sync", args=[ptid]),
        })
        path = navigation.leaf_path_for(inst, ptid)
        rows = list(ShipmentItem.for_instance(inst).filter(part_type_id=ptid, n_contents__gt=0))
        in_transit = sum(1 for r in rows if r.location_id == 0)
        delivered = sum(1 for r in rows if r.location_id not in (0, None))
        agg["total"] += len(rows)
        agg["in_transit"] += in_transit
        agg["delivered"] += delivered
        sec = {
            "leaf": leaf, "path": path, "n": len(rows),
            "in_transit": in_transit, "delivered": delivered,
            "synced_at": leaf.shipments_synced_at,
        }
        g = groups.setdefault((leaf.system_id, leaf.subsystem_id), {
            "sid": leaf.system_id, "ssid": leaf.subsystem_id,
            "system_name": leaf.system_name, "subsystem_name": leaf.subsystem_name,
            "active": [], "idle": [], "n": 0, "in_transit": 0, "delivered": 0,
            "n_unsynced": 0,
        })
        g["active" if rows else "idle"].append(sec)
        g["n"] += len(rows)
        g["in_transit"] += in_transit
        g["delivered"] += delivered
        g["n_unsynced"] += 0 if leaf.shipments_synced_at else 1
        for r in rows:
            boxes.append({"box": r, "type_name": leaf.name, "path": path})
    groups = [groups[k] for k in sorted(groups)]

    # In-transit first, then most-recently-arrived first.
    boxes.sort(key=lambda x: (
        0 if x["box"].location_id == 0 else 1,
        -(x["box"].last_arrived.timestamp() if x["box"].last_arrived else 0),
    ))
    page_obj = Paginator(boxes, 50).get_page(request.GET.get("page"))
    # htmx pager clicks swap just the boxes pane in place (no scroll-to-top).
    if getattr(request, "htmx", False) and request.htmx.target == "shipments-pane":
        return render(request, "explore/_shipments_table.html", {"page_obj": page_obj})
    return render(request, "explore/shipments.html", {
        "active_nav": "shipments",
        "sidebar": navigation.sidebar_tree(inst, {}),
        "groups": groups,
        "n_types": n_types,
        "sync_targets": sync_targets,
        "page_obj": page_obj,
        "summary": agg,
        "hwdb_ui_base": settings.HWDB_PROFILES[inst]["ui"],
    })


@login_not_required
@fnal_login_required
@require_POST
def explore_sync_view(request):
    """Stream a skeleton (hierarchy) refresh into ``HierarchyNode``.

    FNAL-gated; unlinked user is redirected to the link page with a ?next back
    to /explore/. Reads the tree of the URL's instance (#47).
    """
    inst = instance_of(request)
    try:
        bearer = mint_for(request)
    except FnalLinkRequired:
        link = reverse("hwdb:link")
        return redirect(f"{link}?{urlencode({'next': _rev(request, 'explore:home'), 'reason': 'expired'})}")
    except FnalUnavailable:
        return render(request, "hwdb/error.html", {"error_message": FNAL_UNAVAILABLE})

    api = FnalDbApiClient(settings.HWDB_PROFILES[inst]["api"], bearer)

    def _iter():
        try:
            yield from sync_hierarchy(api, inst)
        except Exception as e:
            logger.exception("explore_sync_view crashed")
            yield f"hierarchy sync: CRASH · {e}\n"

    return StreamingHttpResponse(_iter(), content_type="text/plain; charset=utf-8")


@login_not_required
@fnal_login_required
@require_POST
def explore_system_sync_view(request, system_id):
    """Stream a one-system structure walk (the overflow section's lazy sync,
    #49). FNAL-gated; reads the URL's instance. Fired automatically on first
    visit to an unwalked uncurated system, and by the retry button after a
    failed walk."""
    inst = instance_of(request)
    try:
        bearer = mint_for(request)
    except FnalLinkRequired:
        link = reverse("hwdb:link")
        return redirect(f"{link}?{urlencode({'next': _rev(request, 'explore:home'), 'reason': 'expired'})}")
    except FnalUnavailable:
        return render(request, "hwdb/error.html", {"error_message": FNAL_UNAVAILABLE})

    api = FnalDbApiClient(settings.HWDB_PROFILES[inst]["api"], bearer)

    def _iter():
        try:
            yield from sync_system(api, inst, system_id)
        except Exception as e:
            logger.exception("explore_system_sync_view(%s) crashed", system_id)
            yield f"walk system: CRASH · {e}\n"

    return StreamingHttpResponse(_iter(), content_type="text/plain; charset=utf-8")


@login_not_required
@fnal_login_required
@require_POST
def explore_node_sync_view(request, part_type_id):
    """Stream a test-event sync for one component type (issue #30).

    Lazy per-type sync behind the explorer's plot panel. FNAL-gated; reads the
    URL's instance (#47). The browser fires this automatically on first visit
    to an unsynced leaf, and on the manual sync-mode buttons.
    """
    inst = instance_of(request)
    try:
        bearer = mint_for(request)
    except FnalLinkRequired:
        link = reverse("hwdb:link")
        nxt = f"{_rev(request, 'explore:home')}?node={part_type_id}"
        return redirect(f"{link}?{urlencode({'next': nxt, 'reason': 'expired'})}")
    except FnalUnavailable:
        return render(request, "hwdb/error.html", {"error_message": FNAL_UNAVAILABLE})

    base_url = settings.HWDB_PROFILES[inst]["api"]
    mode = request.POST.get("mode", "incremental")
    if mode not in ("incremental", "components", "full"):
        mode = "incremental"

    def _iter():
        try:
            yield from sync_test_events(base_url, bearer, part_type_id,
                                        instance=inst, mode=mode)
        except Exception as e:
            logger.exception("explore_node_sync_view(%s) crashed", part_type_id)
            yield f"test sync: CRASH · {e}\n"

    return StreamingHttpResponse(_iter(), content_type="text/plain; charset=utf-8")


@login_not_required
@fnal_login_required
@require_POST
def explore_shipment_sync_view(request, part_type_id):
    """Stream a shipment (latest-location) sync for one shipping type (#43).

    Mirrors the latest location of each box into ``ShipmentItem``. FNAL-gated;
    reads the URL's instance (#47). Fired automatically on first visit to an
    unsynced shipping leaf, and by the manual "Sync shipments" button.
    """
    inst = instance_of(request)
    try:
        bearer = mint_for(request)
    except FnalLinkRequired:
        link = reverse("hwdb:link")
        nxt = f"{_rev(request, 'explore:home')}?node={part_type_id}"
        return redirect(f"{link}?{urlencode({'next': nxt, 'reason': 'expired'})}")
    except FnalUnavailable:
        return render(request, "hwdb/error.html", {"error_message": FNAL_UNAVAILABLE})

    base_url = settings.HWDB_PROFILES[inst]["api"]
    mode = request.POST.get("mode", "full")
    if mode not in ("full", "incremental"):
        mode = "full"

    def _iter():
        try:
            yield from sync_shipments(base_url, bearer, part_type_id, inst, mode=mode)
        except Exception as e:
            logger.exception("explore_shipment_sync_view(%s) crashed", part_type_id)
            yield f"shipment sync: CRASH · {e}\n"

    return StreamingHttpResponse(_iter(), content_type="text/plain; charset=utf-8")


@login_not_required
@fnal_login_required
def explore_shipment_image_view(request, image_id):
    """Proxy one box attachment — shipping label, bill of lading, proforma
    invoice — straight from HWDB (ADR-0013).

    The bytes are bearer-gated, so we mint and stream them through rather than
    handing the browser a direct FNAL link. ``?name=`` sets the download
    filename (sanitised).
    """
    try:
        bearer = mint_for(request)
    except FnalLinkRequired:
        return JsonResponse(
            {"error": "fnal_link", "link": reverse("hwdb:link")}, status=409
        )
    except FnalUnavailable:
        return JsonResponse({"error": "unavailable"}, status=502)

    api = FnalDbApiClient(settings.HWDB_PROFILES[instance_of(request)]["api"], bearer)
    try:
        upstream = api.get_image_response(image_id)
    except Exception:
        logger.exception("explore_shipment_image_view(%s) crashed", image_id)
        return JsonResponse({"error": "fetch_failed"}, status=502)

    raw = request.GET.get("name") or f"hwdb-{image_id}"
    safe = "".join(c for c in raw if c.isalnum() or c in " ._-").strip() or f"hwdb-{image_id}"
    # ?inline=1 → view in the browser (thumbnail click); default → download.
    disposition = "inline" if request.GET.get("inline") else "attachment"
    resp = StreamingHttpResponse(
        upstream.iter_content(chunk_size=65536),
        content_type=upstream.headers.get("Content-Type", "application/octet-stream"),
    )
    resp["Content-Disposition"] = f'{disposition}; filename="{safe}"'
    return resp


@login_not_required
@fnal_login_required
def explore_test_data_view(request, part_id, test_type_id):
    """Render one test's ``test_data`` payload as pretty JSON, inline as text
    (opened in a new tab) — ADR-0014.

    The structured field the Python dashboard's test-data export serializes;
    here, per part + test type, the latest record's ``test_data`` straight from
    HWDB. FNAL-gated.
    """
    try:
        bearer = mint_for(request)
    except FnalLinkRequired:
        return JsonResponse({"error": "fnal_link", "link": reverse("hwdb:link")}, status=409)
    except FnalUnavailable:
        return JsonResponse({"error": "unavailable"}, status=502)

    api = FnalDbApiClient(settings.HWDB_PROFILES[instance_of(request)]["api"], bearer)
    try:
        data = api.get_tests(part_id, test_type_id=test_type_id).get("data")
    except Exception:
        logger.exception("explore_test_data_view(%s,%s) crashed", part_id, test_type_id)
        return JsonResponse({"error": "fetch_failed"}, status=502)

    rec = (max(data, key=lambda r: r.get("created") or "")
           if isinstance(data, list) and data else data if isinstance(data, dict) else None)
    test_data = (rec or {}).get("test_data")
    body = json.dumps(test_data if test_data is not None else {}, indent=2)
    return HttpResponse(body, content_type="text/plain; charset=utf-8")


@login_not_required
@fnal_login_required
def explore_part_view(request, part_id):
    """Generic per-part detail page (ADR-0014): item facts, a latest-per-type
    test summary, subcomponents, specifications, attachments (with download)
    and a location timeline — live from HWDB. A shipping box additionally shows
    its shipment lifecycle. FNAL-gated; an unlinked user is bounced to link with
    a ?next back here.
    """
    inst = instance_of(request)
    try:
        bearer = mint_for(request)
    except FnalLinkRequired:
        link = reverse("hwdb:link")
        return redirect(f"{link}?{urlencode({'next': request.get_full_path(), 'reason': 'expired'})}")
    except FnalUnavailable:
        return render(request, "explore/part_detail.html",
                      {"part_id": part_id, "unavailable": True,
                       "sidebar": navigation.sidebar_tree(inst, {})})

    ptid = part_id.rsplit("-", 1)[0]
    is_shipping = curation.is_shipping_type(inst, ptid)
    api = FnalDbApiClient(settings.HWDB_PROFILES[inst]["api"], bearer)
    try:
        detail = part_detail(api, part_id, is_shipping)
    except Exception as e:
        logger.exception("explore_part_view(%s) crashed", part_id)
        return render(request, "explore/part_detail.html",
                      {"part_id": part_id, "unavailable": True,
                       "error_detail": f"{type(e).__name__}: {e}" if settings.DEBUG else None,
                       "sidebar": navigation.sidebar_tree(inst, {})})

    # Catch-all attachments minus the ones already shown in a spec section.
    shown = {a["image_id"] for sec in detail["sections"] for a in sec["attachments"]}
    other_attachments = [a for a in detail["attachments"] if a["image_id"] not in shown]

    leaf = HierarchyNode.for_instance(inst).filter(
        level=HierarchyNode.LEVEL_TYPE, part_type_id=ptid).first()
    # Open + highlight this part's component type in the sidebar tree.
    side_ctx = navigation.leaf_sidebar_ctx(inst, leaf) if leaf else {}
    box = (ShipmentItem.for_instance(inst).filter(part_id=part_id).first()
           if is_shipping else None)
    # Mirror fallback for containment (issue #63): used only when the live
    # /container call yields nothing (detail.container is preferred).
    mirror_parent = (HwdbComponentEvent.for_instance(inst)
                     .filter(part_id=part_id).exclude(parent_part_id="")
                     .values_list("parent_part_id", flat=True).first())
    # First write feature (issue #61): boxes on a write-enabled instance get
    # the Update-location form; its dropdown needs the institution list.
    can_update_location = is_shipping and inst in settings.HWDB_WRITE_INSTANCES
    # The type's ES config (consortium, description) for the Executive-summary
    # card. Any type carrying one is "marked" for an ES — the interim mark
    # until the hierarchy-chart one exists.
    es_cfg, es_cfg_msg = (execsummary.load_config(api, ptid)
                          if inst in settings.HWDB_WRITE_INSTANCES else (None, ""))
    exec_summaries = sorted(
        (a for a in detail["attachments"]
         if (a["image_name"] or "").lower().startswith(
             f"executivesummary_{part_id.lower()}_")),
        key=lambda a: a["image_name"] or "", reverse=True)
    for a in exec_summaries:
        a["label"] = _summary_label(a["image_name"])
    return render(request, "explore/part_detail.html", {
        # A box belongs to the Shipments tab; everything else to Hardware.
        "active_nav": "shipments" if is_shipping else "hardware",
        "sidebar": navigation.sidebar_tree(inst, side_ctx),
        "part_id": part_id,
        "detail": detail,
        "is_shipping": is_shipping,
        "other_attachments": other_attachments,
        "leaf": leaf,
        "leaf_path": navigation.leaf_path_for(inst, ptid) if leaf else None,
        "box": box,
        "mirror_parent": mirror_parent,
        "hwdb_ui_base": settings.HWDB_PROFILES[inst]["ui"],
        "can_update_location": can_update_location,
        "institutions": _institution_options(api) if can_update_location else [],
        "arrived_default": timezone.localtime().strftime("%Y-%m-%dT%H:%M"),
        # Packing card (issue #63): the box's slot schema + occupants; the
        # item picker is its own page. None when writes are off or the
        # connectors fetch fails (the card just doesn't render).
        "packing": (_packing_context(api, inst, ptid, detail["manifest"])
                    if can_update_location else None),
        # Executive summaries already on this item (issue #53): attachments
        # matching the Dashboard's gate convention, newest first (the gate
        # filename embeds the timestamp, so name order is chronological).
        "exec_summaries": exec_summaries,
        "es_cfg": es_cfg,
        "es_cfg_msg": es_cfg_msg,
        # Ship/receive checklist runs on this box (issue #65), by workflow.
        "checklists": ({c.workflow: c for c in
                        BoxChecklist.for_instance(inst).filter(part_id=part_id)}
                       if can_update_location else {}),
    })


def _summary_label(name: str) -> str:
    """Short label for a summary PDF: the timestamp its gate-convention
    filename embeds (``ExecutiveSummary_{pid}_{YYYYmmdd_HHMMSS}.pdf``)."""
    m = re.search(r"_(\d{8})_(\d{6})\.pdf$", name or "", re.IGNORECASE)
    if not m:
        return name or ""
    d, t = m.groups()
    return f"{d[:4]}-{d[4:6]}-{d[6:]} {t[:2]}:{t[2:4]}"


def _institution_options(api) -> list[dict]:
    """Institution choices for the Update-location form, name-sorted.
    Best-effort: an empty list renders the form disabled rather than
    breaking the part page."""
    try:
        rows = api.get_institutions().get("data") or []
    except Exception as e:
        logger.warning("institutions fetch failed: %s", e)
        return []
    opts = [{"id": r.get("id"), "name": r.get("name") or "",
             "country_code": ((r.get("country") or {}).get("code") or "")}
            for r in rows if isinstance(r, dict) and r.get("id") is not None]
    return sorted(opts, key=lambda o: o["name"].lower())


@login_not_required
@fnal_login_required
@require_POST
def explore_part_location_view(request, part_id):
    """Post a location update for a shipping box — the explorer's first HWDB
    write (issue #61), mirroring the Dashboard's "Update location" workflow.

    Gated to ``HWDB_WRITE_INSTANCES`` (dev-only for now) on top of the usual
    FNAL gate; the payload matches the Dashboard's exactly. After a successful
    post, the box's mirrored ShipmentItem row is refreshed in place so the
    Shipments dashboard agrees without a whole-type sync.
    """
    inst = instance_of(request)
    part_url = _rev(request, "explore:part", args=[part_id])
    ptid = part_id.rsplit("-", 1)[0]
    if inst not in settings.HWDB_WRITE_INSTANCES or not curation.is_shipping_type(inst, ptid):
        return HttpResponseForbidden("Location updates are not enabled here.")

    try:
        payload = {
            "location": {"id": int(request.POST.get("location_id") or "")},
            "arrived": datetime.fromisoformat(
                (request.POST.get("arrived") or "").strip()).isoformat(),
            "comments": (request.POST.get("comments") or "").strip(),
        }
    except (TypeError, ValueError):
        messages.error(request, "Pick a location and a valid arrival time.")
        return redirect(part_url)

    try:
        bearer = mint_for(request)
    except FnalLinkRequired:
        link = reverse("hwdb:link")
        return redirect(f"{link}?{urlencode({'next': part_url, 'reason': 'expired'})}")
    except FnalUnavailable:
        messages.error(request, FNAL_UNAVAILABLE)
        return redirect(part_url)

    api = FnalDbApiClient(settings.HWDB_PROFILES[inst]["api"], bearer)
    try:
        api.post_location(part_id, payload)
    except requests.RequestException as e:
        logger.warning("post location for %s failed: %s", part_id, e)
        messages.error(request, f"HWDB rejected the location update — {_hwdb_error_detail(e)}")
        return redirect(part_url)

    try:  # targeted mirror refresh; the write itself already succeeded
        refresh_box(api, inst, ptid, part_id)
    except Exception as e:
        logger.warning("refresh_box(%s) failed: %s", part_id, e)
    messages.success(request, "Location update posted to HWDB.")
    return redirect(part_url)


@login_not_required
@fnal_login_required
def explore_institutions_view(request):
    """Institution options as JSON — lazy-loaded by the write forms' dropdowns
    (issue #62), so mirror-only pages stay live-fetch-free on render."""
    inst = instance_of(request)
    if inst not in settings.HWDB_WRITE_INSTANCES:
        return JsonResponse({"error": "writes disabled"}, status=403)
    try:
        bearer = mint_for(request)
    except FnalLinkRequired:
        return JsonResponse({"error": "link"}, status=401)
    except FnalUnavailable:
        return JsonResponse({"error": "unavailable"}, status=503)
    api = FnalDbApiClient(settings.HWDB_PROFILES[inst]["api"], bearer)
    return JsonResponse({"institutions": _institution_options(api)})


def _refresh_box_quietly(api, instance, part_type_id, part_id):
    """Best-effort mirror-row refresh after a write that already succeeded."""
    try:
        refresh_box(api, instance, part_type_id, part_id)
    except Exception as e:
        logger.warning("refresh_box(%s) failed: %s", part_id, e)


def _hwdb_error_detail(e) -> str:
    """The useful part of an HWDB write error: the JSON body's ``data``
    message when the response carries one (e.g. "The component '…' is
    already in use"), else the exception text."""
    resp = getattr(e, "response", None)
    try:
        detail = (resp.json() or {}).get("data") if resp is not None else None
    except ValueError:
        detail = None
    return str(detail) if detail else str(e)


def _spec_template(type_record: dict) -> dict:
    """The type's spec datasheet — the template a create payload must echo
    (the official flow posts ``ct.properties.specifications[-1].datasheet``)."""
    specs = (((type_record.get("data") or {}).get("properties") or {})
             .get("specifications") or [])
    ds = (specs[-1] or {}).get("datasheet") if specs else None
    return ds if isinstance(ds, dict) else {}


@login_not_required
@fnal_login_required
@require_POST
def explore_box_create_view(request, part_type_id):
    """Mint a new shipping box of this type in HWDB — the iPad app's "request
    a new PID" (issue #62), from the shipping type's page.

    Payload mirrors the official create flow: institution (+ its country
    code), optional serial/comments, the type's spec datasheet echoed
    verbatim, and the manufacturer only when the type defines exactly one.
    On success the box gets a mirror row immediately and the user lands on
    its part page, ready for packing.
    """
    inst = instance_of(request)
    if inst not in settings.HWDB_WRITE_INSTANCES or not curation.is_shipping_type(inst, part_type_id):
        return HttpResponseForbidden("Box creation is not enabled here.")
    back = navigation.leaf_path_for(inst, part_type_id) or _rev(request, "explore:browse")

    try:
        bearer = mint_for(request)
    except FnalLinkRequired:
        link = reverse("hwdb:link")
        return redirect(f"{link}?{urlencode({'next': back, 'reason': 'expired'})}")
    except FnalUnavailable:
        messages.error(request, FNAL_UNAVAILABLE)
        return redirect(back)

    api = FnalDbApiClient(settings.HWDB_PROFILES[inst]["api"], bearer)
    institution = next((o for o in _institution_options(api)
                        if str(o["id"]) == (request.POST.get("institution_id") or "")), None)
    if institution is None:
        messages.error(request, "Pick an institution for the new box.")
        return redirect(back)

    try:
        type_record = api.get_component_type(part_type_id)
        manufacturers = (type_record.get("data") or {}).get("manufacturers") or []
        payload = {
            "component_type": {"part_type_id": part_type_id},
            "country_code": institution["country_code"],
            "institution": {"id": institution["id"]},
            "serial_number": (request.POST.get("serial_number") or "").strip(),
            "comments": (request.POST.get("comments") or "").strip(),
            "specifications": _spec_template(type_record),
        }
        if len(manufacturers) == 1 and manufacturers[0].get("id") is not None:
            payload["manufacturer"] = {"id": manufacturers[0]["id"]}
        body = api.create_component(part_type_id, payload)
    except requests.RequestException as e:
        logger.warning("box create for %s failed: %s", part_type_id, e)
        messages.error(request, f"HWDB rejected the new box — {_hwdb_error_detail(e)}")
        return redirect(back)
    part_id = body.get("part_id")
    if body.get("status") != "OK" or not part_id:
        messages.error(request, f"HWDB rejected the new box — {body.get('data') or body}")
        return redirect(back)

    try:  # the box exists now; give it a mirror row so it lists immediately
        refresh_box(api, inst, part_type_id, part_id)
    except Exception as e:
        logger.warning("refresh_box(%s) failed: %s", part_id, e)
    messages.success(request, f"Box {part_id} minted in the {inst} HWDB.")
    return redirect(_rev(request, "explore:part", args=[part_id]))


# Candidate PIDs listed per child type on the packing page. Any PID can still
# be typed/scanned into the add-by-PID box; the cap only bounds the table.
_PACK_CANDIDATE_CAP = 500


def _box_connectors(api, part_type_id) -> dict:
    """The box type's connectors: {functional position: child part_type_id}.
    These named slots are HWDB's own model — an item can only be linked into
    one, and the slot set is fixed by the type's definition."""
    return ((api.get_component_type(part_type_id).get("data") or {})
            .get("connectors") or {})


def _packing_context(api, instance, part_type_id, manifest) -> dict | None:
    """The box page's packing card (issue #63): the box's full slot schema —
    every functional position with the child type it accepts and its current
    occupant — plus free/total counts. The schema is the type's connectors,
    so users see exactly what this box can hold. Candidate picking lives on
    the separate packing page. None if the connectors fetch fails."""
    try:
        connectors = _box_connectors(api, part_type_id)
    except Exception as e:
        logger.warning("packing: connectors for %s failed: %s", part_type_id, e)
        return None
    names = {n.part_type_id: n.name
             for n in HierarchyNode.for_instance(instance).filter(
                 level=HierarchyNode.LEVEL_TYPE,
                 part_type_id__in={v for v in connectors.values() if v})}
    occupied = {m["functional_position"]: m["part_id"] for m in manifest}
    positions = [{"position": pos, "child_type_id": ctid,
                  "child_type_name": names.get(ctid, ctid),
                  "current": occupied.get(pos)}
                 for pos, ctid in sorted(connectors.items())]
    n_free = sum(1 for p in positions if not p["current"])
    return {"positions": positions, "n_total": len(positions), "n_free": n_free}


def _pack_groups(instance, connectors, manifest) -> list[dict]:
    """The packing page's pickable candidates: one group per child type that
    still has free slots — mirror rows of that type, with status + QC flags
    so un-shippable items are visible up front. Rows with a known parent
    (HWDB rejects those with "already in use") or known-unapproved
    (``enabled=False``) are hidden; unknowns pass and HWDB stays the arbiter
    (a refused add reports that item's live HWDB status flags)."""
    occupied = {m["functional_position"] for m in manifest}
    in_box = {m["part_id"] for m in manifest if m["part_id"]}
    free_by_type: dict[str, int] = {}
    for pos, ctid in connectors.items():
        if pos not in occupied and ctid:
            free_by_type[ctid] = free_by_type.get(ctid, 0) + 1
    groups = []
    for ctid, n_free in sorted(free_by_type.items()):
        rows = (HwdbComponentEvent.for_instance(instance)
                .filter(part_type_id=ctid, parent_part_id="")
                .exclude(part_id__in=in_box)
                .exclude(enabled=False)
                .order_by("part_id"))
        leaf = HierarchyNode.for_instance(instance).filter(
            level=HierarchyNode.LEVEL_TYPE, part_type_id=ctid).first()
        groups.append({
            "type_id": ctid, "name": leaf.name if leaf else ctid,
            "n_free": n_free, "total": rows.count(),
            "candidates": [
                {"part_id": r.part_id, "status": r.status or "—",
                 "qc_ok": bool(r.qaqc_uploaded and r.certified_qaqc),
                 "institution": r.institution or "—"}
                for r in rows[:_PACK_CANDIDATE_CAP]],
        })
    return groups


@login_not_required
@fnal_login_required
def explore_box_pack_view(request, part_id):
    """The packing page + endpoint (issue #63) — the iPad app's packing
    step 2, via ``PATCH components/{pid}/subcomponents``.

    GET renders the item picker: one candidate group per child type with free
    slots (mirror rows with status + QC flags), plus an add-by-PID box for
    typed/scanned entries. POST either unlinks one position (``unlink=<pos>``,
    from the box page) or links the picked ``pid`` values — users pick items,
    not slots; the server assigns each item to a free slot of its type.
    Following the official clients, the PATCH always carries the COMPLETE
    positions dict (current state + this request's changes).
    """
    inst = instance_of(request)
    part_url = _rev(request, "explore:part", args=[part_id])
    pack_url = _rev(request, "explore:box_pack", args=[part_id])
    ptid = part_id.rsplit("-", 1)[0]
    if inst not in settings.HWDB_WRITE_INSTANCES or not curation.is_shipping_type(inst, ptid):
        return HttpResponseForbidden("Packing is not enabled here.")

    try:
        bearer = mint_for(request)
    except FnalLinkRequired:
        link = reverse("hwdb:link")
        return redirect(f"{link}?{urlencode({'next': part_url, 'reason': 'expired'})}")
    except FnalUnavailable:
        messages.error(request, FNAL_UNAVAILABLE)
        return redirect(part_url)

    api = FnalDbApiClient(settings.HWDB_PROFILES[inst]["api"], bearer)
    try:
        connectors = _box_connectors(api, ptid)
        manifest = current_manifest(api.get_subcomponents(part_id).get("data"))
        current = {pos: None for pos in connectors}
        for m in manifest:
            if m["functional_position"] in current:
                current[m["functional_position"]] = m["part_id"]
    except requests.RequestException as e:
        logger.warning("packing: state fetch for %s failed: %s", part_id, e)
        messages.error(request, f"Couldn’t read the box’s current state — {e}")
        return redirect(part_url)

    if request.method != "POST":
        # Phone-as-scanner hookup (issue #68): the picker polls the scan feed
        # for PIDs this user scans on their phone, starting AFTER the newest
        # row at page load so stale scans don't flood in.
        scan_url = request.build_absolute_uri(_rev(request, "explore:scan"))
        scan_since = (PackScan.for_instance(inst)
                      .filter(username=request.user.get_username())
                      .order_by("-id").values_list("id", flat=True).first()) or 0
        return render(request, "explore/pack.html", {
            "active_nav": "shipments",
            "sidebar": navigation.sidebar_tree(inst, {}),
            "part_id": part_id,
            "part_type_id": ptid,
            "n_contents": len(manifest),
            "groups": _pack_groups(inst, connectors, manifest),
            "scan_url": scan_url,
            "scan_qr_svg": scanning.qr_svg(scan_url),
            "scan_feed_url": _rev(request, "explore:scan_feed"),
            "scan_since": scan_since,
        })

    unlink = (request.POST.get("unlink") or "").strip()
    if unlink:
        removed = current.get(unlink)
        if unlink not in current or not removed:
            messages.error(request, f"Position “{unlink}” has nothing to unlink.")
            return redirect(part_url)
        payload = {"component": {"part_id": part_id},
                   "subcomponents": {**current, unlink: None}}
        try:
            body = api.patch_subcomponents(part_id, payload)
        except requests.RequestException as e:
            logger.warning("packing: unlink patch for %s failed: %s", part_id, e)
            messages.error(request, f"HWDB rejected the packing change — {_hwdb_error_detail(e)}")
            return redirect(part_url)
        if body.get("status") != "OK":
            messages.error(request, f"HWDB rejected the packing change — {body.get('data') or body}")
            return redirect(part_url)
        _refresh_box_quietly(api, inst, ptid, part_id)
        messages.success(request, f"Unlinked {removed} from “{unlink}”.")
        return redirect(part_url)

    # Add mode. Checked candidates + the add-by-PID box, deduped, order kept.
    back = pack_url  # keep the user on the picker when an add fails
    picked = list(dict.fromkeys(
        [p.strip() for p in request.POST.getlist("pid") if p.strip()]
        + re.split(r"[\s,]+", (request.POST.get("manual") or "").strip())))
    picked = [p for p in picked if p]
    if not picked:
        messages.error(request, "Pick at least one item to add.")
        return redirect(back)
    # Free slots per child type, in stable position order.
    free_by_type: dict[str, list] = {}
    for pos in sorted(current, key=str):
        if current[pos] is None and connectors.get(pos):
            free_by_type.setdefault(connectors[pos], []).append(pos)
    changes = {}
    for pid in picked:
        if not re.fullmatch(r"[A-Z]\d{11}-\d{5}", pid):
            messages.error(request, f"“{pid}” doesn’t look like a PID.")
            return redirect(back)
        if pid in current.values():
            messages.error(request, f"{pid} is already in this box.")
            return redirect(back)
        ctid = pid.rsplit("-", 1)[0]
        free = free_by_type.get(ctid)
        if free is None:
            messages.error(request,
                           f"This box has no positions for {ctid} items ({pid}).")
            return redirect(back)
        if not free:
            messages.error(request,
                           f"No free positions left for {ctid} items ({pid}).")
            return redirect(back)
        changes[free.pop(0)] = pid

    # One PATCH per item: HWDB has no "is it free?" lookup, so an item that's
    # secretly inside some other assembly only fails at write time — and it
    # must not sink the rest of the batch. State accumulates across successes.
    added, failed, state = [], [], dict(current)
    for pos, pid in changes.items():
        payload = {"component": {"part_id": part_id},
                   "subcomponents": {**state, pos: pid}}
        try:
            body = api.patch_subcomponents(part_id, payload)
            ok, detail = body.get("status") == "OK", body.get("data")
        except requests.RequestException as e:
            logger.warning("packing: patch %s into %s failed: %s", pid, part_id, e)
            ok, detail = False, _hwdb_error_detail(e)
        if ok:
            state[pos] = pid
            added.append(pid)
        else:
            try:  # tell the user where the refused item actually is
                parent = current_container(api.get_container(pid).get("data") or [])
            except Exception:
                parent = None
            if parent:
                detail = f"{detail} (it is inside {parent['part_id']})"
            else:
                try:  # …or HWDB's own status flags on why it's unavailable
                    flags = api.get_component_status(pid).get("data") or {}
                    shown = ", ".join(
                        f"{k}={v.get('name') if isinstance(v, dict) else v}"
                        for k, v in flags.items())
                    if shown:
                        detail = f"{detail} (HWDB status: {shown})"
                except Exception:
                    pass
            failed.append((pid, detail))

    if added:
        _refresh_box_quietly(api, inst, ptid, part_id)
        messages.success(request, f"Added {len(added)} item(s): {', '.join(added)}.")
    for pid, detail in failed:
        messages.error(request, f"{pid} was not added — {detail}")
    return redirect(back if failed else part_url)


@login_not_required
@fnal_login_required
def explore_scan_view(request):
    """The phone scanner page (issue #68): camera decoding in the browser
    (vendored html5-qrcode, same as the Dashboard's scanner), each hit POSTed
    to the submit endpoint below. No pairing tokens or scanner-specific auth
    — the phone signs in with the same FNAL session login as any browser,
    and scans queue for the SAME username's open packing page."""
    inst = instance_of(request)
    if inst not in settings.HWDB_WRITE_INSTANCES:
        return HttpResponseForbidden("Scanning is not enabled here.")
    return render(request, "explore/scan.html", {
        "submit_url": _rev(request, "explore:scan_submit"),
    })


@login_not_required
@fnal_login_required
@require_POST
def explore_scan_submit_view(request):
    """One scanned (or typed) text → a queued PackScan row. PID extraction
    handles bare PIDs, label suffixes and HWDB URLs (the Dashboard's
    regexes). The user's day-old rows are swept opportunistically."""
    inst = instance_of(request)
    if inst not in settings.HWDB_WRITE_INSTANCES:
        return JsonResponse({"error": "writes disabled"}, status=403)
    pid = scanning.extract_pid(request.POST.get("text") or "")
    if not pid:
        return JsonResponse({"error": "no PID in the scanned text"}, status=422)
    user = request.user.get_username()
    PackScan.objects.filter(
        username=user, created_at__lt=timezone.now() - timedelta(days=1)).delete()
    row = PackScan.objects.create(instance=inst, username=user, part_id=pid)
    return JsonResponse({"pid": pid, "id": row.id})


@login_not_required
@fnal_login_required
def explore_scan_feed_view(request):
    """The desktop packing page's poll target: this user's scans newer than
    ``?since=<id>``, oldest first."""
    inst = instance_of(request)
    if inst not in settings.HWDB_WRITE_INSTANCES:
        return JsonResponse({"error": "writes disabled"}, status=403)
    try:
        since = int(request.GET.get("since") or 0)
    except ValueError:
        since = 0
    rows = (PackScan.for_instance(inst)
            .filter(username=request.user.get_username(), id__gt=since)
            .order_by("id")[:100])
    scans = [{"id": r.id, "pid": r.part_id} for r in rows]
    return JsonResponse({"scans": scans,
                         "last": scans[-1]["id"] if scans else since})


def _next_position_names(existing, prefix: str, count: int) -> list[str]:
    """``count`` new position names ``{prefix}{n}``, numbering on from the
    highest existing ``{prefix}<number>`` so re-runs never collide."""
    pat = re.compile(rf"^{re.escape(prefix)}(\d+)$")
    start = max((int(m.group(1)) for p in existing if (m := pat.match(p))),
                default=0) + 1
    return [f"{prefix}{n}" for n in range(start, start + count)]


def _type_patch_envelope(type_record: dict, connectors: dict) -> dict:
    """The complete PATCH body for a component type — the official Encoder's
    envelope (everything echoed from a fresh GET, ``name`` carrying the full
    dotted name) with our connectors dict swapped in."""
    specs = ((type_record.get("properties") or {}).get("specifications")) or []
    datasheet = (specs[-1] or {}).get("datasheet") if specs else {}
    return {
        "comments": type_record.get("comments"),
        "connectors": connectors,
        "manufacturers": [m["id"] for m in type_record.get("manufacturers") or []
                          if isinstance(m, dict) and m.get("id") is not None],
        "name": type_record.get("full_name"),
        "part_type_id": type_record.get("part_type_id"),
        "properties": {"specifications": {
            "datasheet": datasheet if isinstance(datasheet, dict) else {}}},
        "roles": [r["id"] for r in type_record.get("roles") or []
                  if isinstance(r, dict) and r.get("id") is not None],
    }


def _find_part_type_id(body, exclude: str):
    """Dig the new type's part_type_id out of the create response — the
    OpenAPI spec leaves the response shape undocumented, so search any
    nesting for a plausible id that isn't the source type's."""
    if isinstance(body, str):
        m = re.search(r"\b[A-Z]\d{11}\b", body)
        return m.group(0) if m and m.group(0) != exclude else None
    if isinstance(body, dict):
        for key in ("part_type_id", "data"):
            found = _find_part_type_id(body.get(key), exclude)
            if found:
                return found
    return None


def _clone_box_type(request, api, inst, part_type_id, record, connectors, page_url):
    """The clone flow (issue #69): POST a new component type under the SAME
    subsystem with the source's connectors, then (create can't carry them)
    PATCH the source's datasheet / manufacturers / roles onto it, and give
    it a mirror leaf so the tree shows it without a full hierarchy sync.
    No official client exercises the create endpoint — errors are surfaced
    verbatim so a schema surprise explains itself."""
    new_name = (request.POST.get("new_name") or "").strip()
    comments = (request.POST.get("comments") or "").strip()
    m = re.match(r"^([A-Z])(\d{3})(\d{3})", part_type_id)
    if not 1 <= len(new_name) <= 100:
        messages.error(request, "Give the new type a name (up to 100 characters).")
        return redirect(page_url)
    if not m:
        messages.error(request, f"Can’t decode system/subsystem from {part_type_id}.")
        return redirect(page_url)

    # HWDB lets the caller assign the type's numeric id explicitly;
    # component_type_id is required even on a create (live-probed
    # 2026-07-13). Blank → 0, hopefully "assign one for me".
    try:
        type_number = int(request.POST.get("type_number") or "0")
    except ValueError:
        messages.error(request, "Numeric type id must be a number (or blank).")
        return redirect(page_url)
    payload = {"component_type_id": type_number,
               "name": new_name,
               "category": record.get("category") or "generic",
               "comments": comments,
               "connectors": dict(connectors)}
    try:
        body = api.post_component_type(m.group(1), int(m.group(2)), int(m.group(3)), payload)
        ok, detail = body.get("status") == "OK", body.get("data")
    except requests.RequestException as e:
        ok, detail = False, _hwdb_error_detail(e)
    if not ok:
        messages.error(request, f"HWDB rejected the new type — {detail}")
        return redirect(page_url)

    new_ptid = _find_part_type_id(body, exclude=part_type_id)
    if not new_ptid:
        messages.success(
            request, f"“{new_name}” created, but HWDB didn’t return its id — find it "
                     "via a hierarchy sync; the source spec was NOT copied onto it.")
        return redirect(page_url)

    # Copy what the create endpoint can't carry: datasheet, manufacturers, roles.
    warn = ""
    src = _type_patch_envelope(record, {})
    if src["properties"]["specifications"]["datasheet"] or src["manufacturers"] or src["roles"]:
        try:
            new_record = api.get_component_type(new_ptid).get("data") or {}
            env = _type_patch_envelope(new_record, dict(new_record.get("connectors") or {}))
            env.update({"properties": src["properties"],
                        "manufacturers": src["manufacturers"],
                        "roles": src["roles"]})
            body = api.patch_component_type(new_ptid, env)
            if body.get("status") != "OK":
                warn = f" (spec copy failed: {body.get('data') or body})"
        except requests.RequestException as e:
            warn = f" (spec copy failed: {_hwdb_error_detail(e)})"

    leaf = HierarchyNode.for_instance(inst).filter(
        level=HierarchyNode.LEVEL_TYPE, part_type_id=part_type_id).first()
    if leaf:  # a sibling mirror leaf, so the tree shows the type right away
        HierarchyNode.objects.update_or_create(
            instance=inst, level=HierarchyNode.LEVEL_TYPE, part_type_id=new_ptid,
            defaults={"parent": leaf.parent, "project": leaf.project,
                      "system_id": leaf.system_id, "system_name": leaf.system_name,
                      "subsystem_id": leaf.subsystem_id,
                      "subsystem_name": leaf.subsystem_name,
                      "name": new_name,
                      "full_name": (leaf.full_name.rsplit(".", 1)[0] + "." + new_name
                                    if "." in leaf.full_name else new_name)})

    messages.success(request, f"Created “{new_name}” as {new_ptid} with "
                              f"{len(connectors)} position(s).{warn}")
    if curation.is_shipping_type(inst, new_ptid):
        return redirect(_rev(request, "explore:box_type", args=[new_ptid]))
    messages.warning(
        request, f"{new_ptid} isn’t covered by the shipping-type curation yet — add it "
                 "to curation.yaml’s shipping_types to enable box workflows on it.")
    return redirect(page_url)


@login_not_required
@fnal_login_required
def explore_box_type_view(request, part_type_id):
    """Extend a shipping-box type's positions (issue #69): bulk-add connector
    slots ("N positions named PREFIX# accepting type X") via a complete-
    envelope ``PATCH component-types/{id}``. Add-only by design — HWDB
    forbids deleting or renaming positions that linked items use, so
    existing positions render read-only and are echoed untouched. The
    packing pages read connectors live, so changes show up immediately.
    """
    inst = instance_of(request)
    if inst not in settings.HWDB_WRITE_INSTANCES or not curation.is_shipping_type(inst, part_type_id):
        return HttpResponseForbidden("Box-type editing is not enabled here.")
    page_url = _rev(request, "explore:box_type", args=[part_type_id])
    try:
        bearer = mint_for(request)
    except FnalLinkRequired:
        link = reverse("hwdb:link")
        return redirect(f"{link}?{urlencode({'next': page_url, 'reason': 'expired'})}")
    except FnalUnavailable:
        messages.error(request, FNAL_UNAVAILABLE)
        return redirect(_rev(request, "explore:home"))
    api = FnalDbApiClient(settings.HWDB_PROFILES[inst]["api"], bearer)

    try:
        record = api.get_component_type(part_type_id).get("data") or {}
    except requests.RequestException as e:
        messages.error(request, f"Couldn’t read the type from HWDB — {_hwdb_error_detail(e)}")
        return redirect(_rev(request, "explore:home"))
    connectors = dict(record.get("connectors") or {})

    if request.method == "POST" and (request.POST.get("action") or "extend") == "clone":
        return _clone_box_type(request, api, inst, part_type_id, record,
                               connectors, page_url)

    if request.method == "POST":
        prefix = (request.POST.get("prefix") or "").strip()
        child = (request.POST.get("child_type") or "").strip().upper()
        try:
            count = int(request.POST.get("count") or "0")
        except ValueError:
            count = 0
        if not re.fullmatch(r"[A-Za-z0-9 _.-]{1,40}", prefix):
            messages.error(request, "Position prefix must be 1–40 plain characters.")
        elif not 1 <= count <= 200:
            messages.error(request, "Count must be between 1 and 200.")
        elif not re.fullmatch(r"[A-Z]\d{11}", child):
            messages.error(request, f"“{child}” doesn’t look like a component-type id.")
        else:
            new_names = _next_position_names(connectors, prefix, count)
            payload = _type_patch_envelope(
                record, {**connectors, **{n: child for n in new_names}})
            try:
                body = api.patch_component_type(part_type_id, payload)
                ok, detail = body.get("status") == "OK", body.get("data")
            except requests.RequestException as e:
                ok, detail = False, _hwdb_error_detail(e)
            if ok:
                messages.success(
                    request, f"Added {count} position(s) {new_names[0]}…{new_names[-1]} "
                             f"accepting {child}.")
            else:
                messages.error(request, f"HWDB rejected the type update — {detail}")
        return redirect(page_url)

    # Names for the accepted child types, from the mirror where known.
    child_ids = sorted(set(connectors.values()))
    child_names = dict(HierarchyNode.for_instance(inst)
                       .filter(level=HierarchyNode.LEVEL_TYPE, part_type_id__in=child_ids)
                       .values_list("part_type_id", "name"))
    leaf = HierarchyNode.for_instance(inst).filter(
        level=HierarchyNode.LEVEL_TYPE, part_type_id=part_type_id).first()
    return render(request, "explore/box_type.html", {
        "active_nav": "shipments",
        "sidebar": navigation.sidebar_tree(inst, {}),
        "part_type_id": part_type_id,
        "type_name": (leaf.name if leaf else record.get("full_name")) or part_type_id,
        "positions": sorted(
            ({"name": pos, "child": ctid, "child_name": child_names.get(ctid, "")}
             for pos, ctid in connectors.items()), key=lambda p: p["name"]),
        "child_options": [{"id": c, "name": child_names.get(c, "")} for c in child_ids],
        "leaf_path": navigation.leaf_path_for(inst, part_type_id) if leaf else None,
    })


def _whoami_context(api) -> tuple[str, set, dict]:
    """(full name, role-id set, role-id→name map) for the calling user —
    best-effort; empty values just mean role-gated rows stay locked."""
    full_name, role_ids, role_names = "", set(), {}
    try:
        who = api.whoami().get("data") or {}
        full_name = who.get("full_name") or who.get("username") or ""
        role_ids = {r["id"] for r in who.get("roles") or []
                    if isinstance(r, dict) and r.get("id") is not None}
    except Exception as e:
        logger.warning("whoami failed: %s", e)
    try:
        role_names = {r["id"]: r["name"] for r in (api.get_roles().get("data") or [])
                      if isinstance(r, dict) and r.get("id") is not None}
    except Exception as e:
        logger.warning("roles fetch failed: %s", e)
    return full_name, role_ids, role_names


def _post_es(api, part_id, es_list, todos, comments) -> str | None:
    """Post the consolidated ES test record; returns an error string or None."""
    try:
        body = api.post_test(part_id, execsummary.es_test_payload(es_list, todos, comments))
    except requests.RequestException as e:
        return _hwdb_error_detail(e)
    return None if body.get("status") == "OK" else str(body.get("data") or body)


def _patch_item_flags(api, part_id, status_id, certified, uploaded, comment) -> None:
    """The Dashboard PATCHes the item's status + QA/QC flags with every
    signature; best-effort (the signature itself already landed)."""
    try:
        api.patch_component(part_id, {
            "part_id": part_id, "status": {"id": status_id},
            "certified_qaqc": certified, "qaqc_uploaded": uploaded,
            "comments": comment})
    except Exception as e:
        logger.warning("exec summary: item patch for %s failed: %s", part_id, e)


@login_not_required
@fnal_login_required
def explore_exec_summary_view(request, part_id):
    """The executive-summary page (issue #64) — the Dashboard's signing flow
    reimplemented: config-driven signees sign in rank order (each signature
    re-posts the consolidated "ES" test record and patches the item's
    status/flags), todos ride along, and once everyone has signed the
    summary PDF is generated (reportlab, DETAIL layout minus plots) and
    uploaded under the pre-shipping gate's naming convention. Without a
    config the page runs DEFAULT mode: one whoami signature, status/flag
    patch, and a minimal PDF. HWDB holds all state.

    POST actions: ``sign`` / ``default_sign`` / ``generate`` / ``reset`` /
    ``upload`` (a ready-made PDF, the #53 spike path).
    """
    inst = instance_of(request)
    part_url = _rev(request, "explore:part", args=[part_id])
    page_url = _rev(request, "explore:exec_summary", args=[part_id])
    ptid = part_id.rsplit("-", 1)[0]
    if inst not in settings.HWDB_WRITE_INSTANCES:
        return HttpResponseForbidden("Executive summaries are not enabled here.")

    try:
        bearer = mint_for(request)
    except FnalLinkRequired:
        link = reverse("hwdb:link")
        return redirect(f"{link}?{urlencode({'next': page_url, 'reason': 'expired'})}")
    except FnalUnavailable:
        messages.error(request, FNAL_UNAVAILABLE)
        return redirect(part_url)

    api = FnalDbApiClient(settings.HWDB_PROFILES[inst]["api"], bearer)
    cfg, cfg_msg = execsummary.load_config(api, ptid)
    # Any type can carry an executive summary, not just shipping boxes. Until
    # the hierarchy-chart "requires ES" marking exists, the mark is the type's
    # ES_{ptid}_*.json config in HWDB; shipping types additionally run
    # configless (DEFAULT mode), as before.
    if cfg is None and not curation.is_shipping_type(inst, ptid):
        return HttpResponseForbidden("Executive summaries are not enabled for this type.")

    if request.method == "POST":
        return _exec_summary_action(request, api, part_id, ptid, cfg,
                                    page_url)

    # ---- GET: assemble the signing page, all state live from HWDB ----
    images_rows = _safe_get_data(api.get_images, part_id)
    plot_blocks = (execsummary.resolve_plots(
        api, cfg, part_id, _children_of(api), images_rows)
        if cfg and cfg["plots"] else [])
    es_list, saved_todos = execsummary.fetch_es_state(api, part_id)
    full_name, role_ids, role_names = _whoami_context(api)
    try:
        comp = api.get_component(part_id).get("data") or {}
    except requests.RequestException:
        comp = {}
    status_name = (comp.get("status") or {}).get("name") if isinstance(comp.get("status"), dict) else comp.get("status")
    summaries = [i for i in images_rows
                 if (i.get("image_name") or "").lower().startswith(
                     f"executivesummary_{part_id.lower()}_")]
    summaries.sort(key=lambda i: i.get("created") or "", reverse=True)
    for s in summaries:
        # Short label for the selection list — the filenames all share the
        # long ExecutiveSummary_{pid}_ prefix, so show the posted time.
        s["label"] = ((s.get("created") or "")[:16].replace("T", " ")
                      or s.get("image_name"))
    return render(request, "explore/exec_summary.html", {
        "active_nav": "shipments",
        "sidebar": navigation.sidebar_tree(inst, {}),
        "part_id": part_id,
        "cfg": cfg, "cfg_msg": cfg_msg,
        "signing": (execsummary.compute_status(cfg, es_list, role_ids, role_names)
                    if cfg else None),
        "todos_checked": (saved_todos or {}).get("checked") or [],
        "full_name": full_name,
        "status_options": execsummary.STATUS_OPTIONS,
        "status_current_id": execsummary.STATUS_ID_BY_LABEL.get(status_name),
        "certified": bool(comp.get("certified_qaqc")),
        "uploaded": bool(comp.get("qaqc_uploaded")),
        "summaries": summaries,
        "plot_blocks": plot_blocks,
        "ptid": ptid,
    })


def _children_of(api):
    """Manifest-row lookup for ES plot sub_part_id addressing."""
    return lambda pid: current_manifest(_safe_get_data(api.get_subcomponents, pid))


@login_not_required
@fnal_login_required
def explore_es_config_view(request, part_type_id):
    """Structured editor for a type's ES config: consortium/description,
    todos, signees, references, plots, plus arbitrary extra fields. Saving
    posts a NEW ``ES_{ptid}_{ts}.json`` onto the type (newest wins — HWDB
    keeps every version). A type with no config starts from the template;
    saving one is what marks the type as carrying an executive summary."""
    inst = instance_of(request)
    page_url = _rev(request, "explore:es_config", args=[part_type_id])
    if inst not in settings.HWDB_WRITE_INSTANCES:
        return HttpResponseForbidden("ES configs can only be edited on the dev instance.")

    try:
        bearer = mint_for(request)
    except FnalLinkRequired:
        link = reverse("hwdb:link")
        return redirect(f"{link}?{urlencode({'next': page_url, 'reason': 'expired'})}")
    except FnalUnavailable:
        messages.error(request, FNAL_UNAVAILABLE)
        return redirect(_rev(request, "explore:home"))
    api = FnalDbApiClient(settings.HWDB_PROFILES[inst]["api"], bearer)

    next_url = request.POST.get("next") or request.GET.get("next") or ""
    back = f"{page_url}?{urlencode({'next': next_url})}" if next_url else page_url

    if request.method == "POST":
        try:
            cfg = json.loads(request.POST.get("config_json") or "")
        except ValueError as e:
            messages.error(request, f"The config isn’t valid JSON — {e}")
            return redirect(back)
        if not isinstance(cfg, dict):
            messages.error(request, "The config must be a JSON object.")
            return redirect(back)
        # Required field, auto-derivable — fill it in rather than reject.
        cfg.setdefault("component_type_id", part_type_id)
        name = f"ES_{part_type_id}_{timezone.now():{execsummary.FILENAME_TS_FMT}}.json"
        try:
            body = api.post_component_type_image(
                part_type_id, io.BytesIO(json.dumps(cfg, indent=2).encode()), name,
                comments="Executive Summary config (Explorer editor)")
        except requests.RequestException as e:
            messages.error(request, f"HWDB rejected the config — {_hwdb_error_detail(e)}")
            return redirect(back)
        if body.get("status") != "OK":
            messages.error(request, f"HWDB rejected the config — {body.get('data') or body}")
            return redirect(back)
        messages.success(request, f"Config posted as {name} — it now applies to "
                                  f"every {part_type_id} item.")
        return redirect(next_url or back)

    raw, current_name = execsummary.load_raw_config(api, part_type_id)
    return render(request, "explore/es_config.html", {
        "sidebar": navigation.sidebar_tree(inst, {}),
        "part_type_id": part_type_id,
        "current_name": current_name,
        "initial": (raw if raw is not None else
                    {**execsummary.CONFIG_TEMPLATE, "component_type_id": part_type_id}),
        "is_new": raw is None,
        "next": next_url,
    })


def _exec_summary_action(request, api, part_id, ptid, cfg, page_url):
    """Dispatch one executive-summary POST action; always lands back on the
    page with flash messages."""
    action = request.POST.get("action") or ("sign" if request.POST.get("sign") else "")
    inst = instance_of(request)

    def _form_flags():
        try:
            sid = int(request.POST.get("status_id") or 0)
        except ValueError:
            sid = 0
        return (sid, bool(request.POST.get("certified")),
                bool(request.POST.get("uploaded")))

    if action == "upload":  # ready-made PDF (the #53 spike path)
        pdf = request.FILES.get("pdf")
        if pdf is None or not pdf.name.lower().endswith(".pdf"):
            messages.error(request, "Pick a PDF file to upload.")
            return redirect(page_url)
        if pdf.size > 25 * 1024 * 1024:
            messages.error(request, "That PDF is over 25 MB — too large for a summary.")
            return redirect(page_url)
        name = f"ExecutiveSummary_{part_id}_{timezone.now():{execsummary.FILENAME_TS_FMT}}.pdf"
        err = _upload_summary_pdf(api, part_id, pdf, name)
        if err:
            messages.error(request, f"HWDB rejected the summary — {err}")
        else:
            messages.success(request, f"Executive summary posted as {name}.")
        return redirect(page_url)

    if action == "default_sign":  # no-config mode: sign + patch + PDF, one shot
        full_name, _ids, _names = _whoami_context(api)
        sid, certified, uploaded = _form_flags()
        missing = [label for ok, label in ((certified, "“Certified QA/QC”"),
                                           (uploaded, "“All QA/QC Uploaded”")) if not ok]
        if missing:
            messages.error(request, "Both QA/QC flags must be confirmed before "
                                    "signing — still unchecked: " + ", ".join(missing) + ".")
            return redirect(page_url)
        ts = timezone.localtime().strftime(execsummary.TIMESTAMP_FMT)
        comments = (request.POST.get("comments") or "").strip() or f"signed by {full_name}"
        _patch_item_flags(api, part_id, sid, certified, uploaded, comments)
        signinfo = {"signature": full_name, "comments": comments, "timestamp": ts,
                    "status_label": execsummary.STATUS_LABEL_BY_ID.get(sid, "Unknown"),
                    "certified_flag": certified, "uploaded_flag": uploaded}
        manifest = current_manifest(_safe_get_data(api.get_subcomponents, part_id))
        pdf_bytes = execsummary.build_default_pdf(
            part_id, signinfo, execsummary.subcomponent_lines(manifest))
        name = f"ExecutiveSummary_{part_id}_{timezone.now():{execsummary.FILENAME_TS_FMT}}.pdf"
        err = _upload_summary_pdf(api, part_id, io.BytesIO(pdf_bytes), name)
        if err:
            messages.error(request, f"Summary PDF upload failed — {err}")
        else:
            messages.success(request, f"Signed and posted {name}.")
        return redirect(page_url)

    if cfg is None:
        messages.error(request, "This action needs an ES config on the type.")
        return redirect(page_url)

    if action == "upload_plot":  # an image for one configured plot slot
        try:
            idx = int(request.POST.get("plot_index") or "")
        except ValueError:
            idx = -1
        plot = next((p for p in cfg["plots"] if p["index"] == idx), None)
        img = request.FILES.get("plot_image")
        ext = img.name.rsplit(".", 1)[-1].lower() if img and "." in img.name else ""
        if plot is None or img is None or ext not in ("png", "jpg", "jpeg", "gif"):
            messages.error(request, "Pick a PNG/JPG/GIF image for a configured plot.")
            return redirect(page_url)
        if img.size > 10 * 1024 * 1024:
            messages.error(request, "That image is over 10 MB — too large for a plot.")
            return redirect(page_url)
        name = (execsummary.plot_upload_prefix(part_id, plot)
                + f"{timezone.now():{execsummary.FILENAME_TS_FMT}}.{ext}")
        try:
            body = api.post_component_image(
                part_id, img, name, comments=f"ES plot upload: {plot['title']}")
        except requests.RequestException as e:
            messages.error(request, f"HWDB rejected the plot image — {_hwdb_error_detail(e)}")
            return redirect(page_url)
        if body.get("status") != "OK":
            messages.error(request, f"HWDB rejected the plot image — {body.get('data') or body}")
            return redirect(page_url)
        messages.success(request, f"Plot image posted as {name} — it now fills "
                                  f"the “{plot['title']}” slot.")
        return redirect(page_url)

    es_list, saved_todos = execsummary.fetch_es_state(api, part_id)
    full_name, role_ids, role_names = _whoami_context(api)
    checked = []
    for v in request.POST.getlist("todo"):
        try:
            checked.append(int(v))
        except ValueError:
            pass
    todos = execsummary.todos_payload(cfg, checked)

    if action == "sign":
        name = request.POST.get("sign") or ""
        status = execsummary.compute_status(cfg, es_list, role_ids)
        row = next((r for r in status["rows"] if r["name"] == name), None)
        if row is None:
            messages.error(request, f"“{name}” is not a configured signee.")
            return redirect(page_url)
        if not row["allowed"]:
            why = ("their signing turn hasn’t come yet" if row["role_ok"]
                   else "you don’t hold the required role")
            messages.error(request, f"“{name}” can’t sign now — {why}.")
            return redirect(page_url)
        signature = (request.POST.get(f"sig:{name}") or "").strip()
        if not signature:
            messages.error(request, f"Type the signature text for “{name}”.")
            return redirect(page_url)
        # Nothing gets signed until every QC check and both QA/QC flags are
        # ticked — the confirmations are the point of the summary.
        sid, certified, uploaded = _form_flags()
        missing = []
        n_checks = len(cfg["todos"]["check_list"])
        if len(todos["checked"]) < n_checks:
            missing.append(f"{n_checks - len(todos['checked'])} QC check(s)")
        if not certified:
            missing.append("“Consortium Certified QA/QC”")
        if not uploaded:
            missing.append("“All QA/QC Uploaded”")
        if missing:
            messages.error(request, "Everything must be confirmed before signing — "
                                    "still unchecked: " + ", ".join(missing) + ".")
            return redirect(page_url)
        ts = timezone.localtime().strftime(execsummary.TIMESTAMP_FMT)
        merged = execsummary.merge_es_entry(
            es_list, name, signature, row["rank"], ts,
            request.POST.get(f"com:{name}") or "")
        err = _post_es(api, part_id, merged, todos, f"ES signature updated: {name}")
        if err:
            messages.error(request, f"HWDB rejected the signature — {err}")
            return redirect(page_url)
        _patch_item_flags(
            api, part_id, sid, certified, uploaded,
            f"[ExecSum] signature '{name}' uploaded, also Status, QAQC Certified, "
            f"and Uploaded flags updated.")
        messages.success(request, f"Signature for “{name}” posted.")
        return redirect(page_url)

    if action == "reset":
        status = execsummary.compute_status(cfg, es_list, role_ids)
        if not status["reset_allowed"]:
            messages.error(request, "RESET needs the final approver’s role.")
            return redirect(page_url)
        err = _post_es(api, part_id, [], saved_todos,
                       "ES RESET requested (cleared signatures)")
        if err:
            messages.error(request, f"HWDB rejected the reset — {err}")
        else:
            messages.success(request, "Signatures cleared.")
        return redirect(page_url)

    if action == "generate":
        status = execsummary.compute_status(cfg, es_list, role_ids, role_names)
        if not status["all_signed"]:
            messages.error(request, "Every configured signee must sign before generating.")
            return redirect(page_url)
        try:
            comp = api.get_component(part_id).get("data") or {}
        except requests.RequestException:
            comp = {}
        status_name = ((comp.get("status") or {}).get("name")
                       if isinstance(comp.get("status"), dict) else comp.get("status"))
        manifest = current_manifest(_safe_get_data(api.get_subcomponents, part_id))
        leaf = HierarchyNode.for_instance(inst).filter(
            level=HierarchyNode.LEVEL_TYPE, part_type_id=ptid).first()
        plot_blocks = []
        if cfg["plots"]:
            plot_blocks = execsummary.resolve_plots(
                api, cfg, part_id, _children_of(api),
                _safe_get_data(api.get_images, part_id))
            execsummary.download_plot_images(api, plot_blocks)
        pdf_bytes = execsummary.build_detail_pdf(part_id, {
            "type_name": leaf.name if leaf else "",
            "description": cfg["test_description"],
            "todos": {**cfg["todos"], "checked": ((saved_todos or {}).get("checked") or [])},
            "signee_rows": status["rows"],
            "status_label": status_name or "Unknown",
            "certified_flag": bool(comp.get("certified_qaqc")),
            "uploaded_flag": bool(comp.get("qaqc_uploaded")),
            "references": cfg["references"],
            "subcomponents": execsummary.subcomponent_lines(manifest),
            "plot_blocks": plot_blocks,
        })
        name = f"ExecutiveSummary_{part_id}_{timezone.now():{execsummary.FILENAME_TS_FMT}}.pdf"
        err = _upload_summary_pdf(api, part_id, io.BytesIO(pdf_bytes), name)
        if err:
            messages.error(request, f"Summary PDF upload failed — {err}")
        else:
            messages.success(request, f"Summary generated and posted as {name}.")
        return redirect(page_url)

    messages.error(request, "Unknown action.")
    return redirect(page_url)


def _safe_get_data(fn, *args) -> list:
    try:
        return fn(*args).get("data") or []
    except Exception:
        return []


def _upload_summary_pdf(api, part_id, fileobj, name) -> str | None:
    """Upload a summary PDF under the gate convention; error string or None."""
    ts = timezone.localtime().strftime(execsummary.TIMESTAMP_FMT)
    try:
        body = api.post_component_image(
            part_id, fileobj, name,
            comments=f"Executive Summary PDF uploaded by HWDB Explorer ({ts})")
    except requests.RequestException as e:
        logger.warning("exec summary upload for %s failed: %s", part_id, e)
        return _hwdb_error_detail(e)
    return None if body.get("status") == "OK" else str(body.get("data") or body)


def _preship_gate(api, part_id) -> dict:
    """The Dashboard's pre-shipping gate status: QC flags + status id ∈
    {120, 140} + a gate-named executive summary on the box's images."""
    item = {}
    try:
        item = api.get_component(part_id).get("data") or {}
    except requests.RequestException as e:
        logger.warning("preship gate: item fetch failed: %s", e)
    status = item.get("status") or {}
    status_id = status.get("id") if isinstance(status, dict) else None
    certified = bool(item.get("certified_qaqc"))
    uploaded = bool(item.get("qaqc_uploaded"))
    summary, uploader = "", ""
    try:
        prefix = f"executivesummary_{part_id.lower()}_"
        matches = [i for i in (api.get_images(part_id).get("data") or [])
                   if (i.get("image_name") or "").lower().startswith(prefix)
                   and (i.get("image_name") or "").lower().endswith(".pdf")]
        if matches:
            newest = max(matches, key=lambda i: i.get("created") or "")
            summary = newest.get("image_name") or ""
            creator = newest.get("creator") or {}
            uploader = creator.get("name") if isinstance(creator, dict) else str(creator or "")
    except Exception as e:
        logger.warning("preship gate: images fetch failed: %s", e)
    return {
        "status_id": status_id,
        "status_name": (status.get("name") if isinstance(status, dict) else status) or "",
        "certified": certified, "uploaded": uploaded,
        "qaqc_ready": certified and uploaded and status_id in {120, 140},
        "summary_name": summary, "summary_uploader": uploader or "",
    }


@login_not_required
@fnal_login_required
def explore_preship_view(request, part_id):
    """The Pre-Shipping checklist (issue #65) — the Dashboard's workflow,
    scene for scene, with state in the shared DB (``BoxChecklist``) so any
    teammate can resume. Scenes 1–7 collect and validate; scene 8 uploads
    the shipping-label PDF and PATCHes the ``Pre-Shipping Checklist`` +
    ``SubPIDs`` spec keys byte-for-byte like the Dashboard. ``?csv=1``
    downloads the logistics CSV.
    """
    inst = instance_of(request)
    part_url = _rev(request, "explore:part", args=[part_id])
    page_url = _rev(request, "explore:preship", args=[part_id])
    ptid = part_id.rsplit("-", 1)[0]
    if inst not in settings.HWDB_WRITE_INSTANCES or not curation.is_shipping_type(inst, ptid):
        return HttpResponseForbidden("Checklists are not enabled here.")

    try:
        bearer = mint_for(request)
    except FnalLinkRequired:
        link = reverse("hwdb:link")
        return redirect(f"{link}?{urlencode({'next': page_url, 'reason': 'expired'})}")
    except FnalUnavailable:
        messages.error(request, FNAL_UNAVAILABLE)
        return redirect(part_url)
    api = FnalDbApiClient(settings.HWDB_PROFILES[inst]["api"], bearer)

    cl = BoxChecklist.for_instance(inst).filter(
        part_id=part_id, workflow="preshipping").first()

    if request.method == "POST":
        action = request.POST.get("action") or "advance"
        if action == "start":
            route = request.POST.get("route") or "confirm_surf"
            if route not in dict(BoxChecklist.ROUTES):
                route = "confirm_surf"
            if cl:
                cl.delete()
            BoxChecklist.objects.create(
                instance=inst, part_id=part_id, workflow="preshipping",
                route=route, created_by=request.user.get_username())
            messages.success(request, "Pre-shipping checklist started.")
            return redirect(page_url)
        if cl is None:
            messages.error(request, "Start the checklist first.")
            return redirect(page_url)
        if action == "back":
            cl.current_scene = max(1, cl.current_scene - 1)
            cl.save(update_fields=["current_scene", "updated_at"])
            return redirect(page_url)

        scene = cl.current_scene
        cleaned, err = checklists.clean_scene(scene, cl.is_surf, request.POST)
        if err:
            messages.error(request, err)
            return redirect(page_url)
        if scene == 1:  # server-side gate re-check, like the Dashboard
            gate = _preship_gate(api, part_id)
            if not (gate["qaqc_ready"] and gate["summary_name"]):
                messages.error(request,
                               "Gate not passed: the box needs QC flags + passing "
                               "status and an executive summary.")
                return redirect(page_url)
            cleaned.update(gate)
        cl.state[checklists.scene_key(scene)] = {
            **cl.state.get(checklists.scene_key(scene), {}), **cleaned}

        if scene == checklists.N_SCENES:  # final writes
            leaf = HierarchyNode.for_instance(inst).filter(
                level=HierarchyNode.LEVEL_TYPE, part_type_id=ptid).first()
            manifest = current_manifest(_safe_get_data(api.get_subcomponents, part_id))
            info = checklists.part_info(leaf, part_id, manifest)
            qr = None
            try:
                qr = api.get_qrcode_response(part_id).content
            except Exception as e:
                logger.warning("preship: QR fetch failed: %s", e)
            label = checklists.build_label_pdf(
                part_id, info["part_type_name"],
                "Development HWDB" if inst == "dev" else "Production HWDB", qr)
            try:
                image_id, err = checklists.execute_final_patch(api, cl, info, label)
            except requests.RequestException as e:
                messages.error(request, f"HWDB rejected the update — {_hwdb_error_detail(e)}")
                return redirect(page_url)
            if err:
                messages.error(request, f"HWDB rejected the update — {err}")
                return redirect(page_url)
            cl.state[checklists.scene_key(scene)].update(
                {"image_id": image_id, "patched": True})
            cl.completed_at = timezone.now()
            cl.save()
            _refresh_box_quietly(api, inst, ptid, part_id)
            messages.success(request,
                             "Pre-shipping checklist written to HWDB (shipping sheet "
                             "uploaded, checklist patched).")
            return redirect(page_url)

        cl.current_scene = scene + 1
        cl.save()
        return redirect(page_url)

    # ---- GET ----
    if cl and request.GET.get("csv"):
        leaf = HierarchyNode.for_instance(inst).filter(
            level=HierarchyNode.LEVEL_TYPE, part_type_id=ptid).first()
        manifest = current_manifest(_safe_get_data(api.get_subcomponents, part_id))
        filename, text = checklists.build_csv(
            cl, checklists.part_info(leaf, part_id, manifest))
        resp = HttpResponse(text, content_type="text/csv")
        resp["Content-Disposition"] = f'attachment; filename="{filename}"'
        return resp

    ctx = {
        "active_nav": "shipments",
        "sidebar": navigation.sidebar_tree(inst, {}),
        "part_id": part_id,
        "cl": cl,
        "routes": BoxChecklist.ROUTES,
        "n_scenes": checklists.N_SCENES,
    }
    if cl and not cl.completed_at:
        scene = cl.current_scene
        ctx.update({"scene": scene, "scene_title": checklists.scene_title(scene),
                    "saved": cl.state.get(checklists.scene_key(scene), {})})
        if scene == 1:
            ctx["gate"] = _preship_gate(api, part_id)
        if scene == 2:
            # Prefill the QA rep from the summary's uploader, like the Dashboard.
            ctx["qa_rep_default"] = (ctx.get("saved", {}).get("qa_rep_name")
                                     or cl.state.get("PreShipping1", {}).get("summary_uploader", ""))
        if scene == 6:
            leaf = HierarchyNode.for_instance(inst).filter(
                level=HierarchyNode.LEVEL_TYPE, part_type_id=ptid).first()
            manifest = current_manifest(_safe_get_data(api.get_subcomponents, part_id))
            filename, _text = checklists.build_csv(
                cl, checklists.part_info(leaf, part_id, manifest))
            try:
                who = api.whoami().get("data") or {}
            except Exception:
                who = {}
            ctx["csv_filename"] = filename
            ctx["email_html"] = checklists.email_html(
                cl, filename, who.get("full_name") or who.get("username") or "",
                who.get("email") or "")
        if scene == checklists.N_SCENES:
            ctx["review"] = [(checklists.scene_title(i),
                              cl.state.get(checklists.scene_key(i), {}))
                             for i in range(2, checklists.N_SCENES)]
    return render(request, "explore/preship.html", ctx)


@login_not_required
@fnal_login_required
def explore_shipping_view(request, part_id):
    """The Shipping checklist (issue #66) — the Dashboard's flow on the
    #65 engine: contents confirm, document uploads (BoL / Proforma /
    approval posted straight onto the box with the Dashboard's comment
    strings), the final-approval email, the ``Shipping Checklist`` spec
    patch (SURF route), and the In-Transit location post. ``?csv=1``
    downloads the wrap-up CSV.
    """
    inst = instance_of(request)
    part_url = _rev(request, "explore:part", args=[part_id])
    page_url = _rev(request, "explore:shipping", args=[part_id])
    ptid = part_id.rsplit("-", 1)[0]
    if inst not in settings.HWDB_WRITE_INSTANCES or not curation.is_shipping_type(inst, ptid):
        return HttpResponseForbidden("Checklists are not enabled here.")
    try:
        bearer = mint_for(request)
    except FnalLinkRequired:
        link = reverse("hwdb:link")
        return redirect(f"{link}?{urlencode({'next': page_url, 'reason': 'expired'})}")
    except FnalUnavailable:
        messages.error(request, FNAL_UNAVAILABLE)
        return redirect(part_url)
    api = FnalDbApiClient(settings.HWDB_PROFILES[inst]["api"], bearer)

    cl = BoxChecklist.for_instance(inst).filter(
        part_id=part_id, workflow="shipping").first()
    preship = BoxChecklist.for_instance(inst).filter(
        part_id=part_id, workflow="preshipping").first()

    def _info():
        leaf = HierarchyNode.for_instance(inst).filter(
            level=HierarchyNode.LEVEL_TYPE, part_type_id=ptid).first()
        manifest = current_manifest(_safe_get_data(api.get_subcomponents, part_id))
        return checklists.part_info(leaf, part_id, manifest)

    def _poc():
        try:
            spec = _spec_data(api.get_component(part_id))
        except requests.RequestException:
            spec = None
        return checklists.poc_from(preship.state if preship else None, spec)

    if request.method == "POST":
        action = request.POST.get("action") or "advance"
        if action == "start":
            route = request.POST.get("route") or (preship.route if preship else "confirm_surf")
            if route not in dict(BoxChecklist.ROUTES):
                route = "confirm_surf"
            if cl:
                cl.delete()
            BoxChecklist.objects.create(
                instance=inst, part_id=part_id, workflow="shipping",
                route=route, created_by=request.user.get_username())
            messages.success(request, "Shipping checklist started.")
            return redirect(page_url)
        if cl is None:
            messages.error(request, "Start the checklist first.")
            return redirect(page_url)
        if action == "back":
            cl.current_scene = max(1, cl.current_scene - 1)
            cl.save(update_fields=["current_scene", "updated_at"])
            return redirect(page_url)

        scene = cl.current_scene
        key = checklists.shipping_scene_key(scene)
        merged = dict(cl.state.get(key, {}))
        # Uploaded documents post straight onto the box (the Dashboard holds
        # them locally until scene 4; we have no local disk, and images are
        # append-only either way). Image ids land in the scene state.
        uploads = {2: [("bol_file", "shipping-bol", "shipping_bol", "bol_info"),
                       ("proforma_file", "shipping-proforma", "shipping_proforma", "proforma_info")],
                   4: [("approval_file", "shipping-final-approval",
                        "shipping_final_approval", "approval_info")]}
        for field, stem, comment, state_key in uploads.get(scene, []):
            f = request.FILES.get(field)
            if f is None:
                continue
            name = checklists.artifact_filename(part_id, stem, f.name)
            try:
                body = api.post_component_image(part_id, f, name, comments=comment)
            except requests.RequestException as e:
                messages.error(request, f"{field} upload failed — {_hwdb_error_detail(e)}")
                return redirect(page_url)
            if body.get("status") != "OK":
                messages.error(request, f"{field} upload failed — {body.get('data') or body}")
                return redirect(page_url)
            merged[state_key] = {"filename": name, "image_id": body.get("image_id")}

        try:
            spec = _spec_data(api.get_component(part_id))
        except requests.RequestException:
            spec = None
        ship_type = checklists.shipping_service_type(spec)
        cleaned, err = checklists.clean_shipping_scene(
            scene, cl.is_surf, ship_type, request.POST, merged)
        merged.update(cleaned)
        cl.state[key] = merged
        cl.save()  # keep uploads/fields even when validation fails
        if err:
            messages.error(request, err)
            return redirect(page_url)

        if scene == 4 and cl.is_surf:  # the Shipping Checklist patch
            poc_name, poc_email = _poc()
            try:
                perr = checklists.patch_shipping(api, cl, _info(), poc_name, poc_email)
            except requests.RequestException as e:
                perr = _hwdb_error_detail(e)
            if perr:
                messages.error(request, f"Shipping HWDB update failed — {perr}")
                return redirect(page_url)
            messages.success(request, "Shipping Checklist patched into HWDB.")
        if scene == 5:  # mark In-Transit
            try:
                body = api.post_location(part_id, {
                    "location": {"id": 0},
                    "arrived": merged.get("shipment_time"),
                    "comments": merged.get("comments", "")})
            except requests.RequestException as e:
                messages.error(request, f"Location update failed — {_hwdb_error_detail(e)}")
                return redirect(page_url)
            if body.get("status") != "OK":
                messages.error(request, f"Location update failed — {body.get('data') or body}")
                return redirect(page_url)
            _refresh_box_quietly(api, inst, ptid, part_id)
            messages.success(request, "Box marked In-Transit in HWDB.")

        if scene == checklists.N_SHIPPING_SCENES:
            cl.completed_at = timezone.now()
            cl.save(update_fields=["completed_at", "updated_at"])
            messages.success(request, "Shipping checklist complete.")
        else:
            cl.current_scene = scene + 1
            cl.save(update_fields=["current_scene", "updated_at"])
        return redirect(page_url)

    # ---- GET ----
    if cl and request.GET.get("csv"):
        poc_name, poc_email = _poc()
        filename, text = checklists.build_shipping_csv(cl, _info(), poc_name, poc_email)
        resp = HttpResponse(text, content_type="text/csv")
        resp["Content-Disposition"] = f'attachment; filename="{filename}"'
        return resp

    ctx = {
        "active_nav": "shipments",
        "sidebar": navigation.sidebar_tree(inst, {}),
        "part_id": part_id,
        "cl": cl,
        "preship": preship,
        "routes": BoxChecklist.ROUTES,
        "n_scenes": checklists.N_SHIPPING_SCENES,
    }
    if cl and not cl.completed_at:
        scene = cl.current_scene
        ctx.update({"scene": scene,
                    "scene_title": checklists.shipping_scene_title(scene),
                    "saved": cl.state.get(checklists.shipping_scene_key(scene), {})})
        if scene == 2:
            try:
                spec = _spec_data(api.get_component(part_id))
            except requests.RequestException:
                spec = None
            ctx["ship_type"] = checklists.shipping_service_type(spec)
        if scene == 3:
            poc_name, poc_email = _poc()
            try:
                who = api.whoami().get("data") or {}
            except Exception:
                who = {}
            ctx["email_html"] = checklists.shipping_email_html(
                part_id, poc_name, poc_email,
                who.get("full_name") or who.get("username") or "",
                who.get("email") or "")
    return render(request, "explore/shipping.html", ctx)


@login_not_required
@fnal_login_required
def explore_receiving_view(request, part_id):
    """The Receiving checklist (issue #67) — the Dashboard's flow on the
    #65 engine: contents confirm, then the arrival-location update that
    posts the location on the box AND every subcomponent and detaches all
    functional positions ("opens the box"; the transshipping route keeps
    contents linked), then the arrival email to the POC. Independent of the
    Explorer's own shipping run so a Dashboard-shipped box is receivable.
    """
    inst = instance_of(request)
    part_url = _rev(request, "explore:part", args=[part_id])
    page_url = _rev(request, "explore:receiving", args=[part_id])
    ptid = part_id.rsplit("-", 1)[0]
    if inst not in settings.HWDB_WRITE_INSTANCES or not curation.is_shipping_type(inst, ptid):
        return HttpResponseForbidden("Checklists are not enabled here.")
    try:
        bearer = mint_for(request)
    except FnalLinkRequired:
        link = reverse("hwdb:link")
        return redirect(f"{link}?{urlencode({'next': page_url, 'reason': 'expired'})}")
    except FnalUnavailable:
        messages.error(request, FNAL_UNAVAILABLE)
        return redirect(part_url)
    api = FnalDbApiClient(settings.HWDB_PROFILES[inst]["api"], bearer)

    cl = BoxChecklist.for_instance(inst).filter(
        part_id=part_id, workflow="receiving").first()
    preship = BoxChecklist.for_instance(inst).filter(
        part_id=part_id, workflow="preshipping").first()
    shipping = BoxChecklist.for_instance(inst).filter(
        part_id=part_id, workflow="shipping").first()

    def _manifest():
        return current_manifest(_safe_get_data(api.get_subcomponents, part_id))

    if request.method == "POST":
        action = request.POST.get("action") or "advance"
        if action == "start":
            route = (request.POST.get("route")
                     or (shipping.route if shipping else "")
                     or (preship.route if preship else "confirm_surf"))
            if route not in dict(BoxChecklist.ROUTES):
                route = "confirm_surf"
            if cl:
                cl.delete()
            BoxChecklist.objects.create(
                instance=inst, part_id=part_id, workflow="receiving",
                route=route, created_by=request.user.get_username())
            messages.success(request, "Receiving checklist started.")
            return redirect(page_url)
        if cl is None:
            messages.error(request, "Start the checklist first.")
            return redirect(page_url)
        if action == "back":
            cl.current_scene = max(1, cl.current_scene - 1)
            cl.save(update_fields=["current_scene", "updated_at"])
            return redirect(page_url)

        scene = cl.current_scene
        key = checklists.receiving_scene_key(scene)
        cleaned, err = checklists.clean_receiving_scene(scene, request.POST)
        if scene == 2 and not err:
            # Dashboard state shape: the location as institution id + name
            # (the name feeds the scene-3 arrival email).
            names = {str(o["id"]): o["name"] for o in _institution_options(api)}
            cleaned = {"location": {"institution_id": int(cleaned["location_id"]),
                                    "institution_name": names.get(cleaned["location_id"], "")},
                       "arrived": cleaned["arrived"], "comments": cleaned["comments"],
                       "affirm_update": True}
        cl.state[key] = {**cl.state.get(key, {}), **cleaned}
        cl.save()
        if err:
            messages.error(request, err)
            return redirect(page_url)

        if scene == 2:  # the writes: locations fan-out + detach
            manifest = _manifest()
            try:
                rerr = checklists.receive_box(api, cl, manifest)
            except requests.RequestException as e:
                rerr = _hwdb_error_detail(e)
            if rerr:
                messages.error(request, f"Receiving HWDB update failed — {rerr}")
                return redirect(page_url)
            _refresh_box_quietly(api, inst, ptid, part_id)
            if cl.route == "confirm_transshipping":
                messages.success(
                    request, "Arrival location posted; contents stay linked (transshipping).")
            else:
                messages.success(
                    request, f"Arrival location posted for the box and {len(manifest)} "
                             "item(s); all contents detached.")

        if scene == checklists.N_RECEIVING_SCENES:
            cl.completed_at = timezone.now()
            cl.save(update_fields=["completed_at", "updated_at"])
            messages.success(request, "Receiving checklist complete.")
        else:
            cl.current_scene = scene + 1
            cl.save(update_fields=["current_scene", "updated_at"])
        return redirect(page_url)

    # ---- GET ----
    ctx = {
        "active_nav": "shipments",
        "sidebar": navigation.sidebar_tree(inst, {}),
        "part_id": part_id,
        "cl": cl,
        "shipping": shipping,
        "routes": BoxChecklist.ROUTES,
        "n_scenes": checklists.N_RECEIVING_SCENES,
    }
    if cl and not cl.completed_at:
        scene = cl.current_scene
        ctx.update({"scene": scene,
                    "scene_title": checklists.receiving_scene_title(scene),
                    "saved": cl.state.get(checklists.receiving_scene_key(scene), {})})
        if scene == 1:
            ctx["n_items"] = len(_manifest())
        if scene == 2:
            ctx["institutions"] = _institution_options(api)
            ctx["arrived_default"] = timezone.localtime().strftime("%Y-%m-%dT%H:%M")
        if scene == 3:
            try:
                spec = _spec_data(api.get_component(part_id))
            except requests.RequestException:
                spec = None
            poc_name, poc_email = checklists.poc_from(
                preship.state if preship else None, spec)
            try:
                who = api.whoami().get("data") or {}
            except Exception:
                who = {}
            r2 = cl.state.get("Receiving2", {})
            ctx["email_html"] = checklists.receiving_email_html(
                part_id, poc_name, poc_email,
                who.get("full_name") or who.get("username") or "",
                who.get("email") or "",
                (r2.get("location") or {}).get("institution_name", ""),
                r2.get("arrived") or "")
    return render(request, "explore/receiving.html", ctx)


@login_not_required
@fnal_login_required
def explore_assembly_view(request, part_id):
    """One level of a part's assembly tree as JSON — a node's direct children
    with their live QC flags (ADR-0015). Lazy-load target for deeper expansion
    on the part page; the first level is rendered server-side. FNAL-gated."""
    try:
        bearer = mint_for(request)
    except FnalLinkRequired:
        return JsonResponse({"error": "fnal_link", "link": reverse("hwdb:link")}, status=409)
    except FnalUnavailable:
        return JsonResponse({"error": "unavailable"}, status=502)

    api = FnalDbApiClient(settings.HWDB_PROFILES[instance_of(request)]["api"], bearer)
    try:
        children = assembly_children(api, part_id)
    except Exception:
        logger.exception("explore_assembly_view(%s) crashed", part_id)
        return JsonResponse({"error": "fetch_failed"}, status=502)

    for c in children:
        c["url"] = (_rev(request, "explore:part", args=[c["part_id"]])
                    if c.get("part_id") else None)
    return JsonResponse({"children": children})


# A full part id, e.g. ``D08100100003-00226`` — type-id segment then a sequence.
_PID_RE = re.compile(r"^[A-Za-z0-9]{8,}-\w+$")


@login_not_required
@fnal_login_required
def explore_search_view(request):
    """Instant search over the local mirror (ADR-0014): jump to a component
    type's leaf page or a part's detail page by name / id. Mirror-only, so no
    FNAL needed; live cross-field 'advanced' search is a later addition."""
    return render(request, "explore/search.html",
                  {"active_nav": "search", "q": request.GET.get("q", ""),
                   "sidebar": navigation.sidebar_tree(instance_of(request), {})})


@login_not_required
@fnal_login_required
def explore_docs_view(request):
    """External DUNE HWDB documentation links (training site, API reference,
    the HWDB web UIs, consortium references). Static curated content — the
    link list lives in the template; API-doc links follow the instance."""
    inst = instance_of(request)
    return render(request, "explore/docs.html", {
        "active_nav": "docs",
        "sidebar": navigation.sidebar_tree(inst, {}),
        "instance": inst,
        "hwdb_ui_base": settings.HWDB_PROFILES[inst]["ui"],
        "hwdb_ui_prod": settings.HWDB_PROFILES["prod"]["ui"],
        "hwdb_ui_dev": settings.HWDB_PROFILES["dev"]["ui"],
    })


@login_not_required
@fnal_login_required
def explore_search_api_view(request):
    """JSON results for the instant search box — component types + mirrored
    parts matching ``q`` (substring, case-insensitive), plus a direct-open hint
    when ``q`` looks like a full part id. Reads only the mirror."""
    q = (request.GET.get("q") or "").strip()
    if len(q) < 2:
        return JsonResponse({"types": [], "parts": [], "direct_part": None})

    inst = instance_of(request)
    types = []
    type_qs = (HierarchyNode.for_instance(inst)
               .filter(level=HierarchyNode.LEVEL_TYPE)
               .filter(Q(name__icontains=q) | Q(part_type_id__icontains=q)
                       | Q(full_name__icontains=q))
               .order_by("system_name", "subsystem_name", "name")[:25])
    for n in type_qs:
        path = navigation.leaf_path_for(inst, n.part_type_id)
        if path:  # only types whose curated family is browsable are reachable
            types.append({
                "name": n.name, "part_type_id": n.part_type_id,
                "sub": f"{n.system_name} › {n.subsystem_name}",
                "n_components": n.n_components, "path": path,
            })

    parts = [
        {"part_id": pid, "part_type_id": ptid, "serial_number": serial,
         "path": _rev(request, "explore:part", args=[pid])}
        for pid, ptid, serial in (HwdbComponentEvent.for_instance(inst)
                                  .filter(Q(part_id__icontains=q)
                                          | Q(serial_number__icontains=q))
                                  .order_by("part_id")
                                  .values_list("part_id", "part_type_id", "serial_number")[:25])
    ]
    direct = q if _PID_RE.match(q) else None
    return JsonResponse({
        "types": types, "parts": parts, "direct_part": direct,
        "direct_part_url": _rev(request, "explore:part", args=[direct]) if direct else None,
    })
