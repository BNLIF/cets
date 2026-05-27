import logging

import requests

logger = logging.getLogger(__name__)


class FnalDbApiClient:
    def __init__(self, base_url, bearer):
        self.base_url = base_url
        self.base_headers = {
            "Authorization": f"Bearer {bearer}",
        }

    def _make_request(self, method, endpoint, data=None):
        url = f"{self.base_url}/{endpoint}"
        request_headers = self.base_headers.copy()

        if method in ["POST", "PATCH"]:
            request_headers["Content-Type"] = "application/json"

        try:
            response = requests.request(method, url, headers=request_headers, json=data)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException:
            logger.exception("API request to %s failed", url)
            raise

    def get_component_types(self, component_type_id):
        endpoint = f"component-types/{component_type_id}/components"
        return self._make_request("GET", endpoint)

    # Subsystem / part-type reads — back the generic HWDB tree browse
    # (subsystem_list / part_type_list views).
    def get_subsystems(self, part1, part2):
        endpoint = f"subsystems/{part1}/{part2}"
        return self._make_request("GET", endpoint)

    def get_part_types_for_subsystem(self, part1, part2, subsystem_id):
        endpoint = f"component-types/{part1}/{part2}/{subsystem_id}"
        return self._make_request("GET", endpoint)

    def post_component(self, component_data):
        endpoint = "components"  # Example endpoint for posting a new component
        return self._make_request("POST", endpoint, data=component_data)

    def patch_component(self, component_id, update_data):
        endpoint = (
            f"components/{component_id}"  # Example endpoint for patching a component
        )
        return self._make_request("PATCH", endpoint, data=update_data)
