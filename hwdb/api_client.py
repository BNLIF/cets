"""Thin HWDB REST client. One method per endpoint we hit.

Reads and writes both go through here. The upload library (hwdb.upload) layers
the find-or-create / status-patch / location / test-post orchestration on top.

Pattern: every method returns the parsed JSON body. Callers check the body's
``status`` field for HWDB's application-level success/error (HWDB returns
"OK"/"ERROR" even on 200s sometimes; the official DUNE script reads
``upload_result["status"]``). Network errors raise ``requests.RequestException``.
"""

import logging
from pathlib import Path

import requests

logger = logging.getLogger(__name__)


class FnalDbApiClient:
    def __init__(self, base_url, bearer):
        self.base_url = base_url
        # One Session per client = one keep-alive TCP/TLS pool. Halves
        # per-call latency vs. fresh ``requests.request`` (no handshake).
        # Sessions aren't fully thread-safe, so the parallel orchestrator
        # constructs one client per worker thread.
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {bearer}"

    def _make_request(self, method, endpoint, data=None, params=None):
        url = f"{self.base_url}/{endpoint}"
        headers = {}
        if method in ("POST", "PATCH"):
            headers["Content-Type"] = "application/json"
        try:
            response = self.session.request(
                method, url, headers=headers, json=data, params=params
            )
        except requests.exceptions.RequestException:
            logger.exception("API request to %s failed", url)
            raise
        if not response.ok:
            # Surface HWDB's pydantic validation detail — ``raise_for_status``
            # discards the response body, which is exactly where the useful
            # error message lives ("extra fields not permitted", etc.).
            body = (response.text or "")[:600]
            logger.warning(
                "HWDB %s %s -> %d: %s", method, url, response.status_code, body
            )
            raise requests.exceptions.HTTPError(
                f"{response.status_code} {response.reason} for {url}: {body}",
                response=response,
            )
        return response.json()

    # ---- Reads ----------------------------------------------------------

    def get_component_types(self, component_type_id):
        endpoint = f"component-types/{component_type_id}/components"
        return self._make_request("GET", endpoint)

    def get_subsystems(self, part1, part2):
        return self._make_request("GET", f"subsystems/{part1}/{part2}")

    def get_part_types_for_subsystem(self, part1, part2, subsystem_id):
        endpoint = f"component-types/{part1}/{part2}/{subsystem_id}"
        return self._make_request("GET", endpoint)

    def find_component_by_serial(self, part_type_id, serial_number):
        """Returns the first matching component dict, or None.

        Karla's ``isPartInHWDB`` flow — used by upload to decide create-vs-skip.
        """
        endpoint = f"component-types/{part_type_id}/components"
        body = self._make_request(
            "GET", endpoint, params={"serial_number": serial_number}
        )
        data = body.get("data") or []
        return data[0] if data else None

    def get_test_types(self, part_type_id):
        """List the test types defined for this component type.

        Used to resolve test-type names ("RoomT QC Test") to ids per instance
        (dev/prod ids differ).
        """
        return self._make_request("GET", f"component-types/{part_type_id}/test-types")

    def get_tests(self, part_id, test_type_id=None, history=False):
        """Tests for a component. With ``test_type_id`` set, narrows to that
        type; with ``history=True``, includes prior revisions.
        """
        if test_type_id is None:
            endpoint = f"components/{part_id}/tests"
            params = None
        else:
            endpoint = f"components/{part_id}/tests/{test_type_id}"
            params = {"history": "True"} if history else None
        return self._make_request("GET", endpoint, params=params)

    # ---- Writes ---------------------------------------------------------

    def create_component(self, part_type_id, payload):
        endpoint = f"component-types/{part_type_id}/components"
        return self._make_request("POST", endpoint, data=payload)

    def patch_component(self, part_id, payload):
        return self._make_request("PATCH", f"components/{part_id}", data=payload)

    def post_location(self, part_id, payload):
        return self._make_request(
            "POST", f"components/{part_id}/locations", data=payload
        )

    def post_test(self, part_id, payload):
        return self._make_request("POST", f"components/{part_id}/tests", data=payload)

    def attach_test_image(self, test_id, file_path):
        """Multipart POST. ``file_path`` is a filesystem path; the filename
        becomes the HWDB image_name. Routes through ``self.session`` so the
        Authorization header (set on session.headers) applies and the
        keep-alive pool is reused; passing explicit ``headers=`` would
        override session headers and drop auth.
        """
        url = f"{self.base_url}/component-tests/{test_id}/images"
        path = Path(file_path)
        with path.open("rb") as fp:
            files = {"image": (path.name, fp, "text/csv")}
            try:
                response = self.session.post(url, files=files)
                response.raise_for_status()
                return response.json()
            except requests.exceptions.RequestException:
                logger.exception("attach_test_image to %s failed", url)
                raise

    # ---- Legacy alias (used by older views; keep until they migrate) ----

    def post_component(self, component_data):
        # Old shape: assumes /components endpoint without the component-type
        # path. Retained so existing callers don't break; new code should use
        # ``create_component(part_type_id, payload)``.
        return self._make_request("POST", "components", data=component_data)
