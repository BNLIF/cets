"""Tests for phone-as-scanner (issue #68): PID extraction (the Dashboard's
regexes), the scan submit/feed endpoints, and the packing page's hookup.

    python manage.py test explore
"""

from __future__ import annotations

import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from explore import scanning
from explore.models import PackScan

SUBMIT = "/hw/dev/scan/submit/"
FEED = "/hw/dev/scan/feed/"
PID = "D05700300001-00012"
BOX = "D00599800007-00128"       # dev-curated shipping type


def _cart_api():
    """HWDB mock for scan-to-cart: a two-FEB box with FEB1 free."""
    api = mock.MagicMock()
    api.get_component_type.return_value = {"status": "OK", "data": {
        "connectors": {"FEB1": "D05700300001", "FEB2": "D05700300001"}}}
    api.get_subcomponents.return_value = {"data": [
        {"part_id": "D05700300001-00099", "type_name": "FEB",
         "functional_position": "FEB2", "operation": "mount"}]}
    api.patch_subcomponents.return_value = {"status": "OK", "data": "Updated"}
    return api


def _mocked(api):
    return (mock.patch("explore.views.mint_for", return_value="bearer"),
            mock.patch("explore.views.FnalDbApiClient", return_value=api))


class ExtractPidTest(TestCase):
    def test_bare_pid(self):
        self.assertEqual(scanning.extract_pid(PID), PID)
        self.assertEqual(scanning.extract_pid(f"  {PID}\n"), PID)

    def test_pid_with_label_suffix(self):
        self.assertEqual(scanning.extract_pid(f"{PID}-US186"), PID)

    def test_hwdb_urls(self):
        for base in ("https://dbweb0.fnal.gov/cdb", "https://dbweb0.fnal.gov/cdbdev"):
            self.assertEqual(
                scanning.extract_pid(f"{base}/view/component/{PID}"), PID)

    def test_garbage(self):
        self.assertEqual(scanning.extract_pid(""), "")
        self.assertEqual(scanning.extract_pid("hello world"), "")
        self.assertEqual(scanning.extract_pid("D057-00012"), "")

    def test_qr_svg(self):
        svg = scanning.qr_svg("https://example.org/hw/dev/scan/")
        self.assertTrue(svg.startswith("<svg"))


class ScanEndpointsTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("w", "w@w.io", "pw")
        self.client.force_login(self.user)

    def test_submit_extracts_and_queues(self):
        resp = self.client.post(SUBMIT, {"text": f"{PID}-US186"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(json.loads(resp.content)["pid"], PID)
        row = PackScan.objects.get()
        self.assertEqual((row.instance, row.username, row.part_id),
                         ("dev", "w", PID))

    def test_submit_rejects_garbage(self):
        resp = self.client.post(SUBMIT, {"text": "not a label"})
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(PackScan.objects.count(), 0)

    def test_checklist_scan_keeps_a_serial_number_and_its_target(self):
        # #170: the scan page opened from a checklist posts target + free —
        # a serial number is stored as scanned; the desktop resolves it
        resp = self.client.post(SUBMIT, {"text": "HPK19901", "target": PID, "free": "1"})
        self.assertEqual(resp.status_code, 200)
        row = PackScan.objects.get()
        self.assertEqual((row.part_id, row.target, row.ok), ("HPK19901", PID, None))
        # a PID in a label / URL is still extracted
        resp = self.client.post(SUBMIT, {"text": f"{PID}-US186", "target": PID, "free": "1"})
        self.assertEqual(json.loads(resp.content)["pid"], PID)
        # without free (or without a target), non-PID text is refused as before
        self.assertEqual(self.client.post(SUBMIT, {"text": "HPK19901", "target": PID}).status_code, 422)
        self.assertEqual(self.client.post(SUBMIT, {"text": "HPK19901", "free": "1"}).status_code, 422)

    def test_checklist_scan_checks_a_serial_against_the_tables_type(self):
        # #170 (Chao): random text must not reach the table — with the
        # table's type posted, the serial has to be on exactly one item of it
        api = mock.MagicMock()
        api.find_components_by_serial.return_value = []
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post(SUBMIT, {"text": "hello", "target": PID, "free": "1", "type": "D00400300001"})
            self.assertEqual(resp.status_code, 422)
            self.assertEqual(json.loads(resp.content)["error"], "no item of type D00400300001 has serial number hello")
            api.find_components_by_serial.return_value = [{"part_id": "D00400300001-00019"}, {"part_id": "D00400300001-00039"}]
            resp = self.client.post(SUBMIT, {"text": "3309", "target": PID, "free": "1", "type": "D00400300001"})
            self.assertEqual(resp.status_code, 422)
            self.assertIn("serial number 3309 is on 2 items: D00400300001-00019, D00400300001-00039 — enter the PID",
                          json.loads(resp.content)["error"])
            api.find_components_by_serial.return_value = [{"part_id": "D00400300001-00019"}]
            resp = self.client.post(SUBMIT, {"text": "HPK19901", "target": PID, "free": "1", "type": "D00400300001"})
            self.assertEqual(resp.status_code, 200)
        self.assertEqual(PackScan.objects.get().part_id, "HPK19901")   # the page resolves it in the cell
        api.find_components_by_serial.assert_called_with("D00400300001", "HPK19901")
        # a PID is never looked up; no type = nothing to check against
        with m1, m2:
            self.client.post(SUBMIT, {"text": PID, "target": PID, "free": "1", "type": "D00400300001"})
            self.client.post(SUBMIT, {"text": "anything", "target": PID, "free": "1"})
        self.assertEqual(api.find_components_by_serial.call_count, 3)
        self.assertEqual(PackScan.objects.count(), 3)

    def test_page_acks_a_scan_and_the_phone_reads_the_outcome(self):
        # #170: the checklist page records what became of each scan; the
        # phone polls its own rows — never another user's
        mine = PackScan.objects.create(instance="dev", username="w", part_id="HPK19901", target=PID)
        other = PackScan.objects.create(instance="dev", username="other", part_id="HPK19902", target=PID)
        resp = self.client.post("/hw/dev/scan/ack/", {"id": mine.id, "ok": "1", "message": "→ Left · 2"})
        self.assertEqual(resp.status_code, 200)
        mine.refresh_from_db()
        self.assertEqual((mine.ok, mine.result), (True, "→ Left · 2"))
        self.assertEqual(self.client.post("/hw/dev/scan/ack/", {"id": other.id, "ok": "0", "message": "x"}).status_code, 404)
        other.refresh_from_db()
        self.assertIsNone(other.ok)
        body = json.loads(self.client.get(f"/hw/dev/scan/outcome/?ids={mine.id},{other.id}").content)
        self.assertEqual(body["scans"], [{"id": mine.id, "pid": "HPK19901", "ok": True, "message": "→ Left · 2"}])

    def test_feed_is_per_target(self):
        # #170: a checklist's page polls its target; the packing pages see
        # only target-less scans — neither takes the other's
        PackScan.objects.create(instance="dev", username="w", part_id="HPK19901", target=PID)
        plain = PackScan.objects.create(instance="dev", username="w", part_id="D05700300001-00013")
        PackScan.objects.create(instance="dev", username="w", part_id="HPK19902", target="D05700300001-00099")
        self.assertEqual([s["pid"] for s in json.loads(self.client.get(FEED).content)["scans"]],
                         ["D05700300001-00013"])
        body = json.loads(self.client.get(f"{FEED}?target={PID}").content)
        self.assertEqual([s["pid"] for s in body["scans"]], ["HPK19901"])
        self.assertEqual(body["last"], plain.id - 1)

    def test_feed_returns_only_newer_scans_for_this_user(self):
        mine1 = PackScan.objects.create(instance="dev", username="w", part_id=PID)
        PackScan.objects.create(instance="dev", username="other", part_id="D05700300001-00099")
        PackScan.objects.create(instance="prod", username="w", part_id="D05700300001-00098")
        mine2 = PackScan.objects.create(instance="dev", username="w", part_id="D05700300001-00013")

        body = json.loads(self.client.get(FEED).content)
        self.assertEqual([s["pid"] for s in body["scans"]],
                         [PID, "D05700300001-00013"])
        self.assertEqual(body["last"], mine2.id)

        body = json.loads(self.client.get(f"{FEED}?since={mine1.id}").content)
        self.assertEqual([s["pid"] for s in body["scans"]], ["D05700300001-00013"])

    def test_submit_with_box_links_immediately(self):
        # Scan-to-cart: the phone's submit performs the link itself and
        # reports the outcome to both screens.
        api = _cart_api()
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post(SUBMIT, {"text": PID, "box": BOX})
        body = json.loads(resp.content)
        self.assertTrue(body["ok"])
        self.assertIn("FEB1", body["message"])
        api.patch_subcomponents.assert_called_once_with(BOX, {
            "component": {"part_id": BOX},
            "subcomponents": {"FEB1": PID, "FEB2": "D05700300001-00099"}})
        row = PackScan.objects.get()
        self.assertEqual((row.box_part_id, row.ok), (BOX, True))
        self.assertIn("FEB1", row.result)

    def test_submit_with_box_reports_hwdb_refusal(self):
        api = _cart_api()
        api.patch_subcomponents.return_value = {
            "status": "ERROR", "data": f"Component '{PID}' is not yet available"}
        api.get_container.return_value = {"data": []}
        api.get_component_status.return_value = {
            "data": {"status": {"id": 1, "name": "Available"}}}
        m1, m2 = _mocked(api)
        with m1, m2:
            body = json.loads(self.client.post(
                SUBMIT, {"text": PID, "box": BOX}).content)
        self.assertFalse(body["ok"])
        self.assertIn("not yet available", body["message"])
        self.assertIn("status=Available", body["message"])
        self.assertFalse(PackScan.objects.get().ok)

    def test_submit_with_box_full_position_warns(self):
        api = _cart_api()
        api.get_subcomponents.return_value = {"data": [
            {"part_id": "D05700300001-00098", "functional_position": "FEB1",
             "operation": "mount"},
            {"part_id": "D05700300001-00099", "functional_position": "FEB2",
             "operation": "mount"}]}
        m1, m2 = _mocked(api)
        with m1, m2:
            body = json.loads(self.client.post(
                SUBMIT, {"text": PID, "box": BOX}).content)
        self.assertFalse(body["ok"])
        self.assertIn("no free position", body["message"])
        api.patch_subcomponents.assert_not_called()

    def test_submit_with_disallowed_status_is_refused_locally(self):
        # Scan-to-cart shares the procedure's status rule (#84): a mirrored
        # status outside the four allowed ones never reaches HWDB.
        from explore.models import HwdbComponentEvent
        HwdbComponentEvent.objects.create(
            instance="dev", part_type_id="D05700300001", part_id=PID,
            status="In Repair", status_id=160)
        api = _cart_api()
        m1, m2 = _mocked(api)
        with m1, m2:
            body = json.loads(self.client.post(
                SUBMIT, {"text": PID, "box": BOX}).content)
        self.assertFalse(body["ok"])
        self.assertIn("not one the Shipping Procedure allows", body["message"])
        api.patch_subcomponents.assert_not_called()

    def test_submit_with_malformed_box_is_rejected(self):
        # #136: any item with positions may be a scan target — only a non-PID is refused up front
        resp = self.client.post(SUBMIT, {"text": PID, "box": "not-a-pid"})
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(PackScan.objects.count(), 0)

    def test_feed_carries_scan_to_cart_outcome(self):
        PackScan.objects.create(instance="dev", username="w", part_id=PID,
                                box_part_id=BOX, ok=True, result="added to “FEB1”")
        s = json.loads(self.client.get(FEED).content)["scans"][0]
        self.assertEqual((s["ok"], s["box"]), (True, BOX))
        self.assertIn("FEB1", s["message"])

    @override_settings(HWDB_WRITE_INSTANCES=["dev"])
    def test_prod_is_forbidden(self):
        self.assertEqual(self.client.get("/hw/scan/").status_code, 403)
        self.assertEqual(self.client.post("/hw/scan/submit/", {"text": PID}).status_code, 403)
        self.assertEqual(self.client.get("/hw/scan/feed/").status_code, 403)

    def test_scan_page_renders(self):
        resp = self.client.get("/hw/dev/scan/")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn("html5-qrcode.min.js", html)
        # The scan queue pairs phone and desktop by username — show who this
        # session scans as, so a mixed sign-in is spottable at a glance.
        self.assertIn("Scanning as <strong>w</strong>", html)

    def test_scan_page_with_box_shows_cart_mode(self):
        html = self.client.get(f"/hw/dev/scan/?box={BOX}").content.decode()
        self.assertIn(f"Scan items into", html)
        self.assertIn(BOX, html)
        self.assertIn("added to the box\n      immediately", html)
        self.assertIn(f'var BOX = "{BOX}";', html)
        # A malformed box param falls back to the select-only page.
        html = self.client.get("/hw/dev/scan/?box=junk").content.decode()
        self.assertIn('var BOX = "";', html)


    def test_scan_page_with_target_shows_checklist_mode(self):
        html = self.client.get(f"/hw/dev/scan/?target={PID}&free=1&type=D00400300001&sn=HPK%5Cd%7B5%7D").content.decode()
        self.assertIn("Scan into the checklist of", html)
        self.assertIn(PID, html)
        self.assertIn(f'var TARGET = "{PID}", FREE = true;', html)
        # the table's type and serial pattern: the phone refuses a code of
        # another type or off the pattern before sending it
        self.assertIn('var TYPE = "D00400300001", SN = "HPK\\u005Cd{5}"', html)   # escapejs; JS reads HPK\d{5}
        self.assertIn("Items of type <span", html)
        self.assertIn("PID or serial number", html)
        self.assertIn('var BOX = "";', html)
        # a malformed target falls back to the packing page's select mode; free/type/sn need a target
        html = self.client.get("/hw/dev/scan/?target=junk&free=1&type=D00400300001&sn=x").content.decode()
        self.assertIn("Scan items into your packing page", html)
        self.assertIn('var TARGET = "", FREE = false;', html)
        self.assertIn('var TYPE = "", SN = ""', html)


class PackPageHookupTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("w", "w@w.io", "pw")
        self.client.force_login(self.user)

    def test_pack_page_carries_scan_context(self):
        old = PackScan.objects.create(instance="dev", username="w", part_id=PID)
        api = mock.MagicMock()
        api.get_component_type.return_value = {"data": {"connectors": {
            "FEB1": "D05700300001"}}}
        api.get_subcomponents.return_value = {"data": []}
        with mock.patch("explore.views.mint_for", return_value="bearer"), \
             mock.patch("explore.views.FnalDbApiClient", return_value=api):
            resp = self.client.get("/hw/dev/part/D00599800007-00128/pack/")
        html = resp.content.decode()
        self.assertIn("Scan with your phone", html)
        # The scan link (and its QR) carries the box, so scans add directly.
        self.assertIn("/hw/dev/scan/?box=D00599800007-00128", html)
        self.assertIn("<svg", html)  # the pairing QR
        self.assertIn(f"var since = {old.id};", html)  # stale scans skipped
        self.assertIn("listening as <strong>w</strong>", html)  # identity shown
