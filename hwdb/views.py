import logging
from datetime import datetime, timedelta

from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from .api_client import FnalDbApiClient
from .fnal import flow
from .fnal import session as fnal_session

logger = logging.getLogger(__name__)
GENERIC_ERROR = "Failed to fetch data from the Hardware Database."
FNAL_UNAVAILABLE = "FNAL authentication service is unavailable. Please try again later."

# How long a started device flow stays valid before the user must reload.
DEVICE_FLOW_LIFETIME = timedelta(minutes=10)


def home(request):
    system_ids = [
        {"id": "D081", "name": "FD1-HD TPC_Elec. and FD2-VD Bottom_Elec."},
        # Add more system IDs here as needed
    ]
    ce_list = [
        {
            "name": "FEMB",
            "part_type_id": "D08100400001",
        },
        {
            "name": "LArASIC",
            "part_type_id": "D08100100001",
        },
        {
            "name": "ColdADC",
            "part_type_id": "D08100200001",
        },
        {
            "name": "COLDATA",
            "part_type_id": "D08100300001",
        },
        {
            "name": "Cold Cable Long",
            "part_type_id": "D08102100012",
        },
    ]
    context = {"system_ids": system_ids, "ce_list": ce_list}
    return render(request, "hwdb/home.html", context)


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


def component_list_view(request, component_type_id=None):
    api_client = FnalDbApiClient(
        base_url="https://dbwebapi2.fnal.gov:8443/cdbdev/api/v1"
    )

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
        }
        return render(request, "hwdb/component_list.html", context)
    except Exception:
        logger.exception("HWDB API call failed")
        return render(request, "hwdb/error.html", {"error_message": GENERIC_ERROR})


def subsystem_list_view(request, part1=None, part2=None):
    api_client = FnalDbApiClient(
        base_url="https://dbwebapi2.fnal.gov:8443/cdbdev/api/v1"
    )

    if not part1:
        part1 = "D"  # Default part1
    if not part2:
        part2 = "081"  # Default part2

    try:
        raw_response = api_client.get_subsystems(part1, part2)
        subsystems = raw_response.get("data", [])

        for subsystem in subsystems:
            if "created" in subsystem and subsystem["created"]:
                subsystem["created"] = datetime.fromisoformat(subsystem["created"])

        # Sort subsystems by subsystem_id
        subsystems.sort(key=lambda x: x.get("subsystem_id", 0))

        context = {
            "subsystems": subsystems,
            "current_part1": part1,
            "current_part2": part2,
        }
        return render(request, "hwdb/subsystem_list.html", context)
    except Exception:
        logger.exception("HWDB API call failed")
        return render(request, "hwdb/error.html", {"error_message": GENERIC_ERROR})


def part_type_list_view(request, part1, part2, subsystem_id):
    api_client = FnalDbApiClient(
        base_url="https://dbwebapi2.fnal.gov:8443/cdbdev/api/v1"
    )
    try:
        raw_response = api_client.get_part_types_for_subsystem(
            part1, part2, subsystem_id
        )
        part_types = raw_response.get("data", [])

        for part_type in part_types:
            if "created" in part_type and part_type["created"]:
                part_type["created"] = datetime.fromisoformat(part_type["created"])

        context = {
            "part_types": part_types,
            "current_part1": part1,
            "current_part2": part2,
            "current_subsystem_id": subsystem_id,
        }
        return render(request, "hwdb/part_type_list.html", context)
    except Exception:
        logger.exception("HWDB API call failed")
        return render(request, "hwdb/error.html", {"error_message": GENERIC_ERROR})
