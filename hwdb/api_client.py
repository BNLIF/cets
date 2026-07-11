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

    def get_systems(self, part1="D"):
        """List the systems under a project (part1), e.g. ``GET systems/D``.

        Each entry has ``id`` (the system segment of the PID) and ``name``
        (e.g. ``FD-VD TDE``). Used to walk the FD-VD hierarchy (ADR-0010).
        """
        return self._make_request("GET", f"systems/{part1}")

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

    def get_locations(self, part_id):
        """Location history for a component (the shipment journey).

        Each entry: ``arrived`` (ISO datetime), ``location`` (name), ``creator``,
        ``comments``, ``id``. The latest ``arrived`` is where the item is now.
        Used by the shipment tracker (ADR-0013).
        """
        return self._make_request("GET", f"components/{part_id}/locations")

    def get_subcomponents(self, part_id):
        """Subcomponents attached to a component (its manifest / contents).

        Maps functional position to the contained part. Used to show what a
        shipping box holds (ADR-0013).
        """
        return self._make_request("GET", f"components/{part_id}/subcomponents")

    def get_component_status(self, part_id):
        """Per-item status flags (``GET components/{pid}/status``): a dict
        mixing named status refs and booleans — HWDB's own word on why an
        item is/isn't "available" for packing. In the OpenAPI spec, not in
        the official Python client (issue #63).
        """
        return self._make_request("GET", f"components/{part_id}/status")

    def get_container(self, part_id):
        """The item's parent(s) (``GET components/{pid}/container``) — the
        reverse of ``get_subcomponents``: mount/unmount rows whose
        ``container`` ref names the box/assembly holding this item. Present
        in the HWDB OpenAPI spec but never wrapped by the official Python
        client (found via the live spec, 2026-07-11; also unwrapped there:
        PATCH pack-in / unpack).
        """
        return self._make_request("GET", f"components/{part_id}/container")

    def get_component(self, part_id):
        """Full item record, including the free-form ``specifications`` blob.

        The FD shipping workflow writes its pre-shipping / shipping / warehouse
        checklists into ``data.specifications[0].DATA`` — read back by the
        shipment detail panel (ADR-0013). Read-only.
        """
        return self._make_request("GET", f"components/{part_id}")

    def get_images(self, part_id):
        """List images/attachments on a component: ``{image_id, image_name}``.

        The shipping label, bill of lading and proforma invoice land here
        (ADR-0013). Download each via ``get_image_response``.
        """
        return self._make_request("GET", f"components/{part_id}/images")

    def get_component_type(self, part_type_id):
        """The component-type record itself (``GET component-types/{id}``):
        name, category, manufacturers, and ``properties.specifications`` —
        whose last entry's ``datasheet`` is the spec template a create
        payload must echo (issue #62). Distinct from ``get_component_types``
        (a legacy misnomer that lists the type's components).
        """
        return self._make_request("GET", f"component-types/{part_type_id}")

    def whoami(self):
        """The calling user's HWDB record (``GET users/whoami``): full_name
        and roles — the executive-summary signing gate matches signee roles
        against these (issue #64).
        """
        return self._make_request("GET", "users/whoami")

    def get_roles(self):
        """All defined HWDB roles ``{id, name}`` — for displaying which role
        a summary signee requires (issue #64)."""
        return self._make_request("GET", "roles")

    def get_institutions(self):
        """All registered institutions: ``{id, name, country: {code, name}}``.

        Options for the location dropdown of the explorer's Update-location
        form (issue #61) — the same list the official Dashboard offers.
        """
        return self._make_request("GET", "institutions")

    def get_component_type_images(self, part_type_id):
        """Attachments on the component TYPE (not an item): the executive
        summary's per-type config lives here as ``ES_{typeid}_*.json``
        (issue #64), discovered newest-first like the Dashboard does.
        """
        return self._make_request("GET", f"component-types/{part_type_id}/images")

    def get_qrcode_response(self, part_id):
        """The item's HWDB-issued QR code PNG (``GET get-qrcode/{pid}``) as a
        streaming response — drawn onto the shipping label (issue #65)."""
        url = f"{self.base_url}/get-qrcode/{part_id}"
        try:
            response = self.session.get(url, stream=True)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException:
            logger.exception("get_qrcode_response from %s failed", url)
            raise

    def get_image_response(self, image_id):
        """Raw attachment bytes by id (``GET img/{id}``) as a streaming
        ``requests.Response`` for the caller to proxy. The bytes are bearer-
        gated, so we can't hand the browser a direct FNAL link (ADR-0013).
        """
        url = f"{self.base_url}/img/{image_id}"
        try:
            response = self.session.get(url, stream=True)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException:
            logger.exception("get_image_response from %s failed", url)
            raise

    # ---- Writes ---------------------------------------------------------

    def create_component(self, part_type_id, payload):
        endpoint = f"component-types/{part_type_id}/components"
        return self._make_request("POST", endpoint, data=payload)

    def patch_component(self, part_id, payload):
        return self._make_request("PATCH", f"components/{part_id}", data=payload)

    def patch_subcomponents(self, part_id, payload):
        """Set a component's functional positions (issue #63). The payload is
        ``{"component": {"part_id": …}, "subcomponents": {pos: pid|None, …}}``;
        the official clients always send the COMPLETE positions dict, with
        ``None`` for a position to be (or stay) empty.
        """
        return self._make_request(
            "PATCH", f"components/{part_id}/subcomponents", data=payload
        )

    def post_location(self, part_id, payload):
        return self._make_request(
            "POST", f"components/{part_id}/locations", data=payload
        )

    def post_test(self, part_id, payload):
        return self._make_request("POST", f"components/{part_id}/tests", data=payload)

    def post_component_image(self, part_id, fileobj, filename, comments=""):
        """Multipart upload of an attachment onto an item
        (``POST components/{pid}/images``). ``filename`` becomes the HWDB
        ``image_name`` — the executive-summary gate matches on it (issue
        #53). Mirrors the official ``post_hwitem_image`` shape: data fields
        as form parts plus the file under ``image``.
        """
        url = f"{self.base_url}/components/{part_id}/images"
        files = {"comments": (None, comments),
                 "image": (filename, fileobj, "application/pdf")}
        try:
            response = self.session.post(url, files=files)
        except requests.exceptions.RequestException:
            logger.exception("post_component_image to %s failed", url)
            raise
        if not response.ok:
            body = (response.text or "")[:600]
            logger.warning("HWDB POST %s -> %d: %s", url, response.status_code, body)
            raise requests.exceptions.HTTPError(
                f"{response.status_code} {response.reason} for {url}: {body}",
                response=response,
            )
        return response.json()

    def post_component_type_image(self, part_type_id, fileobj, filename, comments=""):
        """Multipart upload of an attachment onto a component TYPE — the
        executive-summary config (``ES_{typeid}_*.json``) lives there
        (issue #64). Same multipart shape as ``post_component_image``.
        """
        url = f"{self.base_url}/component-types/{part_type_id}/images"
        files = {"comments": (None, comments),
                 "image": (filename, fileobj, "application/json")}
        try:
            response = self.session.post(url, files=files)
        except requests.exceptions.RequestException:
            logger.exception("post_component_type_image to %s failed", url)
            raise
        if not response.ok:
            body = (response.text or "")[:600]
            logger.warning("HWDB POST %s -> %d: %s", url, response.status_code, body)
            raise requests.exceptions.HTTPError(
                f"{response.status_code} {response.reason} for {url}: {body}",
                response=response,
            )
        return response.json()

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
