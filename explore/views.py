import logging
from datetime import datetime, timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.http import JsonResponse, StreamingHttpResponse
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
from .models import HierarchyNode, HierarchySyncState, ShipmentItem
from .queries import component_type_progress, component_update_progress
from .shipments import box_detail, sync_shipments

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

    return render(
        request,
        "explore/explore.html",
        {
            "view": view,
            "sidebar": navigation.sidebar_tree(view["ctx"]),
            "leaf": leaf,
            "charts": charts,
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
def explore_shipment_box_view(request, part_id):
    """Live detail (timeline + manifest) for one box, as JSON (#44).

    The deliberate live-on-render carve-out (ADR-0013): fetched from HWDB prod
    on demand when a user expands a box, never mirrored. FNAL-gated; returns a
    JSON ``error`` (not a redirect) so the panel can degrade gracefully without
    losing the page.
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
        return JsonResponse(box_detail(api, part_id))
    except Exception:
        logger.exception("explore_shipment_box_view(%s) crashed", part_id)
        return JsonResponse({"error": "fetch_failed"}, status=502)
