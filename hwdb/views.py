import logging
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from urllib.parse import urlencode

from decouple import config as env_config
from django.conf import settings
from django.db.models import Count, Max, Q
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.models import LArASIC, FEMB, FembTest

from .api_client import FnalDbApiClient
from .fnal import flow
from .fnal import session as fnal_session
from .fnal.bearer import FnalLinkRequired, FnalUnavailable, mint_for
from .fnal.session import LINK_KEY
from .instance import SESSION_KEY, active_instance, active_profile
from .hierarchy import sync_hierarchy
from .models import (
    ComponentTypeNode,
    HierarchySyncState,
    HwdbChip,
    HwdbSyncState,
    LarasicSyncState,
)
from .sync import sync_family
from .upload import larasic as upload_lib

FAMILY_PART_TYPE_KEY = {
    "larasic": "larasic_part_type",
    "coldadc": "coldadc_part_type",
    "coldata": "coldata_part_type",
}
FAMILY_DISPLAY = {
    "larasic": "LArASIC",
    "coldadc": "ColdADC",
    "coldata": "COLDATA",
}

logger = logging.getLogger(__name__)
GENERIC_ERROR = "Failed to fetch data from the Hardware Database."
FNAL_UNAVAILABLE = "FNAL authentication service is unavailable. Please try again later."

# How long a started device flow stays valid before the user must reload.
DEVICE_FLOW_LIFETIME = timedelta(minutes=10)


def home(request):
    """HWDB section landing: a card per component type.

    Static (no HWDB API call), so it is not FNAL-gated — a logged-in user can
    see what the section offers; the per-type Display view does the gating.
    Only LArASIC is wired up; its part type follows the configured instance.
    The rest are "coming soon" and get an instance-resolved id when activated.
    """
    profile = active_profile(request)
    component_types = [
        {
            "name": "LArASIC",
            "description": "16-ch cold front-end ASIC",
            "part_type_id": profile["larasic_part_type"],
            "active": True,
            "url": reverse("hwdb:larasic"),
        },
        {"name": "ColdADC", "description": "12-bit cold ADC", "part_type_id": None, "active": False},
        {"name": "COLDATA", "description": "Serializer / control", "part_type_id": None, "active": False},
        {"name": "FEMB", "description": "Frontend Motherboard", "part_type_id": None, "active": False},
        {"name": "Cable", "description": "Cold flex cable", "part_type_id": None, "active": False},
    ]
    return render(
        request,
        "hwdb/home.html",
        {
            "component_types": component_types,
            "active_instance": active_instance(request),
            "instances": list(settings.HWDB_PROFILES),
            "page": "hwdb",
        },
    )


def set_instance(request):
    """Set the per-session HWDB instance override and return to where you were."""
    if request.method == "POST":
        choice = request.POST.get("instance")
        if choice in settings.HWDB_PROFILES:
            request.session[SESSION_KEY] = choice
    return redirect(_safe_next(request, reverse("hwdb:home")))


def _hwdb_family_card(family):
    """Stat-card payload for one family on /hwdb/dashboard/.

    All numbers come from the local HwdbChip mirror — no HWDB API calls. The
    dashboard renders ColdADC for issue #23; COLDATA (#24) and LArASIC (#25)
    plug into the same shape.

    LArASIC additionally carries two "Δ" counts (#27) — chips that BNL has
    tested locally but the HWDB mirror has not seen as tested. This is the
    upload backlog made visible.
    """
    qs = HwdbChip.objects.filter(family=family)
    total = qs.count()
    ln_tested = qs.filter(latest_ln_test_at__isnull=False).count()
    state = HwdbSyncState.for_family(family)
    card = {
        "family": family,
        "name": FAMILY_DISPLAY[family],
        "in_hwdb": total,
        "ln_tested": ln_tested,
        "last_synced": state.finished_at,
        "chips_new": state.chips_new,
        "chips_disappeared": state.chips_disappeared,
        "sync_url": reverse("hwdb:dashboard_sync", args=[family]),
    }
    if family == "larasic":
        card.update(_larasic_consistency_delta())
    return card


def _larasic_consistency_delta():
    """Counts of LArASIC chips BNL has tested locally but the HwdbChip mirror
    has not seen as tested. See ADR-0007 — the consistency check is exactly
    this gap. Two counts: warm (vs RT) and cold (vs LN).
    """
    rt_in_hwdb = HwdbChip.objects.filter(
        family="larasic", latest_rt_test_at__isnull=False
    ).values_list("serial_number", flat=True)
    ln_in_hwdb = HwdbChip.objects.filter(
        family="larasic", latest_ln_test_at__isnull=False
    ).values_list("serial_number", flat=True)
    delta_rt = (
        LArASIC.objects.filter(warm_tested_at__isnull=False)
        .exclude(serial_number__in=rt_in_hwdb)
        .count()
    )
    delta_ln = (
        LArASIC.objects.filter(cold_tested_at__isnull=False)
        .exclude(serial_number__in=ln_in_hwdb)
        .count()
    )
    return {"delta_rt": delta_rt, "delta_ln": delta_ln}


def dashboard_view(request):
    """HWDB-mirror dashboard. Reads ``HwdbChip`` (no live HWDB calls)."""
    from core import queries

    families = ["larasic", "coldadc", "coldata"]
    cards = [_hwdb_family_card(f) for f in families]
    charts = [
        queries.chart_config(
            slug=f"hwdb-{f}",
            name=FAMILY_DISPLAY[f],
            href=reverse("hwdb:dashboard"),
            ranges=queries.hwdb_family_progress(f),
        )
        for f in families
    ]
    return render(
        request,
        "hwdb/dashboard.html",
        {
            "page": "hwdb",
            "cards": cards,
            "progress_charts": charts,
            "active_instance": active_instance(request),
            "instances": list(settings.HWDB_PROFILES),
        },
    )


def dashboard_probe_view(request, family):
    """Diagnostic: fetch one chip's tests and the family's test_type catalog.

    The dashboard's sync code only writes rows whose tests match the
    "RoomT QC Test" / "CryoT QC Test" names. When a family appears to sync
    successfully but the chart stays empty, this probe is the first thing
    to check — either no QC tests exist upstream, or they use names our
    mapping in ``hwdb/sync.py`` doesn't recognize.
    """
    if family not in FAMILY_PART_TYPE_KEY:
        return JsonResponse({"error": "unknown family"}, status=400)
    try:
        bearer = mint_for(request)
    except FnalLinkRequired:
        link = reverse("hwdb:link")
        return redirect(
            f"{link}?{urlencode({'next': reverse('hwdb:dashboard')})}"
        )
    except FnalUnavailable:
        return JsonResponse({"error": FNAL_UNAVAILABLE}, status=503)

    prod = settings.HWDB_PROFILES["prod"]
    part_type_id = prod[FAMILY_PART_TYPE_KEY[family]]
    api = FnalDbApiClient(prod["api"], bearer)

    # Allow targeting a specific chip via ?part_id=... — useful for
    # "I think this chip has tests, why didn't sync see them?" lookups.
    explicit_part_id = request.GET.get("part_id")
    if explicit_part_id:
        sample = HwdbChip.objects.filter(
            family=family, part_id=explicit_part_id
        ).first() or HwdbChip(part_id=explicit_part_id, serial_number="(not in mirror)")
    else:
        sample = HwdbChip.objects.filter(family=family).exclude(part_id="").first()
    out = {"family": family, "part_type_id": part_type_id}

    try:
        # The catalog (/test-types) returns flat entries: {id, name, ...} —
        # NOT nested under a "test_type" key like /components/{id}/tests does.
        catalog = api.get_test_types(part_type_id)
        out["test_type_catalog"] = [
            {"id": t.get("id"), "name": t.get("name")}
            for t in (catalog.get("data") or [])
        ]
    except Exception as e:
        out["test_type_catalog_error"] = str(e)[:300]

    if sample is None:
        out["sample"] = "no HwdbChip rows for this family — run Sync first"
    else:
        out["sample_serial_number"] = sample.serial_number
        out["sample_part_id"] = sample.part_id
        try:
            # Summary call — enumerates test types only; test_data is
            # typically empty / metadata-only.
            summary = api.get_tests(sample.part_id)
            summary_tests = summary.get("data") or []
            out["summary_test_count"] = len(summary_tests)
            out["summary_tests"] = [
                {
                    "test_type_id": (t.get("test_type") or {}).get("id"),
                    "test_type_name": (t.get("test_type") or {}).get("name"),
                    "data_keys": list((t.get("test_data") or {}).keys())[:8],
                    "record_keys": list(t.keys()),
                    "record_top_level": {
                        k: v for k, v in t.items()
                        if k != "test_data" and not isinstance(v, (list, dict))
                    },
                }
                for t in summary_tests
            ]
            # Deep call per test type — returns the actual datasheet.
            # Karla's GetItemTests follows the same two-step pattern.
            out["deep_tests"] = {}
            for st in summary_tests:
                tt_id = (st.get("test_type") or {}).get("id")
                if not tt_id:
                    continue
                deep = api.get_tests(sample.part_id, test_type_id=tt_id, history=True)
                deep_rows = deep.get("data") or []
                out["deep_tests"][str(tt_id)] = {
                    "name": (st.get("test_type") or {}).get("name"),
                    "count": len(deep_rows),
                    "rows": [
                        {
                            "id": r.get("id"),
                            "test_date": (r.get("test_data") or {}).get("Test Date"),
                            "test_time": (r.get("test_data") or {}).get("Test Time"),
                            "data_keys": list((r.get("test_data") or {}).keys())[:10],
                            "record_top_level": {
                                k: v for k, v in r.items()
                                if k != "test_data" and not isinstance(v, (list, dict))
                            },
                        }
                        for r in deep_rows
                    ],
                }
        except Exception as e:
            out["sample_tests_error"] = str(e)[:300]

    return JsonResponse(out, json_dumps_params={"indent": 2})


@require_POST
def dashboard_sync_view(request, family):
    """Stream a HwdbChip sync for one family.

    Prod-only (dev session = no-op redirect, mirrors ADR-0003/0004).
    FNAL-gated; unlinked user is redirected to /hwdb/link/?next=/hwdb/dashboard/.
    """
    if family not in FAMILY_PART_TYPE_KEY:
        return redirect(reverse("hwdb:dashboard"))
    if active_instance(request) != "prod":
        return redirect(reverse("hwdb:dashboard"))
    try:
        bearer = mint_for(request)
    except FnalLinkRequired:
        link = reverse("hwdb:link")
        return redirect(
            f"{link}?{urlencode({'next': reverse('hwdb:dashboard')})}"
        )
    except FnalUnavailable:
        return render(request, "hwdb/error.html", {"error_message": FNAL_UNAVAILABLE})

    prod = settings.HWDB_PROFILES["prod"]
    part_type_id = prod[FAMILY_PART_TYPE_KEY[family]]
    force_full = request.POST.get("force") == "full"

    def _iter():
        try:
            yield from sync_family(
                family,
                part_type_id=part_type_id,
                api_base_url=prod["api"],
                bearer=bearer,
                force_full=force_full,
            )
        except Exception as e:
            logger.exception("dashboard_sync_view(%s) crashed", family)
            yield f"sync {family}: CRASH · {e}\n"

    return StreamingHttpResponse(_iter(), content_type="text/plain; charset=utf-8")


def larasic_view(request):
    """Browse local LArASIC chips against HWDB. Same grouped tray/FEMB layout as
    the general /larasic/ page plus an extra "In HWDB" column and sync stats.

    The is_in_hwdb flag is local-only, so the page itself is not FNAL-gated.
    Only the Sync button hits the API.
    """
    from core.views import _grouped_chip_response

    qs = LArASIC.objects.all()
    total = qs.count()
    in_hwdb = qs.filter(is_in_hwdb=True).count()
    last_synced = qs.aggregate(Max("hwdb_checked_at"))["hwdb_checked_at__max"]
    hwdb_only = LarasicSyncState.get().hwdb_only_count

    return _grouped_chip_response(
        request,
        model=LArASIC,
        family_label="LArASIC",
        family_title="LArASIC · HWDB sync",
        family_subtitle="Local chips vs HWDB",
        chips_per_femb=8,
        has_tray_view=True,
        page_id="hwdb",
        include_to_upload=True,
        tray_drill_url_name="hwdb:upload_tray",
        full_template="hwdb/larasic.html",
        extra_context={
            "total": total,
            "in_hwdb": in_hwdb,
            "to_upload": total - in_hwdb,
            "hwdb_only": hwdb_only,
            "last_synced": last_synced,
            "larasic_part_type": active_profile(request)["larasic_part_type"],
            "active_instance": active_instance(request),
            "instances": list(settings.HWDB_PROFILES),
        },
    )


@require_POST
def larasic_sync_view(request):
    """Stream a LArASIC sync — the engine is now ``sync_family("larasic")``
    so this populates ``HwdbChip`` AND keeps the legacy ``is_in_hwdb`` /
    ``LarasicSyncState`` flags up-to-date (see ADR-0007 and the legacy-flag
    helper in ``hwdb/sync.py``). Streaming because a cold sync fetches
    ``get_tests`` per chip — minutes on a 12k-chip backlog.
    """
    if active_instance(request) != "prod":
        return redirect(reverse("hwdb:larasic"))
    try:
        bearer = mint_for(request)
    except FnalLinkRequired:
        link = reverse("hwdb:link")
        return redirect(f"{link}?{urlencode({'next': reverse('hwdb:larasic')})}")
    except FnalUnavailable:
        return render(request, "hwdb/error.html", {"error_message": FNAL_UNAVAILABLE})

    prod = settings.HWDB_PROFILES["prod"]
    force_full = request.POST.get("force") == "full"

    def _iter():
        try:
            yield from sync_family(
                "larasic",
                part_type_id=prod["larasic_part_type"],
                api_base_url=prod["api"],
                bearer=bearer,
                force_full=force_full,
            )
        except Exception as e:
            logger.exception("larasic_sync_view crashed")
            yield f"sync larasic: CRASH · {e}\n"

    return StreamingHttpResponse(_iter(), content_type="text/plain; charset=utf-8")


def _safe_next(request, default):
    """Return the next= target (GET or POST) if it's a safe internal URL."""
    nxt = request.POST.get("next") or request.GET.get("next")
    if nxt and url_has_allowed_host_and_scheme(
        nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return nxt
    return default


def fnal_link_view(request):
    """Start a FNAL device flow and render the polling page.

    Stashes the in-progress flow (and where to return) in the session; the
    page polls fnal_link_poll_view until vault completes the login.
    """
    next_url = _safe_next(request, reverse("hwdb:home"))
    try:
        start = flow.start()
    except Exception:
        logger.exception("FNAL device-flow start failed")
        return render(request, "hwdb/error.html", {"error_message": FNAL_UNAVAILABLE})

    fnal_session.set_flow(
        request, start.poll_body, timezone.now() + DEVICE_FLOW_LIFETIME, next_url
    )
    return render(
        request,
        "hwdb/link.html",
        {
            "auth_url": start.auth_url,
            "user_code": start.user_code,
            "poll_url": reverse("hwdb:link_poll"),
        },
    )


def fnal_link_poll_view(request):
    """One poll tick. Returns JSON: pending / ok (+next) / error."""
    state = fnal_session.get_flow(request)
    if not state:
        return JsonResponse(
            {"status": "error", "detail": "no link in progress; reload to start"},
            status=404,
        )
    if datetime.fromisoformat(state["expires_at"]) <= timezone.now():
        fnal_session.clear_flow(request)
        return JsonResponse(
            {"status": "error", "detail": "link timed out; reload to start again"},
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
        login = flow.complete(result.auth or {})
    except Exception:
        logger.exception("FNAL device-flow completion failed")
        return JsonResponse({"status": "error", "detail": FNAL_UNAVAILABLE}, status=502)

    fnal_session.store_link(request, login)
    next_url = state.get("next") or reverse("hwdb:home")
    fnal_session.clear_flow(request)
    return JsonResponse({"status": "ok", "next": next_url})


def with_fnal_bearer(view):
    """Mint a per-request FNAL bearer and pass it to the view.

    Owns the Q9 failure surface in one place:
    - no/expired/undecryptable/rejected token -> redirect to the link page
      with a ?next back to here.
    - vault unreachable / transient -> the generic hwdb error page (re-linking
      wouldn't help).
    """

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        try:
            bearer = mint_for(request)
        except FnalLinkRequired:
            link = reverse("hwdb:link")
            return redirect(f"{link}?{urlencode({'next': request.get_full_path()})}")
        except FnalUnavailable:
            return render(
                request, "hwdb/error.html", {"error_message": FNAL_UNAVAILABLE}
            )
        return view(request, bearer, *args, **kwargs)

    return wrapper


@with_fnal_bearer
def component_list_view(request, bearer, component_type_id=None):
    profile = active_profile(request)
    api_client = FnalDbApiClient(profile["api"], bearer)

    # If component_type_id is not provided in the URL, use a default or raise an error
    if not component_type_id:
        component_type_id = "D08100400001"  # Default component type ID

    # Get page number from request, default to 1
    page = int(request.GET.get("page", 1))
    size = int(request.GET.get("size", 100))

    # Construct the endpoint with pagination parameters
    endpoint = f"component-types/{component_type_id}/components?page={page}&size={size}"

    try:
        raw_response = api_client._make_request("GET", endpoint)

        component_type_name = raw_response.get("component_type", {}).get(
            "name", "Unknown Component Type"
        )
        components = raw_response.get("data", [])

        # Convert 'created' string to datetime object
        for component in components:
            if "created" in component and component["created"]:
                # Handle ISO 8601 format with microseconds and timezone offset
                component["created"] = datetime.fromisoformat(component["created"])

        pagination_data = raw_response.get("pagination", {})
        current_page = pagination_data.get("page", 1)
        page_size = pagination_data.get("page_size", 100)
        total_pages = pagination_data.get("pages", 1)

        next_page = current_page + 1 if current_page < total_pages else None
        prev_page = current_page - 1 if current_page > 1 else None
        first_page = 1
        last_page = total_pages

        context = {
            "component_type_name": component_type_name,
            "components": components,
            "current_page": current_page,
            "next_page": next_page,
            "prev_page": prev_page,
            "first_page": first_page,
            "last_page": last_page,
            "page_size": page_size,
            "current_component_type_id": component_type_id,
            "hwdb_ui_base": profile["ui"],
            "active_instance": active_instance(request),
            "page": "hwdb",
        }
        return render(request, "hwdb/component_list.html", context)
    except Exception:
        logger.exception("HWDB API call failed")
        return render(request, "hwdb/error.html", {"error_message": GENERIC_ERROR})


# Generic HWDB tree browse (subsystems -> part types -> components). Demoted
# from primary nav to the landing's "More" card in #13, but still useful for
# poking around the raw HWDB structure.
@with_fnal_bearer
def subsystem_list_view(request, bearer, part1=None, part2=None):
    api_client = FnalDbApiClient(active_profile(request)["api"], bearer)
    part1 = part1 or "D"
    part2 = part2 or "081"
    try:
        raw_response = api_client.get_subsystems(part1, part2)
        subsystems = raw_response.get("data", [])
        for subsystem in subsystems:
            if subsystem.get("created"):
                subsystem["created"] = datetime.fromisoformat(subsystem["created"])
        subsystems.sort(key=lambda x: x.get("subsystem_id", 0))
        context = {
            "subsystems": subsystems,
            "current_part1": part1,
            "current_part2": part2,
            "active_instance": active_instance(request),
            "page": "hwdb",
        }
        return render(request, "hwdb/subsystem_list.html", context)
    except Exception:
        logger.exception("HWDB API call failed")
        return render(request, "hwdb/error.html", {"error_message": GENERIC_ERROR})


# ---- FD-VD component explorer (ADR-0010, issue #29) ----------------------


def explore_view(request):
    """Read-only FD-VD component hierarchy, rendered from the local mirror.

    The sidebar folder-tree (System ▸ Subsystem ▸ Component Type) is built
    entirely from ``ComponentTypeNode`` rows — no live HWDB call on render, so
    the page is not FNAL-gated. Only the "Refresh hierarchy" button hits the
    API. Selecting a leaf (``?node=<part_type_id>``) shows a placeholder panel;
    the per-type plots land in issue #30.
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
        s["n_components"] = sum(
            leaf.n_components for sub in s["subs"] for leaf in sub["leaves"]
        )
        tree.append(s)

    selected = request.GET.get("node")
    selected_node = next((n for n in nodes if n.part_type_id == selected), None)

    return render(
        request,
        "hwdb/explore.html",
        {
            "tree": tree,
            "selected_node": selected_node,
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
    to /hwdb/explore/. Reads the production tree regardless of the session
    instance (the hierarchy is the same shape on dev, but prod is canonical).
    """
    try:
        bearer = mint_for(request)
    except FnalLinkRequired:
        link = reverse("hwdb:link")
        return redirect(f"{link}?{urlencode({'next': reverse('hwdb:explore')})}")
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


# ---- Upload (Phase-3, issues #19/#20/#21) --------------------------------


def upload_index_view(request):
    """Legacy URL — the tray worklist is now merged into /hwdb/larasic/.

    Old bookmarks land here and bounce; the merged page surfaces the same
    To-upload count and CSV-availability signals as table columns.
    """
    return redirect("hwdb:larasic")


def _rts_root() -> Path | None:
    """Resolve RTS_DIR from env. Returns None if unconfigured."""
    try:
        return Path(env_config("RTS_DIR"))
    except Exception:
        return None


@require_POST
def upload_refresh_csv_cache_view(request):
    """Walk every known tray and refresh its CSV cache (L1 + L2).

    The index page reads ``TrayCsvCache`` rows directly to avoid one SMB
    ``stat()`` per tray on every render — that's deliberately fast and
    deliberately stale: a tray that just gained CSVs but was never visited
    has no row yet, so the badge won't light up until someone clicks through
    to its detail page. This view forces the catch-up: one full scan across
    all known trays, then redirect back to the index.

    Synchronous; for a few dozen trays this takes a handful of seconds even
    on SMB. We don't need a FNAL bearer (reads filesystem + writes local DB).
    """
    rts_root = _rts_root()
    if rts_root is None:
        return render(
            request,
            "hwdb/error.html",
            {"error_message": "RTS_DIR is not configured."},
            status=500,
        )
    tray_ids = list(
        LArASIC.objects.exclude(tray_id__isnull=True)
        .exclude(tray_id="")
        .values_list("tray_id", flat=True)
        .distinct()
    )
    for tid in tray_ids:
        upload_lib.scan_tray_csvs(rts_root, tid)
    return redirect("hwdb:larasic")


def upload_tray_view(request, tray_id):
    """Per-tray chip list with per-row + global upload buttons.

    Scans ``RTS_DIR/<tray_id>/results/`` once and badges each chip row with
    whether its RT and LN CSVs are available — so the user sees up front
    whether the upload will be detailed (CSV → 67 fields) or simple (no CSV
    → 7 fields).
    """
    chips = LArASIC.objects.filter(tray_id=tray_id).order_by("serial_number")
    chip_count = chips.count()
    instance = active_instance(request)

    rts_root = _rts_root()
    csvs = upload_lib.scan_tray_csvs(rts_root, tray_id)

    # Map serial → HWDB part_id so each row can deep-link to the official
    # component record (test/upload history). The HwdbChip mirror is synced
    # from PROD (all rows are the prod part type), so the link targets the prod
    # UI regardless of the active instance — that's where the canonical history
    # lives. Chips not yet in HWDB have no part_id and render unlinked.
    part_ids = dict(
        HwdbChip.objects.filter(
            family="larasic",
            serial_number__in=chips.values_list("serial_number", flat=True),
        ).values_list("serial_number", "part_id")
    )
    hwdb_ui_base = settings.HWDB_PROFILES["prod"]["ui"]

    # Four states (computed per-chip so "done" can account for CSV attachment,
    # matching the index page's to_upload_count — see _annotate_to_upload):
    #   "new"         — not in HWDB → create + post tests.
    #   "enrich"      — in HWDB (likely from FEMB workflow) but our QC tests
    #                   aren't confirmed there → reuse part_id + post missing tests.
    #   "csv-pending" — tests confirmed, but an analysis CSV is now available
    #                   and not yet attached → re-upload upgrades simple→detailed.
    #   "done"        — tests confirmed and no CSV waiting → skip unless Force.
    new_count = enrich_count = csv_pending_count = done_count = 0
    chip_rows = []
    for chip in chips:
        if not chip.is_in_hwdb:
            state = "new"
            new_count += 1
        elif not chip.qc_tests_uploaded:
            state = "enrich"
            enrich_count += 1
        elif upload_lib.csv_attach_pending(chip, csvs):
            state = "csv-pending"
            csv_pending_count += 1
        else:
            state = "done"
            done_count += 1
        pid = part_ids.get(chip.serial_number)
        chip_rows.append({
            "chip": chip,
            "state": state,
            "has_rt_csv": (chip.serial_number, "RT") in csvs,
            "has_ln_csv": (chip.serial_number, "LN") in csvs,
            "hwdb_url": f"{hwdb_ui_base}/edit/component/{pid}" if pid else None,
        })
    upload_count = new_count + enrich_count + csv_pending_count
    has_analysis = bool(csvs)

    return render(
        request,
        "hwdb/upload_tray.html",
        {
            "tray_id": tray_id,
            "chip_rows": chip_rows,
            "chip_count": chip_count,
            "new_count": new_count,
            "enrich_count": enrich_count,
            "csv_pending_count": csv_pending_count,
            "done_count": done_count,
            "upload_count": upload_count,
            "has_analysis": has_analysis,
            "csv_count": len(csvs),
            "active_instance": instance,
            "instances": list(settings.HWDB_PROFILES),
            "is_dev": instance == "dev",
            "page": "hwdb",
        },
    )


def _stream_upload(api, chips, *, part_type_id, rts_root, attach_csvs, instance, tray_id, operator_name, force_csv_attach=False):
    """Generator that yields per-chip progress lines for ``upload_run_view``.

    Per Q9 error policy: continue past per-chip errors with a clear line, no
    retries. End with a tally line. Bearer is already minted by the caller.
    """
    total = len(chips)
    yield f"Starting upload of {total} chip(s) on tray {tray_id} to {instance}.\n"
    if total == 0:
        yield "No chips to upload.\n"
        return

    try:
        test_type_ids = {
            "RT": upload_lib.resolve_test_type_id(api, part_type_id, "RoomT QC Test"),
            "LN": upload_lib.resolve_test_type_id(api, part_type_id, "CryoT QC Test"),
        }
    except Exception as e:
        yield f"*** cannot resolve HWDB test types: {e} ***\n"
        return

    ok = failed = 0
    promoted = []  # chips whose is_in_hwdb we should flip True on prod
    csv_warm = []  # chip pks whose RT CSV was attached in this run
    csv_cold = []  # chip pks whose LN CSV was attached in this run

    for i, chip in enumerate(chips, 1):
        yield f"[{i}/{total}] {chip.serial_number}: "
        try:
            result = upload_lib.upload_chip(
                api,
                chip,
                part_type_id=part_type_id,
                instance=instance,
                rts_root=rts_root,
                attach_csvs=attach_csvs,
                test_type_ids=test_type_ids,
                operator_name=operator_name,
                force_csv_attach=force_csv_attach,
            )
        except Exception as e:
            failed += 1
            logger.exception("upload_chip crashed for %s", chip.serial_number)
            yield f"CRASH — {e}\n"
            continue

        if result.error:
            failed += 1
            yield f"FAIL — {result.error}\n"
            continue

        bits = [f"created {result.part_id}" if result.created else f"exists ({result.part_id})"]
        for t in result.tests:
            if t.error:
                bits.append(f"{t.env} FAIL: {t.error}")
            elif t.skipped:
                bits.append(f"{t.env} skipped (already test_id={t.test_id})")
            else:
                atch = " +csv" if t.csv_attached else ""
                bits.append(f"{t.env}={t.test_id} ({t.mode}{atch})")
        if all(t.error is None for t in result.tests):
            ok += 1
            if instance == "prod":
                promoted.append((chip.pk, result.part_id))
                for t in result.tests:
                    if t.csv_attached and t.env == "RT":
                        csv_warm.append(chip.pk)
                    elif t.csv_attached and t.env == "LN":
                        csv_cold.append(chip.pk)
        else:
            failed += 1
        yield ", ".join(bits) + "\n"

    yield from _commit_prod_stamps(instance, promoted, csv_warm, csv_cold)
    yield f"\nDone. ok={ok} failed={failed}\n"


def _commit_prod_stamps(instance, promoted, csv_warm, csv_cold):
    """Flip is_in_hwdb / qc_tests_uploaded for promoted chips, and stamp the
    per-env csv_attached_at timestamps for chips whose CSVs we actually attached
    in this run. Prod-only — dev runs leave the local state alone, same as the
    existing is_in_hwdb policy ([[0003-prod-scoped-is-in-hwdb-flag]])."""
    if instance != "prod":
        return
    now = timezone.now()
    if promoted:
        ids = [pk for pk, _ in promoted]
        LArASIC.objects.filter(pk__in=ids).update(
            is_in_hwdb=True,
            qc_tests_uploaded=True,
            hwdb_checked_at=now,
        )
        yield f"(updated is_in_hwdb=True, qc_tests_uploaded=True on {len(ids)} local row(s))\n"
    if csv_warm:
        LArASIC.objects.filter(pk__in=csv_warm).update(warm_csv_attached_at=now)
    if csv_cold:
        LArASIC.objects.filter(pk__in=csv_cold).update(cold_csv_attached_at=now)
    if csv_warm or csv_cold:
        yield f"(stamped csv_attached_at on {len(csv_warm)} RT + {len(csv_cold)} LN row(s))\n"


def _stream_upload_parallel(
    *, base_url, bearer, chips, part_type_id, rts_root, attach_csvs,
    instance, tray_id, operator_name, workers, force_csv_attach=False,
):
    """Parallel sibling of ``_stream_upload``. Same UX (per-chip line +
    final tally) but lines arrive in completion order with a monotonic
    ``[done k/total]`` counter instead of input-order ``[i/total]``.
    See ADR-0005.
    """
    total = len(chips)
    yield f"Starting parallel upload of {total} chip(s) on tray {tray_id} to {instance} ({workers} workers).\n"
    if total == 0:
        yield "No chips to upload.\n"
        return

    # Resolve test types once with a short-lived client; worker threads will
    # build their own clients.
    bootstrap = FnalDbApiClient(base_url, bearer)
    try:
        test_type_ids = {
            "RT": upload_lib.resolve_test_type_id(bootstrap, part_type_id, "RoomT QC Test"),
            "LN": upload_lib.resolve_test_type_id(bootstrap, part_type_id, "CryoT QC Test"),
        }
    except Exception as e:
        yield f"*** cannot resolve HWDB test types: {e} ***\n"
        return

    def make_client():
        return FnalDbApiClient(base_url, bearer)

    ok = failed = 0
    promoted = []
    csv_warm = []
    csv_cold = []
    done = 0
    for chip, result in upload_lib.iter_upload_chips_parallel(
        chips,
        client_factory=make_client,
        part_type_id=part_type_id,
        instance=instance,
        rts_root=rts_root,
        attach_csvs=attach_csvs,
        test_type_ids=test_type_ids,
        operator_name=operator_name,
        workers=workers,
        force_csv_attach=force_csv_attach,
    ):
        done += 1
        prefix = f"[done {done}/{total}] {chip.serial_number}: "
        if result.error:
            failed += 1
            yield prefix + f"FAIL — {result.error}\n"
            continue
        bits = [f"created {result.part_id}" if result.created else f"exists ({result.part_id})"]
        for t in result.tests:
            if t.error:
                bits.append(f"{t.env} FAIL: {t.error}")
            elif t.skipped:
                bits.append(f"{t.env} skipped (already test_id={t.test_id})")
            else:
                atch = " +csv" if t.csv_attached else ""
                bits.append(f"{t.env}={t.test_id} ({t.mode}{atch})")
        if all(t.error is None for t in result.tests):
            ok += 1
            if instance == "prod":
                promoted.append((chip.pk, result.part_id))
                for t in result.tests:
                    if t.csv_attached and t.env == "RT":
                        csv_warm.append(chip.pk)
                    elif t.csv_attached and t.env == "LN":
                        csv_cold.append(chip.pk)
        else:
            failed += 1
        yield prefix + ", ".join(bits) + "\n"

    yield from _commit_prod_stamps(instance, promoted, csv_warm, csv_cold)
    yield f"\nDone. ok={ok} failed={failed}\n"


@require_POST
def upload_run_view(request, tray_id):
    """Stream per-chip upload progress as text/plain.

    Issues #19/#20 land the DEV path; #21 adds the PROD gauntlet (a
    type-to-confirm modal on the client — see ``upload_tray.html``). The
    server-side gate is the FNAL writer role: HWDB returns 403 without it,
    we surface the error per-chip. Per Q8 we do not duplicate the gauntlet
    server-side.
    """
    instance = active_instance(request)

    try:
        bearer = mint_for(request)
    except FnalLinkRequired:
        link = reverse("hwdb:link")
        return redirect(
            f"{link}?{urlencode({'next': reverse('hwdb:upload_tray', args=[tray_id])})}"
        )
    except FnalUnavailable:
        return render(request, "hwdb/error.html", {"error_message": FNAL_UNAVAILABLE})

    profile = active_profile(request)
    api = FnalDbApiClient(profile["api"], bearer)
    part_type_id = profile["larasic_part_type"]
    # credkey is the FNAL services username — most honest "Operator Name" we have.
    operator_name = (request.session.get(LINK_KEY) or {}).get("credkey") or ""

    chips_qs = LArASIC.objects.filter(tray_id=tray_id).order_by("serial_number")
    chip_filter = request.POST.get("chip")
    if chip_filter:
        chips_qs = chips_qs.filter(serial_number=chip_filter)

    rts_root = _rts_root()
    force = request.POST.get("force") == "on"

    if request.POST.get("random_5") == "on" and instance == "dev":
        # Dev-only quick-feasibility sample. order_by("?") picks a fresh random
        # subset per click — useful for repeatedly exercising the full pipeline
        # without burning a whole tray.
        chips = list(chips_qs.order_by("?")[:5])
    else:
        chips = list(chips_qs)

    # On PROD, default behavior skips chips that are fully done: QC tests
    # confirmed AND no newly-available CSV waiting to be attached. A csv-pending
    # chip is kept so the bulk run upgrades it simple→detailed and attaches the
    # CSV (find_existing_test won't dedup detailed-over-simple). "Force
    # re-upload" walks everything — find_existing_test still protects HWDB from
    # duplicates. Per-chip button presses bypass this filter (explicit opt-in).
    # Dev always walks everything (qc_tests_uploaded reflects PROD state).
    if instance == "prod" and not force and not chip_filter:
        csvs = upload_lib.scan_tray_csvs(rts_root, tray_id)
        chips = [
            c for c in chips
            if not c.qc_tests_uploaded or upload_lib.csv_attach_pending(c, csvs)
        ]

    attach_csvs = request.POST.get("attach_csvs", "on") == "on"
    # Re-post detailed-mode tests even if a detailed record already exists.
    # Used to retry CSV attachment when a prior detailed upload's attach
    # silently failed. Posts a duplicate test record by design (probe 3:
    # HWDB doesn't dedup, and PATCH on tests isn't supported).
    force_csv_attach = request.POST.get("force_csv_attach") == "on"

    mode = "parallel" if request.POST.get("mode") == "parallel" else "serial"
    if mode == "parallel":
        try:
            workers = int(request.GET.get("workers", "10"))
        except (TypeError, ValueError):
            workers = 10
        workers = max(1, min(32, workers))
        stream = _stream_upload_parallel(
            base_url=profile["api"],
            bearer=bearer,
            chips=chips,
            part_type_id=part_type_id,
            rts_root=rts_root,
            attach_csvs=attach_csvs,
            instance=instance,
            tray_id=tray_id,
            operator_name=operator_name,
            workers=workers,
            force_csv_attach=force_csv_attach,
        )
    else:
        stream = _stream_upload(
            api,
            chips,
            part_type_id=part_type_id,
            rts_root=rts_root,
            attach_csvs=attach_csvs,
            instance=instance,
            tray_id=tray_id,
            operator_name=operator_name,
            force_csv_attach=force_csv_attach,
        )

    response = StreamingHttpResponse(
        stream,
        content_type="text/plain; charset=utf-8",
    )
    # Hint reverse proxies not to buffer; supported by nginx, ignored by Apache.
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


@with_fnal_bearer
def part_type_list_view(request, bearer, part1, part2, subsystem_id):
    profile = active_profile(request)
    api_client = FnalDbApiClient(profile["api"], bearer)
    try:
        raw_response = api_client.get_part_types_for_subsystem(part1, part2, subsystem_id)
        part_types = raw_response.get("data", [])
        for part_type in part_types:
            if part_type.get("created"):
                part_type["created"] = datetime.fromisoformat(part_type["created"])
        context = {
            "part_types": part_types,
            "current_part1": part1,
            "current_part2": part2,
            "current_subsystem_id": subsystem_id,
            "hwdb_ui_base": profile["ui"],
            "active_instance": active_instance(request),
            "page": "hwdb",
        }
        return render(request, "hwdb/part_type_list.html", context)
    except Exception:
        logger.exception("HWDB API call failed")
        return render(request, "hwdb/error.html", {"error_message": GENERIC_ERROR})
