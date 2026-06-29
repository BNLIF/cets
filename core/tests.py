import tempfile
import textwrap
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings

from cets.testutils import make_cets_user

from core.management.commands.update_fembs_from_ocr import (
    components_to_state,
    compute_repair_diff,
    parse_inspection_note,
    parse_parts_file,
)
from core.management.commands.update_larasics_from_rts import (
    parse_sn_folder,
    parse_time_folder,
    scan_batch,
)
from core.models import CABLE, COLDATA, FEMB, ColdADC, LArASIC


class ComponentsToStateTests(SimpleTestCase):
    def test_keys_by_type_and_position(self):
        components = [
            {"type": "LArASIC", "serial_number": "FE-1", "position": "F1"},
            {"type": "ColdADC", "serial_number": "ADC-1", "position": "F1"},
            {"type": "COLDATA", "serial_number": "CD-1", "position": "F1"},
        ]
        state = components_to_state(components)
        # Same position label must NOT collide across chip types.
        self.assertEqual(state[("LArASIC", "F1")], "FE-1")
        self.assertEqual(state[("ColdADC", "F1")], "ADC-1")
        self.assertEqual(state[("COLDATA", "F1")], "CD-1")

    def test_drops_components_with_blank_position(self):
        components = [
            {"type": "LArASIC", "serial_number": "FE-1", "position": ""},
            {"type": "LArASIC", "serial_number": "FE-2", "position": "F1"},
        ]
        self.assertEqual(components_to_state(components), {("LArASIC", "F1"): "FE-2"})


class ComputeRepairDiffTests(SimpleTestCase):
    def _fe(self, sn, pos):
        return {"type": "LArASIC", "serial_number": sn, "position": pos}

    def test_no_change(self):
        before = [self._fe("FE-A", "F1"), self._fe("FE-B", "F2")]
        removed, added = compute_repair_diff(before, before)
        self.assertEqual(removed, [])
        self.assertEqual(added, [])

    def test_pure_removal(self):
        before = [self._fe("FE-A", "F1"), self._fe("FE-B", "F2")]
        after = [self._fe("FE-A", "F1")]
        removed, added = compute_repair_diff(before, after)
        self.assertEqual(removed, [self._fe("FE-B", "F2")])
        self.assertEqual(added, [])

    def test_pure_addition(self):
        before = [self._fe("FE-A", "F1")]
        after = [self._fe("FE-A", "F1"), self._fe("FE-B", "F2")]
        removed, added = compute_repair_diff(before, after)
        self.assertEqual(removed, [])
        self.assertEqual(added, [self._fe("FE-B", "F2")])

    def test_swap_at_same_position(self):
        before = [self._fe("FE-OLD", "F1")]
        after = [self._fe("FE-NEW", "F1")]
        removed, added = compute_repair_diff(before, after)
        self.assertEqual(removed, [self._fe("FE-OLD", "F1")])
        self.assertEqual(added, [self._fe("FE-NEW", "F1")])

    def test_same_position_label_different_chip_types_do_not_collide(self):
        # LArASIC at F1 swapped, ColdADC at F1 unchanged — must not report the
        # ColdADC as removed just because a LArASIC shares its position label.
        before = [self._fe("FE-OLD", "F1"), {"type": "ColdADC", "serial_number": "ADC-1", "position": "F1"}]
        after = [self._fe("FE-NEW", "F1"), {"type": "ColdADC", "serial_number": "ADC-1", "position": "F1"}]
        removed, added = compute_repair_diff(before, after)
        self.assertEqual(removed, [self._fe("FE-OLD", "F1")])
        self.assertEqual(added, [self._fe("FE-NEW", "F1")])


class ParsePartsFileTests(SimpleTestCase):
    def _write(self, content):
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
        tmp.write(textwrap.dedent(content).lstrip("\n"))
        tmp.close()
        return Path(tmp.name)

    def test_real_sample_format(self):
        path = self._write("""
            "FEMB", "BNL/FEMB/IO-1865-1K/00016"
            "(F) COLDATA 1 SN", "2506-03219"
            "(F) ColdADC 1 SN", "2502-18564"
            "(F) LArASIC 1 SN", "009-05061"
            "(B) LArASIC 4 SN", "009-06576"
        """)
        version, sn, components = parse_parts_file(str(path))
        self.assertEqual(version, "IO-1865-1K")
        self.assertEqual(sn, "00016")
        self.assertIn({"type": "COLDATA", "serial_number": "2506-03219", "position": "F1"}, components)
        self.assertIn({"type": "ColdADC", "serial_number": "2502-18564", "position": "F1"}, components)
        self.assertIn({"type": "LArASIC", "serial_number": "009-05061", "position": "F1"}, components)
        self.assertIn({"type": "LArASIC", "serial_number": "009-06576", "position": "B4"}, components)
        self.assertEqual(len(components), 4)

    def test_missing_femb_header_returns_empty(self):
        path = self._write("""
            "(F) LArASIC 1 SN", "009-05061"
        """)
        version, sn, components = parse_parts_file(str(path))
        self.assertIsNone(version)
        self.assertIsNone(sn)
        self.assertEqual(components, [])

    def test_nonexistent_file(self):
        self.assertEqual(parse_parts_file("/no/such/file.txt"), (None, None, []))


class ParseInspectionNoteTests(SimpleTestCase):
    def _write(self, content):
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
        tmp.write(textwrap.dedent(content).lstrip("\n"))
        tmp.close()
        return Path(tmp.name)

    def test_real_sample_format(self):
        path = self._write("""
            FEMB SN: BNL/FEMB/IO-1865-1L/00032
            Batch ID: 03192026
            Inspection Type: repair
            Inspection/Repair Iteration Number: 1
            Date: 2026-03-31 10:19:28
            Operator Name: lke
            What was fixed: replaced larasic chip
            Comments:
        """)
        note = parse_inspection_note(str(path))
        self.assertEqual(note["femb_sn"], "BNL/FEMB/IO-1865-1L/00032")
        self.assertEqual(note["batch_id"], "03192026")
        self.assertEqual(note["iteration_number"], 1)
        self.assertEqual(note["operator"], "lke")
        self.assertEqual(note["what_was_fixed"], "replaced larasic chip")
        self.assertEqual(note["comments"], "")
        self.assertIsNotNone(note["date"])
        self.assertEqual(note["date"].year, 2026)

    def test_bad_date_is_ignored(self):
        path = self._write("""
            FEMB SN: BNL/FEMB/IO-1865-1L/00099
            Date: not-a-date
        """)
        note = parse_inspection_note(str(path))
        self.assertEqual(note["femb_sn"], "BNL/FEMB/IO-1865-1L/00099")
        self.assertIsNone(note["date"])


@override_settings(ALLOWED_HOSTS=["*"])
class ViewSmokeTests(TestCase):
    """
    GET each public page as an authenticated user and assert it renders.
    Catches template errors, broken URL reverses, and missing ORM fields
    after refactors. Does NOT assert on content — that's the job of
    targeted view tests, not smoke tests.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = make_cets_user(username="smoketest")
        cls.femb = FEMB.objects.create(version="IO-1865-1K", serial_number="00001")
        cls.larasic = LArASIC.objects.create(
            serial_number="009-00001", femb=cls.femb, femb_pos="F1", status="on-femb",
        )
        cls.coldadc = ColdADC.objects.create(
            serial_number="2502-00001", femb=cls.femb, femb_pos="F1", status="on-femb",
        )
        cls.coldata = COLDATA.objects.create(
            serial_number="2506-00001", femb=cls.femb, femb_pos="F1", status="on-femb",
        )
        cls.cable = CABLE.objects.create(serial_number="CBL-00001")

    def setUp(self):
        self.client.force_login(self.user)

    def test_list_pages_render(self):
        for url in [
            "/",
            "/larasic/",
            "/coldadc/",
            "/coldata/",
            "/femb/",
            "/cable/",
            "/reference/",
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_femb_detail_renders_with_chips(self):
        # Exercises femb.larasic_set / coldadc_set / coldata_set reverse
        # accessors and the prefetch_related on repairs.
        url = f"/femb/{self.femb.version}/{self.femb.serial_number}/"
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_chip_detail_pages_render(self):
        cases = [
            f"/larasic/{self.larasic.serial_number}/",
            f"/coldadc/{self.coldadc.serial_number}/",
            f"/coldata/{self.coldata.serial_number}/",
            f"/cable/{self.cable.serial_number}/",
        ]
        for url in cases:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_legacy_fe_path_redirects(self):
        r = self.client.get(f"/fe/{self.larasic.serial_number}/")
        self.assertEqual(r.status_code, 301)
        self.assertTrue(r["Location"].endswith(f"/larasic/{self.larasic.serial_number}/"))

    def test_legacy_adc_path_redirects(self):
        r = self.client.get(f"/adc/{self.coldadc.serial_number}/")
        self.assertEqual(r.status_code, 301)
        self.assertTrue(r["Location"].endswith(f"/coldadc/{self.coldadc.serial_number}/"))


def _mkrts(tmp: Path, tree: dict) -> Path:
    """Materialize an RTS fixture tree from a nested dict of folder names.

    tree = {
        "B002T0001": {
            "Time_20250813095435": ["RT_FE_002004605_..._002004616", "LN_FE_..."],
            ...
        },
        ...
    }
    """
    for batch_name, sessions in tree.items():
        batch = tmp / batch_name
        batch.mkdir()
        for session_name, subs in sessions.items():
            session = batch / session_name
            session.mkdir()
            for sub in subs:
                (session / sub).mkdir()
    return tmp


class ParseTimeFolderTests(SimpleTestCase):
    def test_valid_timestamp(self):
        dt = parse_time_folder("Time_20250813095435")
        self.assertEqual(dt, datetime(2025, 8, 13, 9, 54, 35, tzinfo=timezone.utc))

    def test_with_dut_suffix(self):
        dt = parse_time_folder("Time_20250813095435_DUT_0000_1001_2002")
        self.assertEqual(dt, datetime(2025, 8, 13, 9, 54, 35, tzinfo=timezone.utc))

    def test_invalid(self):
        self.assertIsNone(parse_time_folder("notatime"))
        self.assertIsNone(parse_time_folder("Time_99999999999999"))


class ParseSnFolderTests(SimpleTestCase):
    def test_full_8_chips(self):
        sns = parse_sn_folder(
            "RT_FE_002004605_002004606_002004607_002004608_"
            "002004613_002004614_002004615_002004616",
            "RT_FE_",
        )
        self.assertEqual(len(sns), 8)
        self.assertEqual(sns[0], "002-04605")
        self.assertEqual(sns[-1], "002-04616")

    def test_partial_tray(self):
        sns = parse_sn_folder("RT_FE_002004605_002004606_002004607_002004608_002004613", "RT_FE_")
        self.assertEqual(sns, ["002-04605", "002-04606", "002-04607", "002-04608", "002-04613"])

    def test_garbage_returns_empty(self):
        # No digits at all
        self.assertEqual(parse_sn_folder("RT_FE_XXX_YYY", "RT_FE_"), [])
        # Wrong-length numbers
        self.assertEqual(parse_sn_folder("RT_FE_12345", "RT_FE_"), [])

    def test_wrong_prefix(self):
        self.assertEqual(parse_sn_folder("LN_FE_002004605", "RT_FE_"), [])


class ScanBatchTests(SimpleTestCase):
    def test_happy_path_warm_and_cold(self):
        with tempfile.TemporaryDirectory() as td:
            root = _mkrts(Path(td), {
                "B002T0001": {
                    "Time_20250813095435_DUT_0000": [
                        "RT_FE_002004605_002004606_002004607_002004608_"
                        "002004613_002004614_002004615_002004616",
                        "LN_FE_002004605_002004606_002004607_002004608_"
                        "002004613_002004614_002004615_002004616",
                    ],
                },
            })
            batch = scan_batch(root / "B002T0001")
            self.assertEqual(batch.batch_id, "B002T0001")
            self.assertEqual(len(batch.chips), 8)
            chip = batch.chips["002-04605"]
            self.assertEqual(chip.warm_ts, datetime(2025, 8, 13, 9, 54, 35, tzinfo=timezone.utc))
            self.assertEqual(chip.cold_ts, datetime(2025, 8, 13, 9, 54, 35, tzinfo=timezone.utc))
            self.assertEqual(chip.warm_batch_id, "B002T0001")
            self.assertEqual(batch.skipped_folders, [])

    def test_aborted_session_ignored(self):
        # Session has only LN_FE_ (no RT_) — ADR-0004 says skip wholesale.
        with tempfile.TemporaryDirectory() as td:
            root = _mkrts(Path(td), {
                "B002T0001": {
                    "Time_20250813095435": [
                        "LN_FE_999999999_999999999_999999999",  # garbage SNs in aborted session
                    ],
                },
            })
            batch = scan_batch(root / "B002T0001")
            self.assertEqual(batch.chips, {})
            self.assertEqual(batch.valid_session_count, 0)
            self.assertIsNone(batch.warm_date)

    def test_partial_tray_warm_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = _mkrts(Path(td), {
                "B005T0017": {
                    "Time_20250915120000": [
                        "RT_FE_002004605_002004606_002004607_002004608_002004613",
                    ],
                },
            })
            batch = scan_batch(root / "B005T0017")
            self.assertEqual(len(batch.chips), 5)
            self.assertIsNone(batch.cold_date)
            self.assertIsNotNone(batch.warm_date)

    def test_retested_chip_within_batch_latest_wins(self):
        with tempfile.TemporaryDirectory() as td:
            root = _mkrts(Path(td), {
                "B002T0001": {
                    "Time_20250813095435": [
                        "RT_FE_002004605_002004606",
                    ],
                    "Time_20250920120000": [
                        "RT_FE_002004605",  # re-tested
                    ],
                },
            })
            batch = scan_batch(root / "B002T0001")
            chip = batch.chips["002-04605"]
            self.assertEqual(chip.warm_ts, datetime(2025, 9, 20, 12, 0, 0, tzinfo=timezone.utc))
            # The other chip stays at the earlier time.
            self.assertEqual(
                batch.chips["002-04606"].warm_ts,
                datetime(2025, 8, 13, 9, 54, 35, tzinfo=timezone.utc),
            )

    def test_garbage_folder_skipped_and_recorded(self):
        with tempfile.TemporaryDirectory() as td:
            root = _mkrts(Path(td), {
                "B002T0001": {
                    "Time_20250813095435": [
                        "RT_FE_002004605",       # valid: provides RT_ presence + 1 chip
                        "RT_FE_XXX_YYY",          # garbage: zero valid SNs
                    ],
                },
            })
            batch = scan_batch(root / "B002T0001")
            self.assertEqual(set(batch.chips.keys()), {"002-04605"})
            self.assertEqual(len(batch.skipped_folders), 1)
            self.assertIn("RT_FE_XXX_YYY", batch.skipped_folders[0])


class UpdateLArasicsFromRtsCommandTests(TestCase):
    def _run(self, data_dir: Path, **kwargs) -> str:
        out = StringIO()
        call_command(
            "update_larasics_from_rts",
            "--data-dir", str(data_dir),
            "--commit",
            stdout=out,
            **kwargs,
        )
        return out.getvalue()

    def test_inserts_new_chips(self):
        with tempfile.TemporaryDirectory() as td:
            root = _mkrts(Path(td), {
                "B002T0001": {
                    "Time_20250813095435": [
                        "RT_FE_002004605_002004606",
                        "LN_FE_002004605_002004606",
                    ],
                },
            })
            self._run(root)
        self.assertEqual(LArASIC.objects.count(), 2)
        c = LArASIC.objects.get(serial_number="002-04605")
        self.assertEqual(c.status, "rts-tested")
        self.assertEqual(c.tray_id, "B002T0001")
        self.assertIsNotNone(c.warm_tested_at)
        self.assertIsNotNone(c.cold_tested_at)

    def test_dry_run_makes_no_writes(self):
        with tempfile.TemporaryDirectory() as td:
            root = _mkrts(Path(td), {
                "B002T0001": {
                    "Time_20250813095435": ["RT_FE_002004605"],
                },
            })
            # Provide "no" to the prompt by patching builtins.input.
            import builtins
            orig_input = builtins.input
            builtins.input = lambda *a, **kw: "no"
            try:
                out = StringIO()
                call_command(
                    "update_larasics_from_rts",
                    "--data-dir", str(root),
                    stdout=out,
                )
            finally:
                builtins.input = orig_input
        self.assertEqual(LArASIC.objects.count(), 0)

    def test_existing_on_femb_chip_keeps_status(self):
        femb = FEMB.objects.create(version="IO-1865-1K", serial_number="00001")
        LArASIC.objects.create(
            serial_number="002-04605", status="on-femb", femb=femb, femb_pos="F1",
        )
        with tempfile.TemporaryDirectory() as td:
            root = _mkrts(Path(td), {
                "B002T0001": {
                    "Time_20250813095435": ["RT_FE_002004605"],
                },
            })
            self._run(root)
        c = LArASIC.objects.get(serial_number="002-04605")
        self.assertEqual(c.status, "on-femb")
        self.assertEqual(c.tray_id, "B002T0001")
        self.assertIsNotNone(c.warm_tested_at)

    def test_existing_non_on_femb_chip_status_becomes_rts_tested(self):
        LArASIC.objects.create(serial_number="002-04605", status="testing")
        with tempfile.TemporaryDirectory() as td:
            root = _mkrts(Path(td), {
                "B002T0001": {
                    "Time_20250813095435": ["RT_FE_002004605"],
                },
            })
            self._run(root)
        c = LArASIC.objects.get(serial_number="002-04605")
        self.assertEqual(c.status, "rts-tested")
        self.assertEqual(c.tray_id, "B002T0001")

    def test_chip_in_multiple_batches_latest_warm_wins_tray_id(self):
        with tempfile.TemporaryDirectory() as td:
            root = _mkrts(Path(td), {
                "B001T0001": {
                    "Time_20250101000000": ["RT_FE_002004605"],
                },
                "B009T0099": {
                    "Time_20251231000000": ["RT_FE_002004605"],
                },
            })
            self._run(root)
        c = LArASIC.objects.get(serial_number="002-04605")
        self.assertEqual(c.tray_id, "B009T0099")
        self.assertEqual(
            c.warm_tested_at,
            datetime(2025, 12, 31, 0, 0, 0, tzinfo=timezone.utc),
        )

    def test_pre_cutoff_batch_is_skipped_on_import(self):
        with tempfile.TemporaryDirectory() as td:
            root = _mkrts(Path(td), {
                "B010T0001": {  # 2024 batch (test chips)
                    "Time_20240711102529": [
                        "RT_FE_002010000_002020000_002030000_002040000_"
                        "002050000_002060000_002070000_002080000",
                    ],
                },
                "B005T0001": {  # post-cutoff batch
                    "Time_20251231000000": ["RT_FE_002004605"],
                },
            })
            self._run(root)
        sns = set(LArASIC.objects.values_list("serial_number", flat=True))
        self.assertEqual(sns, {"002-04605"})  # dummies excluded

    def test_existing_pre_cutoff_chip_is_deleted_unless_on_femb(self):
        LArASIC.objects.create(
            serial_number="002-10000", status="rts-tested",
            warm_tested_at=datetime(2024, 9, 4, tzinfo=timezone.utc),
        )
        femb = FEMB.objects.create(version="IO-1865-1K", serial_number="00001")
        LArASIC.objects.create(
            serial_number="002-20000", status="on-femb",
            femb=femb, femb_pos="F1",
            warm_tested_at=datetime(2024, 9, 4, tzinfo=timezone.utc),
        )
        with tempfile.TemporaryDirectory() as td:
            root = _mkrts(Path(td), {
                "B005T0001": {"Time_20251231000000": ["RT_FE_002004605"]},
            })
            self._run(root)
        sns = set(LArASIC.objects.values_list("serial_number", flat=True))
        # 002-10000 deleted; on-femb 002-20000 retained.
        self.assertEqual(sns, {"002-04605", "002-20000"})

    def test_batch_filter_restricts_scan(self):
        with tempfile.TemporaryDirectory() as td:
            root = _mkrts(Path(td), {
                "B001T0001": {"Time_20250101000000": ["RT_FE_002004605"]},
                "B009T0099": {"Time_20251231000000": ["RT_FE_002004606"]},
            })
            self._run(root, batch="B009T0099")
        sns = set(LArASIC.objects.values_list("serial_number", flat=True))
        self.assertEqual(sns, {"002-04606"})
