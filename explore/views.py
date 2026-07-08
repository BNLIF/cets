import json
import logging
import re
from datetime import datetime, timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.core.paginator import Paginator
from django.db.models import F, Q
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
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

from . import charts, curation, navigation
from .auth import fnal_login_required, provision_and_login
from .events import physics_date_field, sync_test_events
from .hierarchy import sync_hierarchy, sync_system
from .instances import instance_of, namespace_of
from .models import (
    HierarchyNode, HierarchySyncState, HwdbComponentEvent, ShipmentItem,
)
from .queries import (
    component_breakdowns, component_qc_flags, component_type_progress,
    component_update_filters, component_update_progress,
)
from .parts import assembly_children, part_detail
from .shipments import sync_shipments

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
    side_ctx = ({"kind": "leaf", "part_type_id": ptid, "system_id": leaf.system_id,
                 "subsystem_id": leaf.subsystem_id} if leaf else {})
    box = (ShipmentItem.for_instance(inst).filter(part_id=part_id).first()
           if is_shipping else None)
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
        "hwdb_ui_base": settings.HWDB_PROFILES[inst]["ui"],
    })


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
