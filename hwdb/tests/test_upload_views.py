"""View-level tests for the Phase-3 upload UI (issues #19/#20).

We don't hit live HWDB — ``mint_for`` and ``upload_lib.upload_chip`` are mocked.
The point is to verify URL wiring, instance gating, streaming-response shape,
and the per-chip-vs-batch chip selection.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import LArASIC
from hwdb.upload import larasic as upload_lib


def _login(client):
    user = get_user_model().objects.create_user("guest", password="x")
    client.force_login(user)
    return user


class UploadIndexTest(TestCase):
    def setUp(self):
        _login(self.client)
        LArASIC.objects.create(
            serial_number="002-00001", tray_id="B005T0011", is_in_hwdb=False
        )
        LArASIC.objects.create(
            serial_number="002-00002", tray_id="B005T0011", is_in_hwdb=True
        )
        LArASIC.objects.create(
            serial_number="002-00003", tray_id="B005T0012", is_in_hwdb=False
        )
        # Untrayed chip: should not appear on the index.
        LArASIC.objects.create(serial_number="002-00004", tray_id="")

    def test_lists_trays_with_counts(self):
        resp = self.client.get(reverse("hwdb:upload_index"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "B005T0011")
        self.assertContains(resp, "B005T0012")
        self.assertNotContains(resp, "002-00004")  # the empty-tray chip

    def test_refresh_csv_cache_calls_scan_per_tray(self):
        # Walks every distinct tray_id and runs scan_tray_csvs once each.
        from unittest import mock
        with mock.patch("hwdb.views.upload_lib.scan_tray_csvs") as scan, \
             mock.patch("hwdb.views._rts_root", return_value=__import__("pathlib").Path("/tmp")):
            resp = self.client.post(reverse("hwdb:upload_refresh_csv_cache"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("hwdb:upload_index"), resp["Location"])
        # Two distinct trays in setUp: B005T0011 (×2 chips) + B005T0012.
        scanned_trays = sorted(c.args[1] for c in scan.call_args_list)
        self.assertEqual(scanned_trays, ["B005T0011", "B005T0012"])

    def test_has_analysis_badge_uses_cache_table(self):
        # The index reads TrayCsvCache (single DB query), not the SMB
        # filesystem — so a row with non-empty csvs lights up the badge.
        from hwdb.models import TrayCsvCache
        TrayCsvCache.objects.create(
            tray_id="B005T0011",
            dir_mtime=1.0,
            csvs={"002-00001|RT": "002_00001_..._RT.csv"},
        )
        self.addCleanup(TrayCsvCache.objects.all().delete)
        resp = self.client.get(reverse("hwdb:upload_index"))
        self.assertContains(resp, "CSVs")


class UploadTrayTest(TestCase):
    def setUp(self):
        _login(self.client)
        LArASIC.objects.create(
            serial_number="002-00001", tray_id="B005T0011", is_in_hwdb=False
        )

    def test_renders_tray_page(self):
        resp = self.client.get(reverse("hwdb:upload_tray", args=["B005T0011"]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "B005T0011")
        self.assertContains(resp, "002-00001")
        # Default instance is prod; the PROD warning + gauntlet markup must render.
        self.assertContains(resp, "PRODUCTION instance")
        self.assertContains(resp, "Confirm production upload")  # gauntlet modal label
        # No RTS_DIR configured in test settings → no analysis CSVs.
        self.assertContains(resp, "No analysis CSVs")

    def test_dev_session_hides_prod_warning(self):
        self.client.post(reverse("hwdb:set_instance"), {"instance": "dev"})
        resp = self.client.get(reverse("hwdb:upload_tray", args=["B005T0011"]))
        self.assertContains(resp, "Upload this chip")
        self.assertContains(resp, "Upload tray")
        self.assertNotContains(resp, "PRODUCTION instance")


class UploadRunTest(TestCase):
    def setUp(self):
        _login(self.client)
        self.chip = LArASIC.objects.create(
            serial_number="002-00001",
            tray_id="B005T0011",
            is_in_hwdb=False,
            warm_tested_at=datetime(2025, 9, 24, 16, 59, 20, tzinfo=timezone.utc),
        )
        # Default instance is prod; flip to dev for these tests.
        self.client.post(reverse("hwdb:set_instance"), {"instance": "dev"})

    def _ok_result(self):
        return upload_lib.ChipResult(
            serial_number="002-00001",
            part_id="D08100100004-00999",
            created=True,
            tests=[
                upload_lib.TestResult(
                    env="RT", mode="simple", test_id=59921, csv_attached=False, error=None
                )
            ],
        )

    def test_prod_upload_promotes_is_in_hwdb(self):
        # The gauntlet lives client-side (issue #21); server accepts PROD POSTs
        # and updates the prod-scoped is_in_hwdb flag on success (Q10).
        self.client.post(reverse("hwdb:set_instance"), {"instance": "prod"})
        self.assertFalse(self.chip.is_in_hwdb)
        with mock.patch("hwdb.views.mint_for", return_value="b"), \
             mock.patch.object(upload_lib, "resolve_test_type_id", return_value=863), \
             mock.patch.object(upload_lib, "upload_chip", return_value=self._ok_result()):
            resp = self.client.post(reverse("hwdb:upload_run", args=["B005T0011"]))
            body = b"".join(resp.streaming_content).decode()
        self.assertEqual(resp.status_code, 200)
        self.assertIn("qc_tests_uploaded=True on 1 local row", body)
        self.chip.refresh_from_db()
        self.assertTrue(self.chip.is_in_hwdb)
        self.assertTrue(self.chip.qc_tests_uploaded)
        self.assertIsNotNone(self.chip.hwdb_checked_at)

    def test_dev_run_streams_progress(self):
        with mock.patch("hwdb.views.mint_for", return_value="b"), \
             mock.patch.object(
                 upload_lib, "resolve_test_type_id",
                 side_effect=lambda api, ptid, name: 863 if name == "RoomT QC Test" else 864,
             ), \
             mock.patch.object(upload_lib, "upload_chip", return_value=self._ok_result()):
            resp = self.client.post(reverse("hwdb:upload_run", args=["B005T0011"]))
            # The generator is lazy — consume inside the patch context so the
            # mocks are still active when each chunk is produced.
            body = b"".join(resp.streaming_content).decode()
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Starting upload of 1 chip(s)", body)
        self.assertIn("002-00001", body)
        self.assertIn("created D08100100004-00999", body)
        self.assertIn("RT=59921", body)
        self.assertIn("Done. ok=1 failed=0", body)

    def test_single_chip_filter(self):
        # Add a second chip on the same tray; verify chip= narrows the loop.
        LArASIC.objects.create(
            serial_number="002-00002",
            tray_id="B005T0011",
            warm_tested_at=datetime(2025, 9, 24, 17, 0, 0, tzinfo=timezone.utc),
        )
        captured = []

        def fake_upload_chip(api, chip, **kw):
            captured.append(chip.serial_number)
            return self._ok_result()

        with mock.patch("hwdb.views.mint_for", return_value="b"), \
             mock.patch.object(upload_lib, "resolve_test_type_id", return_value=863), \
             mock.patch.object(upload_lib, "upload_chip", side_effect=fake_upload_chip):
            resp = self.client.post(
                reverse("hwdb:upload_run", args=["B005T0011"]),
                {"chip": "002-00001"},
            )
            body = b"".join(resp.streaming_content).decode()
        self.assertEqual(captured, ["002-00001"])
        self.assertIn("Starting upload of 1 chip(s)", body)

    def test_random_5_samples_at_most_five_chips_on_dev(self):
        # Dev-only feasibility-sample button: should pick up to 5 random chips.
        for i in range(2, 12):
            LArASIC.objects.create(
                serial_number=f"002-{i:05d}",
                tray_id="B005T0011",
                warm_tested_at=datetime(2025, 9, 24, 17, 0, i, tzinfo=timezone.utc),
            )
        captured = []

        def fake_upload_chip(api, chip, **kw):
            captured.append(chip.serial_number)
            return self._ok_result()

        with mock.patch("hwdb.views.mint_for", return_value="b"), \
             mock.patch.object(upload_lib, "resolve_test_type_id", return_value=863), \
             mock.patch.object(upload_lib, "upload_chip", side_effect=fake_upload_chip):
            resp = self.client.post(
                reverse("hwdb:upload_run", args=["B005T0011"]),
                {"random_5": "on"},
            )
            body = b"".join(resp.streaming_content).decode()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(captured), 5)
        self.assertIn("Starting upload of 5 chip(s)", body)

    def test_random_5_ignored_on_prod(self):
        # The random_5 sampler is dev-only — on prod the POST falls through to
        # the full tray (so the gauntlet's "type N chips" expectation stays
        # honest).
        for i in range(2, 8):
            LArASIC.objects.create(
                serial_number=f"002-{i:05d}",
                tray_id="B005T0011",
                warm_tested_at=datetime(2025, 9, 24, 17, 0, i, tzinfo=timezone.utc),
            )
        self.client.post(reverse("hwdb:set_instance"), {"instance": "prod"})
        captured = []

        def fake_upload_chip(api, chip, **kw):
            captured.append(chip.serial_number)
            return self._ok_result()

        with mock.patch("hwdb.views.mint_for", return_value="b"), \
             mock.patch.object(upload_lib, "resolve_test_type_id", return_value=863), \
             mock.patch.object(upload_lib, "upload_chip", side_effect=fake_upload_chip):
            resp = self.client.post(
                reverse("hwdb:upload_run", args=["B005T0011"]),
                {"random_5": "on"},
            )
            b"".join(resp.streaming_content)
        # 1 from setUp + 6 added here = 7; random_5 ignored on prod.
        self.assertEqual(len(captured), 7)

    def test_prod_skips_done_chips_by_default(self):
        # A chip whose qc_tests_uploaded is already True should be filtered
        # out of the PROD upload loop — we already confirmed its tests in HWDB.
        LArASIC.objects.create(
            serial_number="002-00002", tray_id="B005T0011",
            is_in_hwdb=True, qc_tests_uploaded=True,
            warm_tested_at=datetime(2025, 9, 24, 17, 0, 0, tzinfo=timezone.utc),
        )
        self.client.post(reverse("hwdb:set_instance"), {"instance": "prod"})
        captured = []

        def fake_upload_chip(api, chip, **kw):
            captured.append(chip.serial_number)
            return self._ok_result()

        with mock.patch("hwdb.views.mint_for", return_value="b"), \
             mock.patch.object(upload_lib, "resolve_test_type_id", return_value=863), \
             mock.patch.object(upload_lib, "upload_chip", side_effect=fake_upload_chip):
            resp = self.client.post(reverse("hwdb:upload_run", args=["B005T0011"]))
            b"".join(resp.streaming_content)
        # Only the not-yet-done chip (002-00001 from setUp) is walked.
        self.assertEqual(captured, ["002-00001"])

    def test_force_walks_done_chips_on_prod(self):
        # With force=on, even chips whose qc_tests_uploaded is True get walked.
        # find_existing_test still dedups on the HWDB side; this is the
        # "be paranoid" escape hatch.
        LArASIC.objects.create(
            serial_number="002-00002", tray_id="B005T0011",
            is_in_hwdb=True, qc_tests_uploaded=True,
            warm_tested_at=datetime(2025, 9, 24, 17, 0, 0, tzinfo=timezone.utc),
        )
        self.client.post(reverse("hwdb:set_instance"), {"instance": "prod"})
        captured = []

        def fake_upload_chip(api, chip, **kw):
            captured.append(chip.serial_number)
            return self._ok_result()

        with mock.patch("hwdb.views.mint_for", return_value="b"), \
             mock.patch.object(upload_lib, "resolve_test_type_id", return_value=863), \
             mock.patch.object(upload_lib, "upload_chip", side_effect=fake_upload_chip):
            resp = self.client.post(
                reverse("hwdb:upload_run", args=["B005T0011"]),
                {"force": "on"},
            )
            b"".join(resp.streaming_content)
        self.assertEqual(sorted(captured), ["002-00001", "002-00002"])

    def test_dev_walks_done_chips_regardless(self):
        # qc_tests_uploaded reflects PROD state — dev should not honor it.
        LArASIC.objects.create(
            serial_number="002-00002", tray_id="B005T0011",
            is_in_hwdb=True, qc_tests_uploaded=True,
            warm_tested_at=datetime(2025, 9, 24, 17, 0, 0, tzinfo=timezone.utc),
        )
        # setUp already flipped to dev.
        captured = []

        def fake_upload_chip(api, chip, **kw):
            captured.append(chip.serial_number)
            return self._ok_result()

        with mock.patch("hwdb.views.mint_for", return_value="b"), \
             mock.patch.object(upload_lib, "resolve_test_type_id", return_value=863), \
             mock.patch.object(upload_lib, "upload_chip", side_effect=fake_upload_chip):
            resp = self.client.post(reverse("hwdb:upload_run", args=["B005T0011"]))
            b"".join(resp.streaming_content)
        self.assertEqual(sorted(captured), ["002-00001", "002-00002"])

    def test_per_chip_button_bypasses_done_filter(self):
        # Clicking "Upload this chip" on a done chip is an explicit opt-in —
        # the server must honor it without requiring Force re-upload.
        LArASIC.objects.create(
            serial_number="002-00002", tray_id="B005T0011",
            is_in_hwdb=True, qc_tests_uploaded=True,
            warm_tested_at=datetime(2025, 9, 24, 17, 0, 0, tzinfo=timezone.utc),
        )
        self.client.post(reverse("hwdb:set_instance"), {"instance": "prod"})
        captured = []

        def fake_upload_chip(api, chip, **kw):
            captured.append(chip.serial_number)
            return self._ok_result()

        with mock.patch("hwdb.views.mint_for", return_value="b"), \
             mock.patch.object(upload_lib, "resolve_test_type_id", return_value=863), \
             mock.patch.object(upload_lib, "upload_chip", side_effect=fake_upload_chip):
            resp = self.client.post(
                reverse("hwdb:upload_run", args=["B005T0011"]),
                {"chip": "002-00002"},
            )
            b"".join(resp.streaming_content)
        self.assertEqual(captured, ["002-00002"])

    def test_link_required_redirects_to_link_page(self):
        from hwdb.fnal.bearer import FnalLinkRequired
        with mock.patch("hwdb.views.mint_for", side_effect=FnalLinkRequired):
            resp = self.client.post(reverse("hwdb:upload_run", args=["B005T0011"]))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/link/", resp["Location"])
