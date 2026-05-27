import logging
from datetime import datetime, timedelta
from functools import wraps
from urllib.parse import urlencode

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from .api_client import FnalDbApiClient
from .fnal import flow
from .fnal import session as fnal_session
from .fnal.bearer import FnalLinkRequired, FnalUnavailable, mint_for

logger = logging.getLogger(__name__)
GENERIC_ERROR = "Failed to fetch data from the Hardware Database."
FNAL_UNAVAILABLE = "FNAL authentication service is unavailable. Please try again later."

# How long a started device flow stays valid before the user must reload.
DEVICE_FLOW_LIFETIME = timedelta(minutes=10)


# Component types in the HWDB section landing. Only LArASIC is wired up so
# far; the rest are shown as "coming soon" until their Display/Compare lands.
COMPONENT_TYPES = [
    {"name": "LArASIC", "part_type_id": "D08100100001", "active": True},
    {"name": "ColdADC", "part_type_id": "D08100200001", "active": False},
    {"name": "COLDATA", "part_type_id": "D08100300001", "active": False},
    {"name": "FEMB", "part_type_id": "D08100400001", "active": False},
    {"name": "Cable", "part_type_id": "D08102100012", "active": False},
]


def home(request):
    """HWDB section landing: a card per component type.

    Static (no HWDB API call), so it is not FNAL-gated — a logged-in user can
    see what the section offers; the per-type Display view does the gating.
    """
    return render(
        request, "hwdb/home.html", {"component_types": COMPONENT_TYPES, "page": "hwdb"}
    )


def _safe_next(request, default):
    """Return the ?next= target if it's a safe internal URL, else default."""
    nxt = request.GET.get("next")
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
    api_client = FnalDbApiClient(settings.HWDB_API_BASE_URL, bearer)

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
    api_client = FnalDbApiClient(settings.HWDB_API_BASE_URL, bearer)
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
            "page": "hwdb",
        }
        return render(request, "hwdb/subsystem_list.html", context)
    except Exception:
        logger.exception("HWDB API call failed")
        return render(request, "hwdb/error.html", {"error_message": GENERIC_ERROR})


@with_fnal_bearer
def part_type_list_view(request, bearer, part1, part2, subsystem_id):
    api_client = FnalDbApiClient(settings.HWDB_API_BASE_URL, bearer)
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
            "page": "hwdb",
        }
        return render(request, "hwdb/part_type_list.html", context)
    except Exception:
        logger.exception("HWDB API call failed")
        return render(request, "hwdb/error.html", {"error_message": GENERIC_ERROR})
