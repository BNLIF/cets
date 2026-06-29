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

from .auth import fnal_login_required, provision_and_login
from .events import physics_date_field, sync_test_events
from .hierarchy import sync_hierarchy
from .models import ComponentTypeNode, HierarchySyncState
from .queries import component_type_progress, component_update_progress

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
def explore_view(request):
    """Read-only FD-VD component hierarchy, rendered from the local mirror.

    The sidebar folder-tree (System ▸ Subsystem ▸ Component Type) is built
    entirely from ``ComponentTypeNode`` rows — no live HWDB call on render, so
    the page is not FNAL-gated. Only the "Refresh hierarchy" button hits the
    API. Selecting a leaf (``?node=<part_type_id>``) shows its plots.
    """
    nodes = list(ComponentTypeNode.objects.all())  # Meta-ordered

    systems: dict[int, dict] = {}
    for n in nodes:
        s = systems.setdefault(
            n.system_id,
            {"id": n.system_id, "name": n.system_name, "subs": {}},
        )
        ss = s["subs"].setdefault(
            n.subsystem_id,
            {"id": n.subsystem_id, "name": n.subsystem_name, "leaves": []},
        )
        ss["leaves"].append(n)

    tree = []
    for s in sorted(systems.values(), key=lambda x: x["id"]):
        s["subs"] = sorted(s["subs"].values(), key=lambda x: x["id"])
        for sub in s["subs"]:
            sub["n_components"] = sum(leaf.n_components for leaf in sub["leaves"])
            sub["n_tests"] = sum(leaf.n_tests for leaf in sub["leaves"])
        s["n_components"] = sum(sub["n_components"] for sub in s["subs"])
        s["n_tests"] = sum(sub["n_tests"] for sub in s["subs"])
        tree.append(s)

    selected = request.GET.get("node")
    selected_node = next((n for n in nodes if n.part_type_id == selected), None)

    charts = []
    if selected_node and selected_node.tests_synced_at:
        ptid = selected_node.part_type_id
        comp_chart = chart_config(
            slug=f"{ptid}_comp", name="Components updated", href="",
            ranges=component_update_progress(ptid),
        )
        comp_chart["caption"] = (
            "By HWDB last-updated date (status change / QC upload bumps it), "
            "not the original mint date."
        )
        phys = physics_date_field(selected_node.part_type_id)
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
            "tree": tree,
            "selected_node": selected_node,
            "charts": charts,
            # Mirror is prod-sourced, so deep-link the part type to prod's UI
            # (matches the /hwdb/larasic/ convention).
            "hwdb_ui_base": settings.HWDB_PROFILES["prod"]["ui"],
            "node_count": len(nodes),
            "sync_state": HierarchySyncState.get(),
            "active_instance": active_instance(request),
            "page": "hwdb",
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
