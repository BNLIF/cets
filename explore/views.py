import logging
from urllib.parse import urlencode

from django.conf import settings
from django.http import StreamingHttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.queries import chart_config
from hwdb.api_client import FnalDbApiClient
from hwdb.fnal.bearer import FnalLinkRequired, FnalUnavailable, mint_for
from hwdb.instance import active_instance

from .events import physics_date_field, sync_test_events
from .hierarchy import sync_hierarchy
from .models import ComponentTypeNode, HierarchySyncState
from .queries import component_type_progress, component_update_progress

logger = logging.getLogger(__name__)
FNAL_UNAVAILABLE = "FNAL authentication service is unavailable. Please try again later."


def _ce_links(node):
    if node is None or node.system_id != 81:
        return []
    dashboard = {"label": "CE progress dashboard", "url": reverse("hwdb:dashboard")}
    by_subsystem = {
        "LArASIC": [
            {"label": "Detailed QC & upload", "url": reverse("hwdb:larasic")},
            {"label": "LArASIC chips", "url": reverse("larasic")},
            dashboard,
        ],
        "ColdADC": [{"label": "ColdADC chips", "url": reverse("coldadc")}, dashboard],
        "COLDATA": [{"label": "COLDATA chips", "url": reverse("coldata")}, dashboard],
        "FEMB": [{"label": "FEMB", "url": reverse("femb")}, dashboard],
    }
    return by_subsystem.get(node.subsystem_name, [])


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
            "ce_links": _ce_links(selected_node),
            # Mirror is prod-sourced, so deep-link the part type to prod's UI
            # (matches the /hwdb/larasic/ convention).
            "hwdb_ui_base": settings.HWDB_PROFILES["prod"]["ui"],
            "node_count": len(nodes),
            "sync_state": HierarchySyncState.get(),
            "active_instance": active_instance(request),
            "page": "hwdb",
        },
    )


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
