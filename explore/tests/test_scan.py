"""Tests for phone-as-scanner (issue #68): PID extraction (the Dashboard's
regexes), the scan submit/feed endpoints, and the packing page's hookup.

    python manage.py test explore
"""

from __future__ import annotations

import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from explore import scanning
from explore.models import PackScan

SUBMIT = "/hw/dev/scan/submit/"
FEED = "/hw/dev/scan/feed/"
PID = "D05700300001-00012"


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

    def test_prod_is_forbidden(self):
        self.assertEqual(self.client.get("/hw/scan/").status_code, 403)
        self.assertEqual(self.client.post("/hw/scan/submit/", {"text": PID}).status_code, 403)
        self.assertEqual(self.client.get("/hw/scan/feed/").status_code, 403)

    def test_scan_page_renders(self):
        resp = self.client.get("/hw/dev/scan/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("html5-qrcode.min.js", resp.content.decode())


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
        self.assertIn("/hw/dev/scan/", html)
        self.assertIn("<svg", html)  # the pairing QR
        self.assertIn(f"var since = {old.id};", html)  # stale scans skipped
