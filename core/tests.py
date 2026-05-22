import tempfile
import textwrap
from pathlib import Path

from django.test import SimpleTestCase

from core.management.commands.update_fembs_from_ocr import (
    components_to_state,
    compute_repair_diff,
    parse_inspection_note,
    parse_parts_file,
)


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
