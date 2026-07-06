"""Tests for the audit_chart_mapping command (#59).

Mirror-only (no HWDB calls): the audit compares a chart's mapping overlay
against the spec's node ids and the HierarchyNode mirror, and suggests
name-match candidates for unmapped nodes. Advisory only — never writes.

    python manage.py test explore
"""

from __future__ import annotations

from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase

from explore.models import HierarchyNode as H


def _leaf(ptid, name, system="FD-VD TOP CRP"):
    return H.objects.create(
        level=H.LEVEL_TYPE, system_id=int(ptid[1:4]), system_name=system,
        subsystem_id=int(ptid[4:7]), subsystem_name="sub",
        name=name, part_type_id=ptid)


FAKE_CHART = {"boxes": [{"id": "femb", "label": "FEMB (1)"},
                        {"id": "camera-light", "label": "Camera light"},
                        {"id": "mystery", "label": "Zzzqqq widget"}]}
FAKE_MAPPING = {"femb": ["D08101100041"], "ghost": ["D99999999999"]}


def _run(mapping=FAKE_MAPPING, *extra):
    out = StringIO()
    with mock.patch("explore.charts.svg_chart", return_value=FAKE_CHART), \
         mock.patch("explore.charts.type_mapping", return_value=mapping):
        call_command("audit_chart_mapping", "fake", *extra, stdout=out)
    return out.getvalue()


class AuditChartMappingTest(TestCase):
    def setUp(self):
        _leaf("D08101100041", "FEMB FD-VD MiniSAS", system="FD CE")  # mapped, in mirror
        _leaf("D05900100001", "Camera light")            # candidate for camera-light
        _leaf("D05900100002", "Camera light cold cable")  # weaker alt candidate
        _leaf("D05700200005", "uTCA crate")              # matches nothing

    def test_summary_counts(self):
        out = _run()
        self.assertIn("3 nodes: 1 mapped, 2 unmapped", out)
        self.assertIn("mirror has 4 component types", out)

    def test_stale_mapping_reported(self):
        out = _run()
        self.assertIn("ghost: D99999999999", out)   # not in the mirror
        self.assertNotIn("femb: D08101100041", out)  # in the mirror → not stale

    def test_unknown_node_id_reported(self):
        out = _run()
        self.assertIn("not in the chart spec", out)
        self.assertRegex(out, r"(?m)^  ghost$")

    def test_candidates_are_paste_ready_with_alts(self):
        out = _run()
        self.assertRegex(out, r"camera-light: \[D05900100001\].*Camera light")
        self.assertRegex(out, r"#   alt: D05900100002")

    def test_no_candidate_nodes_listed_separately(self):
        out = _run()
        self.assertIn("no candidate in the mirror (1)", out)
        self.assertRegex(out, r"mystery\s+Zzzqqq widget")

    def test_already_mapped_types_not_suggested(self):
        _leaf("D08101100099", "FEMB spare flavor", system="FD CE")
        out = _run({"femb": ["D08101100041", "D08101100099"], "ghost": ["D99999999999"]})
        self.assertNotIn("camera-light: [D08101100099]", out)

    def test_fully_mapped_chart(self):
        out = _run({"femb": ["D08101100041"],
                    "camera-light": ["D05900100001"],
                    "mystery": ["D05700200005"]})
        self.assertIn("No stale mappings.", out)
        self.assertIn("Every chart node is mapped.", out)

    def test_real_chart_smoke(self):
        out = StringIO()
        call_command("audit_chart_mapping", stdout=out)  # default = sole chart
        self.assertIn("Chart 'fd-vd-v4' · instance prod", out.getvalue())
