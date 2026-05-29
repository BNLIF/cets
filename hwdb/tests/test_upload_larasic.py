"""Unit tests for hwdb.upload.larasic — no live HTTP, no Django views."""

from __future__ import annotations

import textwrap
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.test import TestCase, override_settings

from hwdb.upload import csv_parser, larasic


# ---- Fixtures -------------------------------------------------------------


def _chip(serial="002-00001", tray="B005T0011", warm=None, cold=None):
    """Minimal stand-in for a LArASIC model row."""
    return SimpleNamespace(
        serial_number=serial,
        tray_id=tray,
        warm_tested_at=warm,
        cold_tested_at=cold,
    )


def _sample_csv(tmp: Path, serial="002_00797", env="RT", ts="20250924165920") -> Path:
    """A minimal Karla-format CSV that the parser fully understands."""
    name = f"{serial}_{ts}_Tray31_SKT6_{env}.csv"
    p = tmp / name
    metadata = textwrap.dedent("""\
        UTC_Time,09_24_2025_16_59_20
        RTS_timestamp,20250924165920
        tester,K. Zucker
        testsite,BNL
        env,RT
        RTS_Property_ID,RTS-7
        Tray_ID,B005T0011
        FE_in_Tray,Tray31
        DAT_SN,DAT-001
        FE_in_Socket,SKT6
        """)
    target_row = (
        "Test_01_Power_Consumption,200mV_sedcBufOFF_seBuffOFF,"
        "vdda_P=31.5,vddo_P=22.1,vddp_P=18.4,"
        + ",".join(
            f"CH{ch}=(ped={600 + ch};rms=5.4;posAmp={3900 + ch};negAmp={595 + ch})"
            for ch in range(16)
        )
    )
    p.write_text(metadata + target_row + "\n")
    return p


# ---- csv_parser ----------------------------------------------------------


class CsvParserTest(TestCase):
    def setUp(self):
        self.tmp = Path(self._mk())

    def _mk(self):
        import tempfile
        d = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, d)
        return d

    def test_extract_serial(self):
        p = self.tmp / "002_00797_x_y_z_RT.csv"
        self.assertEqual(csv_parser.extract_serial(p), "002-00797")

    def test_parse_filename_tokens(self):
        p = self.tmp / "002_00797_20250924165920_Tray31_SKT6_RT.csv"
        out = csv_parser.parse_filename(p)
        self.assertEqual(out["serial"], "002-00797")
        self.assertEqual(out["timestamp"], "20250924165920")
        self.assertEqual(out["tray"], "Tray31")
        self.assertEqual(out["socket"], "SKT6")
        self.assertEqual(out["env"], "RT")

    def test_parse_csv_happy_path(self):
        p = _sample_csv(self.tmp)
        out = csv_parser.parse_csv(p)
        self.assertEqual(out["serial_hwdb"], "002-00797")
        self.assertEqual(out["env"], "RT")
        self.assertEqual(out["test_date"], "2025/09/24")
        self.assertEqual(out["test_time"], "16:59:20")
        self.assertEqual(out["operator_name"], "K. Zucker")
        self.assertEqual(out["test_location"], "BNL")
        self.assertEqual(out["tray_id"], "B005T0011")
        self.assertAlmostEqual(out["power"]["vdda_P"], 31.5)
        self.assertEqual(set(out["channels"].keys()), set(range(16)))
        self.assertAlmostEqual(out["channels"][0]["ped"], 600)

    def test_parse_csv_rejects_missing_target_row(self):
        p = self.tmp / "002_00001_20250924165920_Tray31_SKT6_RT.csv"
        p.write_text("UTC_Time,09_24_2025_16_59_20\n")
        with self.assertRaises(ValueError):
            csv_parser.parse_csv(p)


# ---- find_item / create_item / status / location -------------------------


class FindAndCreateTest(TestCase):
    def test_find_item_hit_returns_full_dict(self):
        # find_item now returns the full component dict (not just part_id) so
        # callers can read qaqc_uploaded and skip redundant PATCHes.
        api = mock.Mock()
        api.find_component_by_serial.return_value = {
            "part_id": "D08100100004-00123",
            "qaqc_uploaded": True,
        }
        out = larasic.find_item(api, "D08100100004", "002-00001")
        self.assertEqual(out["part_id"], "D08100100004-00123")
        self.assertTrue(out["qaqc_uploaded"])

    def test_find_item_miss(self):
        api = mock.Mock()
        api.find_component_by_serial.return_value = None
        self.assertIsNone(larasic.find_item(api, "D08100100004", "002-00001"))

    def test_create_item_payload_shape(self):
        api = mock.Mock()
        api.create_component.return_value = {
            "status": "OK", "part_id": "D08100100004-00999",
        }
        chip = _chip(serial="002-00001", tray="B005T0011")
        defaults = larasic._larasic_defaults("dev")
        part_id = larasic.create_item(api, chip, "D08100100004", defaults)
        self.assertEqual(part_id, "D08100100004-00999")
        # Inspect the exact payload sent
        sent_part_type, sent_payload = api.create_component.call_args.args
        self.assertEqual(sent_part_type, "D08100100004")
        self.assertEqual(sent_payload["component_type"], {"part_type_id": "D08100100004"})
        self.assertEqual(sent_payload["serial_number"], "002-00001")
        self.assertEqual(sent_payload["country_code"], "US")
        self.assertEqual(sent_payload["institution"], {"id": 128})
        self.assertEqual(sent_payload["manufacturer"], {"id": 59})
        self.assertEqual(sent_payload["specifications"]["DATA"]["LOT N"], "B005T0011")
        # Status is now embedded (probe 1) so the create finishes the
        # "fresh chip" setup in one call — no separate set_status PATCH.
        self.assertEqual(sent_payload["status"], {"id": 110})

    def test_create_item_prod_uses_prod_manufacturer_id(self):
        # TSMC manufacturer_id differs per HWDB instance (prod=15, dev=59,
        # confirmed via .idea/spike/hwdb_id_compare.py). The create payload
        # must honor the active instance.
        api = mock.Mock()
        api.create_component.return_value = {
            "status": "OK", "part_id": "D08100100003-00777",
        }
        larasic.create_item(
            api, _chip(serial="002-00001", tray="B005T0011"),
            "D08100100003", larasic._larasic_defaults("prod"),
        )
        _, sent = api.create_component.call_args.args
        self.assertEqual(sent["manufacturer"], {"id": 15})

    def test_create_item_propagates_hwdb_error(self):
        api = mock.Mock()
        api.create_component.return_value = {
            "status": "ERROR", "data": "Not authorized: no suitable roles",
        }
        with self.assertRaises(larasic.UploadError) as ctx:
            larasic.create_item(api, _chip(), "D08100100004", larasic._larasic_defaults("dev"))
        self.assertIn("no suitable roles", str(ctx.exception))

    def test_set_status_minimal_patch_body(self):
        # Slim PATCH: part_id + the changed field, no specifications. HWDB's
        # spec history should record actual spec changes only, not every patch.
        api = mock.Mock()
        api.patch_component.return_value = {"status": "OK"}
        larasic.set_status(api, "D08100100004-00999", 110)
        api.patch_component.assert_called_once_with(
            "D08100100004-00999",
            {"part_id": "D08100100004-00999", "status": {"id": 110}},
        )

    def test_set_qaqc_uploaded_minimal_patch_body(self):
        api = mock.Mock()
        api.patch_component.return_value = {"status": "OK"}
        larasic.set_qaqc_uploaded(api, "D08100100004-00999")
        api.patch_component.assert_called_once_with(
            "D08100100004-00999",
            {"part_id": "D08100100004-00999", "qaqc_uploaded": True},
        )

    def test_set_location_payload(self):
        api = mock.Mock()
        api.post_location.return_value = {"status": "OK"}
        dt = datetime(2026, 5, 28, 12, 0, 0, tzinfo=timezone.utc)
        larasic.set_location(api, "D08100100004-00999", 128, dt)
        api.post_location.assert_called_once()
        sent_part_id, sent_payload = api.post_location.call_args.args
        self.assertEqual(sent_part_id, "D08100100004-00999")
        self.assertEqual(sent_payload["location"], {"id": 128})
        self.assertEqual(sent_payload["arrived"], "2026-05-28 12:00:00")


# ---- test post + datasheets ----------------------------------------------


class TestPostTest(TestCase):
    def test_post_test_returns_id(self):
        api = mock.Mock()
        api.post_test.return_value = {"status": "OK", "test_id": 59920}
        out = larasic.post_test(api, "D08100100004-00999", "RoomT QC Test", {"x": 1}, "c")
        self.assertEqual(out, 59920)
        sent_part_id, sent_payload = api.post_test.call_args.args
        self.assertEqual(sent_payload["test_type"], "RoomT QC Test")
        self.assertEqual(sent_payload["comments"], "c")
        self.assertEqual(sent_payload["test_data"], {"x": 1})

    def test_post_test_error_raises(self):
        api = mock.Mock()
        api.post_test.return_value = {"status": "ERROR", "data": "bad"}
        with self.assertRaises(larasic.UploadError):
            larasic.post_test(api, "p", "RoomT QC Test", {}, "c")


class DatasheetTest(TestCase):
    def test_simple_warm(self):
        chip = _chip(warm=datetime(2025, 9, 24, 16, 59, 20, tzinfo=timezone.utc))
        sheet = larasic.build_datasheet_simple(chip, "RT", operator_name="chaoz")
        self.assertEqual(sheet["Test Date"], "2025/09/24")
        self.assertEqual(sheet["Test Time"], "16:59:20")
        self.assertEqual(sheet["LArASIC Serial Number"], "002-00001")
        self.assertEqual(sheet["Test Location"], "BNL")
        self.assertEqual(sheet["Operator Name"], "chaoz")
        self.assertEqual(sheet["Environment"], "RT")
        self.assertEqual(sheet["Tray ID"], "B005T0011")
        # Skipped (no analysis CSV → don't fake values for these):
        self.assertNotIn("Test Result", sheet)
        self.assertNotIn("Test Item", sheet)
        self.assertNotIn("Configuration", sheet)
        # 4 schema-required fields + 3 traceability extras = 7.
        self.assertEqual(len(sheet), 7)

    def test_simple_operator_defaults_to_na(self):
        chip = _chip(warm=datetime(2025, 9, 24, 16, 59, 20, tzinfo=timezone.utc))
        sheet = larasic.build_datasheet_simple(chip, "RT")
        # The schema requires Operator Name — never omitted, falls back to "N/A".
        self.assertEqual(sheet["Operator Name"], "N/A")

    def test_simple_missing_timestamp(self):
        chip = _chip(warm=None)
        with self.assertRaises(larasic.UploadError):
            larasic.build_datasheet_simple(chip, "RT")

    def test_detailed_field_count_and_shape(self):
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, str(tmp))
        p = _sample_csv(tmp)
        chip = _chip(serial="002-00797", tray="B005T0011")
        sheet = larasic.build_datasheet_detailed(chip, p)
        # 19 header fields + 48 (16ch × 3) = 67
        self.assertEqual(len(sheet), 67)
        self.assertEqual(sheet["Test Date"], "2025/09/24")
        self.assertEqual(sheet["Operator Name"], "K. Zucker")
        self.assertEqual(sheet["Test Result"], "PASS")
        self.assertAlmostEqual(sheet["Power Consumption"], 31.5 + 22.1 + 18.4, places=4)
        self.assertEqual(sheet["CH0 Pedestal"], 600)
        self.assertAlmostEqual(sheet["CH5 Pulse Amplitude"], (3900 + 5) - (600 + 5))


# ---- orchestrator --------------------------------------------------------


class UploadChipTest(TestCase):
    def _api(self, *, existing=None, test_type_ids=None, existing_tests=None):
        """Build a mock api client returning sensible defaults.

        ``existing_tests`` is the body returned by ``get_tests(...)``; defaults
        to an empty list (no dedup hit).
        """
        api = mock.Mock()
        api.find_component_by_serial.return_value = existing
        api.create_component.return_value = {"status": "OK", "part_id": "D08100100004-00999"}
        api.patch_component.return_value = {"status": "OK"}
        api.post_location.return_value = {"status": "OK"}
        api.post_test.side_effect = [
            {"status": "OK", "test_id": 59921},
            {"status": "OK", "test_id": 59922},
        ]
        api.get_tests.return_value = existing_tests or {"data": []}
        api.get_test_types.return_value = {
            "data": [
                {"name": "RoomT QC Test", "id": 863},
                {"name": "CryoT QC Test", "id": 864},
            ]
        }
        return api

    def test_happy_path_new_chip_warm_only(self):
        api = self._api()
        chip = _chip(warm=datetime(2025, 9, 24, 16, 59, 20, tzinfo=timezone.utc))
        result = larasic.upload_chip(api, chip, part_type_id="D08100100004", instance="dev", rts_root=None)
        self.assertTrue(result.ok, result)
        self.assertTrue(result.created)
        self.assertEqual(result.part_id, "D08100100004-00999")
        self.assertEqual(len(result.tests), 1)
        self.assertEqual(result.tests[0].env, "RT")
        self.assertEqual(result.tests[0].mode, "simple")
        self.assertEqual(result.tests[0].test_id, 59921)
        self.assertFalse(result.tests[0].csv_attached)
        # Call sequence: find → create (status embedded) → location → test.
        # No qaqc PATCH for a simple-mode-only upload (interpretation B —
        # qaqc_uploaded means "CSV-backed analysis is in HWDB").
        self.assertEqual(api.find_component_by_serial.call_count, 1)
        self.assertEqual(api.create_component.call_count, 1)
        self.assertEqual(api.post_location.call_count, 1)
        self.assertEqual(api.post_test.call_count, 1)
        self.assertEqual(api.attach_test_image.call_count, 0)
        api.patch_component.assert_not_called()

    def test_warm_and_cold_both_posted(self):
        api = self._api()
        chip = _chip(
            warm=datetime(2025, 9, 24, 16, 59, 20, tzinfo=timezone.utc),
            cold=datetime(2025, 9, 24, 18, 1, 0, tzinfo=timezone.utc),
        )
        result = larasic.upload_chip(api, chip, part_type_id="D08100100004", instance="dev", rts_root=None)
        self.assertTrue(result.ok, result)
        self.assertEqual([t.env for t in result.tests], ["RT", "LN"])
        self.assertEqual(api.post_test.call_count, 2)

    def test_existing_chip_skips_create_and_location(self):
        api = self._api(existing={"part_id": "D08100100004-00042"})
        chip = _chip(warm=datetime(2025, 9, 24, 16, 59, 20, tzinfo=timezone.utc))
        result = larasic.upload_chip(api, chip, part_type_id="D08100100004", instance="dev", rts_root=None)
        self.assertTrue(result.ok, result)
        self.assertFalse(result.created)
        self.assertEqual(result.part_id, "D08100100004-00042")
        api.create_component.assert_not_called()
        api.post_location.assert_not_called()
        self.assertEqual(api.post_test.call_count, 1)
        # Simple-mode posts don't flip qaqc_uploaded (interpretation B).
        api.patch_component.assert_not_called()

    def test_create_failure_aborts_chip_with_no_tests(self):
        api = self._api()
        api.create_component.return_value = {"status": "ERROR", "data": "no role"}
        chip = _chip(warm=datetime(2025, 9, 24, 16, 59, 20, tzinfo=timezone.utc))
        result = larasic.upload_chip(api, chip, part_type_id="D08100100004", instance="dev", rts_root=None)
        self.assertFalse(result.ok)
        self.assertIn("no role", result.error)
        self.assertEqual(result.tests, [])
        api.post_test.assert_not_called()

    def test_test_post_failure_doesnt_block_other_env(self):
        api = self._api()
        api.post_test.side_effect = [
            {"status": "ERROR", "data": "validation"},
            {"status": "OK", "test_id": 59922},
        ]
        chip = _chip(
            warm=datetime(2025, 9, 24, 16, 59, 20, tzinfo=timezone.utc),
            cold=datetime(2025, 9, 24, 18, 1, 0, tzinfo=timezone.utc),
        )
        result = larasic.upload_chip(api, chip, part_type_id="D08100100004", instance="dev", rts_root=None)
        self.assertFalse(result.ok)
        self.assertEqual(result.tests[0].error and "validation" in result.tests[0].error, True)
        self.assertEqual(result.tests[1].error, None)
        self.assertEqual(result.tests[1].test_id, 59922)

    def test_skipped_tests_do_not_trigger_qaqc_patch(self):
        # Re-running a chip whose tests are already in HWDB: tests are skipped
        # via find_existing_test. The qaqc PATCH must NOT fire — otherwise
        # we'd add a fresh specifications history entry on every re-run.
        chip = _chip(
            serial="002-00001",
            warm=datetime(2025, 9, 24, 16, 59, 20, tzinfo=timezone.utc),
        )
        existing_tests = {
            "data": [
                {
                    "id": 59920,
                    "test_data": {"Test Date": "2025/09/24", "Test Time": "16:59:20"},
                }
            ]
        }
        api = self._api(existing={"part_id": "D08100100004-00042"}, existing_tests=existing_tests)
        result = larasic.upload_chip(api, chip, part_type_id="D08100100004", instance="dev", rts_root=None)
        self.assertTrue(result.ok, result)
        self.assertTrue(result.tests[0].skipped)
        api.patch_component.assert_not_called()
        api.post_test.assert_not_called()

    def test_skips_test_post_when_existing_match_found(self):
        # Probe 3 (2026-05-28): HWDB does not dedup test POSTs server-side; a
        # second POST with the same (type, date, time) creates a duplicate.
        # upload_chip must check before posting.
        chip = _chip(
            serial="002-00001",
            warm=datetime(2025, 9, 24, 16, 59, 20, tzinfo=timezone.utc),
        )
        existing_tests = {
            "data": [
                {
                    "id": 59920,
                    "test_data": {
                        "Test Date": "2025/09/24",
                        "Test Time": "16:59:20",
                    },
                }
            ]
        }
        api = self._api(existing={"part_id": "D08100100004-00042"}, existing_tests=existing_tests)
        result = larasic.upload_chip(api, chip, part_type_id="D08100100004", instance="dev", rts_root=None)
        self.assertTrue(result.ok, result)
        self.assertEqual(len(result.tests), 1)
        self.assertTrue(result.tests[0].skipped)
        self.assertEqual(result.tests[0].mode, "skipped")
        self.assertEqual(result.tests[0].test_id, 59920)
        api.post_test.assert_not_called()

    def test_csv_detected_uses_detailed_mode_and_attaches(self):
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, str(tmp))
        rts_root = tmp
        tray = "B005T0011"
        (tmp / tray / "results").mkdir(parents=True)
        _sample_csv(tmp / tray / "results", serial="002_00797")

        api = self._api()
        api.attach_test_image.return_value = {"status": "OK", "image_id": 1}
        chip = _chip(
            serial="002-00797",
            tray=tray,
            warm=datetime(2025, 9, 24, 16, 59, 20, tzinfo=timezone.utc),
        )
        result = larasic.upload_chip(
            api, chip, part_type_id="D08100100004", instance="dev", rts_root=rts_root
        )
        self.assertTrue(result.ok, result)
        self.assertEqual(result.tests[0].mode, "detailed")
        self.assertTrue(result.tests[0].csv_attached)
        api.attach_test_image.assert_called_once()
        # Detailed-mode posts DO flip qaqc_uploaded — real analysis is in HWDB.
        self.assertEqual(api.patch_component.call_count, 1)
        _, qaqc_payload = api.patch_component.call_args.args
        self.assertTrue(qaqc_payload["qaqc_uploaded"])

    def test_qaqc_patch_skipped_when_flag_already_true(self):
        # Existing chip with qaqc_uploaded=True + detailed-mode test posted:
        # the flag is already set, so we must NOT re-PATCH (HWDB would create
        # another spec-history snapshot).
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, str(tmp))
        rts_root = tmp
        tray = "B005T0011"
        (tmp / tray / "results").mkdir(parents=True)
        _sample_csv(tmp / tray / "results", serial="002_00797")

        api = self._api(
            existing={"part_id": "D08100100004-00042", "qaqc_uploaded": True},
        )
        api.attach_test_image.return_value = {"status": "OK", "image_id": 1}
        chip = _chip(
            serial="002-00797",
            tray=tray,
            warm=datetime(2025, 9, 24, 16, 59, 20, tzinfo=timezone.utc),
        )
        result = larasic.upload_chip(
            api, chip, part_type_id="D08100100004", instance="dev", rts_root=rts_root
        )
        self.assertTrue(result.ok, result)
        self.assertEqual(result.tests[0].mode, "detailed")
        # The detailed test was posted (api.post_test called once), but
        # patch_component MUST NOT be called — the flag is already True.
        self.assertEqual(api.post_test.call_count, 1)
        api.patch_component.assert_not_called()


# ---- resolve_test_type_id ------------------------------------------------


class ScanTrayCsvsTest(TestCase):
    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, str(self.tmp))
        larasic.clear_csv_cache()
        self.addCleanup(larasic.clear_csv_cache)

    def test_tray_has_analysis(self):
        self.assertFalse(larasic.tray_has_analysis(self.tmp, "B005T0011"))
        (self.tmp / "B005T0011" / "results").mkdir(parents=True)
        self.assertTrue(larasic.tray_has_analysis(self.tmp, "B005T0011"))

    def test_tray_has_analysis_none_root(self):
        self.assertFalse(larasic.tray_has_analysis(None, "B005T0011"))

    def test_scan_tray_csvs_empty(self):
        self.assertEqual(larasic.scan_tray_csvs(self.tmp, "B005T0011"), {})

    def test_scan_tray_csvs_collects_rt_and_ln(self):
        results = self.tmp / "B005T0011" / "results"
        results.mkdir(parents=True)
        rt = _sample_csv(results, serial="002_00797", env="RT")
        ln = _sample_csv(results, serial="002_00798", env="LN")
        out = larasic.scan_tray_csvs(self.tmp, "B005T0011")
        self.assertEqual(set(out.keys()), {("002-00797", "RT"), ("002-00798", "LN")})
        self.assertEqual(out[("002-00797", "RT")], rt)
        self.assertEqual(out[("002-00798", "LN")], ln)

    def test_scan_tray_csvs_skips_malformed_filenames(self):
        results = self.tmp / "B005T0011" / "results"
        results.mkdir(parents=True)
        (results / "garbage.csv").write_text("")  # no serial pattern
        (results / "002_00797_20250924165920_Tray31_SKT6_RT.csv").write_text("")
        out = larasic.scan_tray_csvs(self.tmp, "B005T0011")
        self.assertEqual(set(out.keys()), {("002-00797", "RT")})

    def test_scan_tray_csvs_caches_by_mtime(self):
        from unittest import mock
        results = self.tmp / "B005T0011" / "results"
        results.mkdir(parents=True)
        _sample_csv(results, serial="002_00797", env="RT")

        with mock.patch.object(
            larasic, "_scan_results_dir", wraps=larasic._scan_results_dir
        ) as scan_spy:
            larasic.scan_tray_csvs(self.tmp, "B005T0011")
            self.assertEqual(scan_spy.call_count, 1)
            # Same mtime, second call: hit cache, no rescan.
            larasic.scan_tray_csvs(self.tmp, "B005T0011")
            self.assertEqual(scan_spy.call_count, 1)

    def test_scan_tray_csvs_rescans_when_dir_changes(self):
        import os, time
        from unittest import mock
        results = self.tmp / "B005T0011" / "results"
        results.mkdir(parents=True)
        _sample_csv(results, serial="002_00797", env="RT")

        with mock.patch.object(
            larasic, "_scan_results_dir", wraps=larasic._scan_results_dir
        ) as scan_spy:
            first = larasic.scan_tray_csvs(self.tmp, "B005T0011")
            self.assertEqual(len(first), 1)
            # Add another CSV and bump the dir mtime explicitly (sub-second
            # filesystem resolution would otherwise hide the change in tests).
            _sample_csv(results, serial="002_00798", env="LN")
            os.utime(results, (time.time() + 5, time.time() + 5))
            second = larasic.scan_tray_csvs(self.tmp, "B005T0011")
            self.assertEqual(len(second), 2)
            self.assertEqual(scan_spy.call_count, 2)

    def test_scan_tray_csvs_drops_stale_entry_when_dir_removed(self):
        import shutil
        results = self.tmp / "B005T0011" / "results"
        results.mkdir(parents=True)
        _sample_csv(results, serial="002_00797", env="RT")
        larasic.scan_tray_csvs(self.tmp, "B005T0011")
        self.assertIn("B005T0011", larasic._csv_cache)
        shutil.rmtree(results)
        self.assertEqual(larasic.scan_tray_csvs(self.tmp, "B005T0011"), {})
        self.assertNotIn("B005T0011", larasic._csv_cache)

    def test_l2_cache_persists_across_l1_clear(self):
        # The DB-backed cache should survive a process restart, modeled here
        # by clearing the in-memory L1. Second call hits L2, no filesystem
        # rescan.
        from unittest import mock
        from hwdb.models import TrayCsvCache
        TrayCsvCache.objects.all().delete()
        self.addCleanup(TrayCsvCache.objects.all().delete)

        results = self.tmp / "B005T0011" / "results"
        results.mkdir(parents=True)
        _sample_csv(results, serial="002_00797", env="RT")

        # First call: rescans, populates L1 + L2.
        with mock.patch.object(
            larasic, "_scan_results_dir", wraps=larasic._scan_results_dir
        ) as scan_spy:
            larasic.scan_tray_csvs(self.tmp, "B005T0011")
            self.assertEqual(scan_spy.call_count, 1)
        self.assertEqual(TrayCsvCache.objects.count(), 1)

        # Simulate restart: clear L1. L2 row remains.
        larasic.clear_csv_cache()

        # Second call: L1 miss, L2 hit, no rescan.
        with mock.patch.object(
            larasic, "_scan_results_dir", wraps=larasic._scan_results_dir
        ) as scan_spy:
            out = larasic.scan_tray_csvs(self.tmp, "B005T0011")
            self.assertEqual(scan_spy.call_count, 0)
        self.assertEqual(set(out.keys()), {("002-00797", "RT")})

    def test_trays_with_analysis_uses_l2_only(self):
        # Index-page batch query: zero SMB stats, just one DB read. Verify it
        # picks up trays with populated rows and ignores empty ones.
        from hwdb.models import TrayCsvCache
        TrayCsvCache.objects.all().delete()
        self.addCleanup(TrayCsvCache.objects.all().delete)
        TrayCsvCache.objects.create(
            tray_id="B005T0011",
            dir_mtime=1.0,
            csvs={"002-00797|RT": "002_00797_..._RT.csv"},
        )
        TrayCsvCache.objects.create(  # empty results/ — excluded
            tray_id="B005T0012", dir_mtime=1.0, csvs={},
        )
        out = larasic.trays_with_analysis(["B005T0011", "B005T0012", "B005T9999"])
        self.assertEqual(out, {"B005T0011"})

    def test_l2_cache_invalidates_on_dir_removal(self):
        from hwdb.models import TrayCsvCache
        TrayCsvCache.objects.all().delete()
        self.addCleanup(TrayCsvCache.objects.all().delete)
        results = self.tmp / "B005T0011" / "results"
        results.mkdir(parents=True)
        _sample_csv(results, serial="002_00797", env="RT")
        larasic.scan_tray_csvs(self.tmp, "B005T0011")
        self.assertEqual(TrayCsvCache.objects.count(), 1)

        import shutil
        shutil.rmtree(results)
        larasic.scan_tray_csvs(self.tmp, "B005T0011")
        self.assertEqual(TrayCsvCache.objects.count(), 0)


class ResolveTestTypeIdTest(TestCase):
    def test_finds_by_name(self):
        api = mock.Mock()
        api.get_test_types.return_value = {
            "data": [
                {"name": "RoomT QC Test", "id": 863},
                {"name": "CryoT QC Test", "id": 864},
            ]
        }
        self.assertEqual(
            larasic.resolve_test_type_id(api, "D08100100004", "RoomT QC Test"), 863
        )

    def test_raises_if_missing(self):
        api = mock.Mock()
        api.get_test_types.return_value = {"data": []}
        with self.assertRaises(larasic.UploadError):
            larasic.resolve_test_type_id(api, "D08100100004", "RoomT QC Test")


# ---- parallel orchestrator -----------------------------------------------


class IterUploadChipsParallelTest(TestCase):
    """The orchestrator hands each thread its own client (from the factory),
    runs upload_chip in parallel, and yields (chip, ChipResult) tuples in
    completion order with continue-on-error semantics."""

    def _make_api(self):
        api = mock.Mock()
        api.find_component_by_serial.return_value = None
        # Each post_test call returns a fresh id — irrelevant here, just
        # avoid the side_effect-runs-out exception.
        api.create_component.side_effect = lambda *a, **k: {
            "status": "OK", "part_id": f"PID-{id(a)}",
        }
        api.post_location.return_value = {"status": "OK"}
        api.post_test.return_value = {"status": "OK", "test_id": 1}
        api.get_tests.return_value = {"data": []}
        return api

    def test_yields_one_result_per_chip(self):
        chips = [
            _chip(serial=f"002-{i:05d}",
                  warm=datetime(2025, 9, 24, 16, i, 0, tzinfo=timezone.utc))
            for i in range(5)
        ]
        clients_made = []

        def factory():
            api = self._make_api()
            clients_made.append(api)
            return api

        out = list(larasic.iter_upload_chips_parallel(
            chips,
            client_factory=factory,
            part_type_id="D08100100004",
            instance="dev",
            test_type_ids={"RT": 863, "LN": 864},
            workers=3,
        ))

        # 5 chips → 5 results, all distinct chips covered
        self.assertEqual(len(out), 5)
        self.assertEqual({c.serial_number for c, _ in out},
                         {ch.serial_number for ch in chips})
        # Each worker thread builds its own client; 3 workers → at most 3
        # factory invocations.
        self.assertLessEqual(len(clients_made), 3)
        self.assertGreaterEqual(len(clients_made), 1)

    def test_continue_on_per_chip_crash(self):
        chips = [
            _chip(serial="002-00001",
                  warm=datetime(2025, 9, 24, 16, 0, 0, tzinfo=timezone.utc)),
            _chip(serial="002-00002",
                  warm=datetime(2025, 9, 24, 16, 1, 0, tzinfo=timezone.utc)),
        ]
        # First chip's create blows up; second chip's path is fine. Both
        # results must still be yielded.
        def factory():
            api = self._make_api()
            api.find_component_by_serial.side_effect = (
                lambda part_type_id, sn:
                    (_ for _ in ()).throw(RuntimeError("boom"))
                    if sn == "002-00001" else None
            )
            return api

        out = list(larasic.iter_upload_chips_parallel(
            chips,
            client_factory=factory,
            part_type_id="D08100100004",
            instance="dev",
            test_type_ids={"RT": 863, "LN": 864},
            workers=2,
        ))
        self.assertEqual(len(out), 2)
        by_sn = {c.serial_number: r for c, r in out}
        self.assertIsNotNone(by_sn["002-00001"].error)
        self.assertIsNone(by_sn["002-00002"].error)
