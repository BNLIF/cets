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
from hwdb.instance import active_instance

from . import curation, navigation
from .auth import fnal_login_required, provision_and_login
from .events import physics_date_field, sync_test_events
from .hierarchy import sync_hierarchy
from .models import (
    HierarchyNode, HierarchySyncState, HwdbComponentEvent, ShipmentItem,
)
from .queries import component_type_progress, component_update_progress
from .parts import part_detail
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


@login_not_required
def login_view(request):
    """Sign in with FNAL — the explore site's only login (ADR-0011).

    Starts a device flow with the ``login_user`` intent set, so completion
    (in ``login_poll_view``) provisions + logs in a Django user keyed on the
    credkey. An already-authenticated visitor skips straight to ``next``.
    """
    next_url = _safe_next(request, reverse("explore:home"))
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
            "poll_url": reverse("explore:login_poll"),
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
    next_url = state.get("next") or reverse("explore:home")
    fnal_session.clear_flow(request)
    return JsonResponse({"status": "ok", "next": next_url})


@login_not_required
@fnal_login_required
def explore_view(request, trail=None):
    """Drill-in navigator over the curated DUNE hardware tree (ADR-0012, #40).

    A URL trail resolves to a node; folders render a breadcrumb + a grid of
    child cards, a component-type leaf renders the detail panel + plots. Reads
    the local mirror (no live HWDB on render). The legacy ``?node=<ptid>`` link
    permanently redirects to the node's path URL.
    """
    legacy = request.GET.get("node")
    if legacy:
        dest = navigation.leaf_path_for(legacy)
        if dest:
            return redirect(dest)

    view = navigation.resolve(trail)  # raises Http404 on an unknown path

    charts = []
    leaf = view.get("leaf")
    is_shipping = bool(leaf and curation.is_shipping_type(leaf.part_type_id))
    shipments = shipment_synced_at = shipment_summary = None
    if is_shipping:
        ptid = leaf.part_type_id
        # Only non-empty boxes are mirrored; n_contents>0 guard covers stale rows.
        rows = list(ShipmentItem.objects.filter(part_type_id=ptid, n_contents__gt=0))
        shipments = rows
        # Sync marker on the leaf — NOT inferred from rows, so a synced type with
        # 0 non-empty boxes reads as synced (no auto-sync loop).
        shipment_synced_at = leaf.shipments_synced_at
        in_transit = sum(1 for r in rows if r.location_id == 0)
        delivered = sum(1 for r in rows if r.location_id not in (0, None))
        shipment_summary = {
            "total": len(rows), "in_transit": in_transit, "delivered": delivered,
        }
        # Boxes-over-time chart (reuses the components-updated machinery; boxes
        # have no 'updated' so it bins on each box's created date).
        box_chart = chart_config(
            slug=f"{ptid}_comp", name="Boxes over time", href="",
            ranges=component_update_progress(ptid),
        )
        box_chart["caption"] = "Non-empty shipping boxes by HWDB created date."
        charts = [box_chart]
    elif leaf and leaf.tests_synced_at:
        ptid = leaf.part_type_id
        comp_chart = chart_config(
            slug=f"{ptid}_comp", name="Components updated", href="",
            ranges=component_update_progress(ptid),
        )
        comp_chart["caption"] = (
            "By HWDB last-updated date (status change / QC upload bumps it), "
            "not the original mint date."
        )
        phys = physics_date_field(ptid)
        test_chart = chart_config(
            slug=f"{ptid}_test",
            name="Tests performed" if phys else "Tests recorded",
            href="", ranges=component_type_progress(ptid),
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
    if leaf and not is_shipping and leaf.tests_synced_at:
        part_rows = (HwdbComponentEvent.objects
                     .filter(part_type_id=leaf.part_type_id)
                     .order_by(F("updated").desc(nulls_last=True),
                               F("created").desc(nulls_last=True), "part_id"))
        parts_page = Paginator(part_rows, 50).get_page(request.GET.get("page"))

    return render(
        request,
        "explore/explore.html",
        {
            "view": view,
            "sidebar": navigation.sidebar_tree(view["ctx"]),
            "leaf": leaf,
            "charts": charts,
            "parts_page": parts_page,
            "is_shipping": is_shipping,
            "shipments": shipments,
            "shipment_synced_at": shipment_synced_at,
            "shipment_summary": shipment_summary,
            # Mirror is prod-sourced, so deep-link the part type to prod's UI.
            "hwdb_ui_base": settings.HWDB_PROFILES["prod"]["ui"],
            "sync_state": HierarchySyncState.get(),
            "active_instance": active_instance(request),
        },
    )


@login_not_required
@fnal_login_required
def shipments_view(request):
    """Top-level Shipments dashboard (Hajime's ask): all boxes across the
    curated shipping types in one view, each linking into the box's existing
    leaf node view. Reads the mirror (skip-empties, like the leaf panel)."""
    sections, boxes = [], []
    agg = {"total": 0, "in_transit": 0, "delivered": 0}
    for ptid in sorted(curation.shipping_types()):
        leaf = HierarchyNode.objects.filter(
            level=HierarchyNode.LEVEL_TYPE, part_type_id=ptid).first()
        if not leaf:  # curated but not yet refreshed into the mirror
            continue
        path = navigation.leaf_path_for(ptid)
        rows = list(ShipmentItem.objects.filter(part_type_id=ptid, n_contents__gt=0))
        in_transit = sum(1 for r in rows if r.location_id == 0)
        delivered = sum(1 for r in rows if r.location_id not in (0, None))
        agg["total"] += len(rows)
        agg["in_transit"] += in_transit
        agg["delivered"] += delivered
        sections.append({
            "leaf": leaf, "path": path, "n": len(rows),
            "in_transit": in_transit, "delivered": delivered,
            "synced_at": leaf.shipments_synced_at,
        })
        for r in rows:
            boxes.append({"box": r, "type_name": leaf.name, "path": path})

    # In-transit first, then most-recently-arrived first.
    boxes.sort(key=lambda x: (
        0 if x["box"].location_id == 0 else 1,
        -(x["box"].last_arrived.timestamp() if x["box"].last_arrived else 0),
    ))
    page_obj = Paginator(boxes, 50).get_page(request.GET.get("page"))
    return render(request, "explore/shipments.html", {
        "active_nav": "shipments",
        "sections": sections,
        "page_obj": page_obj,
        "summary": agg,
        "hwdb_ui_base": settings.HWDB_PROFILES["prod"]["ui"],
    })


@login_not_required
@fnal_login_required
@require_POST
def explore_sync_view(request):
    """Stream a skeleton (hierarchy) refresh into ``ComponentTypeNode``.

    FNAL-gated; unlinked user is redirected to the link page with a ?next back
    to /explore/. Reads the production tree regardless of the session instance
    (the hierarchy is the same shape on dev, but prod is canonical).
    """
    try:
        bearer = mint_for(request)
    except FnalLinkRequired:
        link = reverse("hwdb:link")
        return redirect(f"{link}?{urlencode({'next': reverse('explore:home')})}")
    except FnalUnavailable:
        return render(request, "hwdb/error.html", {"error_message": FNAL_UNAVAILABLE})

    api = FnalDbApiClient(settings.HWDB_PROFILES["prod"]["api"], bearer)

    def _iter():
        try:
            yield from sync_hierarchy(api)
        except Exception as e:
            logger.exception("explore_sync_view crashed")
            yield f"hierarchy sync: CRASH · {e}\n"

    return StreamingHttpResponse(_iter(), content_type="text/plain; charset=utf-8")


@login_not_required
@fnal_login_required
@require_POST
def explore_node_sync_view(request, part_type_id):
    """Stream a test-event sync for one component type (issue #30).

    Lazy per-type sync behind the explorer's plot panel. FNAL-gated; reads the
    production tree (canonical). The browser fires this automatically on first
    visit to an unsynced leaf, and on the manual sync-mode buttons.
    """
    try:
        bearer = mint_for(request)
    except FnalLinkRequired:
        link = reverse("hwdb:link")
        nxt = f"{reverse('explore:home')}?node={part_type_id}"
        return redirect(f"{link}?{urlencode({'next': nxt})}")
    except FnalUnavailable:
        return render(request, "hwdb/error.html", {"error_message": FNAL_UNAVAILABLE})

    base_url = settings.HWDB_PROFILES["prod"]["api"]
    mode = request.POST.get("mode", "incremental")
    if mode not in ("incremental", "components", "full"):
        mode = "incremental"

    def _iter():
        try:
            yield from sync_test_events(base_url, bearer, part_type_id, mode=mode)
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
    reads production (canonical). Fired automatically on first visit to an
    unsynced shipping leaf, and by the manual "Sync shipments" button.
    """
    try:
        bearer = mint_for(request)
    except FnalLinkRequired:
        link = reverse("hwdb:link")
        nxt = f"{reverse('explore:home')}?node={part_type_id}"
        return redirect(f"{link}?{urlencode({'next': nxt})}")
    except FnalUnavailable:
        return render(request, "hwdb/error.html", {"error_message": FNAL_UNAVAILABLE})

    base_url = settings.HWDB_PROFILES["prod"]["api"]

    def _iter():
        try:
            yield from sync_shipments(base_url, bearer, part_type_id)
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

    api = FnalDbApiClient(settings.HWDB_PROFILES["prod"]["api"], bearer)
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

    api = FnalDbApiClient(settings.HWDB_PROFILES["prod"]["api"], bearer)
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
    try:
        bearer = mint_for(request)
    except FnalLinkRequired:
        link = reverse("hwdb:link")
        return redirect(f"{link}?{urlencode({'next': request.get_full_path()})}")
    except FnalUnavailable:
        return render(request, "explore/part_detail.html",
                      {"part_id": part_id, "unavailable": True})

    ptid = part_id.rsplit("-", 1)[0]
    is_shipping = curation.is_shipping_type(ptid)
    api = FnalDbApiClient(settings.HWDB_PROFILES["prod"]["api"], bearer)
    try:
        detail = part_detail(api, part_id, is_shipping)
    except Exception as e:
        logger.exception("explore_part_view(%s) crashed", part_id)
        return render(request, "explore/part_detail.html",
                      {"part_id": part_id, "unavailable": True,
                       "error_detail": f"{type(e).__name__}: {e}" if settings.DEBUG else None})

    # Catch-all attachments minus the ones already shown in a spec section.
    shown = {a["image_id"] for sec in detail["sections"] for a in sec["attachments"]}
    other_attachments = [a for a in detail["attachments"] if a["image_id"] not in shown]

    leaf = HierarchyNode.objects.filter(
        level=HierarchyNode.LEVEL_TYPE, part_type_id=ptid).first()
    box = ShipmentItem.objects.filter(part_id=part_id).first() if is_shipping else None
    return render(request, "explore/part_detail.html", {
        # A box belongs to the Shipments tab; everything else to Hardware.
        "active_nav": "shipments" if is_shipping else "hardware",
        "part_id": part_id,
        "detail": detail,
        "is_shipping": is_shipping,
        "other_attachments": other_attachments,
        "leaf": leaf,
        "leaf_path": navigation.leaf_path_for(ptid) if leaf else None,
        "box": box,
        "hwdb_ui_base": settings.HWDB_PROFILES["prod"]["ui"],
    })


# A full part id, e.g. ``D08100100003-00226`` — type-id segment then a sequence.
_PID_RE = re.compile(r"^[A-Za-z0-9]{8,}-\w+$")


@login_not_required
@fnal_login_required
def explore_search_view(request):
    """Instant search over the local mirror (ADR-0014): jump to a component
    type's leaf page or a part's detail page by name / id. Mirror-only, so no
    FNAL needed; live cross-field 'advanced' search is a later addition."""
    return render(request, "explore/search.html",
                  {"active_nav": "search", "q": request.GET.get("q", "")})


@login_not_required
@fnal_login_required
def explore_search_api_view(request):
    """JSON results for the instant search box — component types + mirrored
    parts matching ``q`` (substring, case-insensitive), plus a direct-open hint
    when ``q`` looks like a full part id. Reads only the mirror."""
    q = (request.GET.get("q") or "").strip()
    if len(q) < 2:
        return JsonResponse({"types": [], "parts": [], "direct_part": None})

    types = []
    type_qs = (HierarchyNode.objects
               .filter(level=HierarchyNode.LEVEL_TYPE)
               .filter(Q(name__icontains=q) | Q(part_type_id__icontains=q)
                       | Q(full_name__icontains=q))
               .order_by("system_name", "subsystem_name", "name")[:25])
    for n in type_qs:
        path = navigation.leaf_path_for(n.part_type_id)
        if path:  # only types whose curated family is browsable are reachable
            types.append({
                "name": n.name, "part_type_id": n.part_type_id,
                "sub": f"{n.system_name} › {n.subsystem_name}",
                "n_components": n.n_components, "path": path,
            })

    parts = [
        {"part_id": pid, "part_type_id": ptid,
         "path": reverse("explore:part", args=[pid])}
        for pid, ptid in (HwdbComponentEvent.objects
                          .filter(part_id__icontains=q)
                          .order_by("part_id")
                          .values_list("part_id", "part_type_id")[:25])
    ]
    direct = q if _PID_RE.match(q) else None
    return JsonResponse({"types": types, "parts": parts, "direct_part": direct})
