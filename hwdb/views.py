from django.shortcuts import render
from .api_client import FnalDbApiClient
import json
from urllib.parse import urlparse, parse_qs
from datetime import datetime


def home(request):
    system_ids = [
        {"id": "D081", "name": "FD1-HD TPC_Elec. and FD2-VD Bottom_Elec."},
        # Add more system IDs here as needed
    ]
    context = {"system_ids": system_ids}
    return render(request, "hwdb/home.html", context)


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
        total_items = pagination_data.get("total", 0)

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
    except Exception as e:
        return render(request, "hwdb/error.html", {"error_message": str(e)})


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
    except Exception as e:
        return render(request, "hwdb/error.html", {"error_message": str(e)})
