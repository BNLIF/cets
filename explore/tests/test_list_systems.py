"""Tests for the list_systems curation audit (issue #39, ADR-0012).

The HWDB call is mocked — no network, no bearer needed.

    python manage.py test explore
"""

from __future__ import annotations

from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase


def _run(systems, curated):
    api = mock.MagicMock()
    api.get_systems.return_value = {"data": systems}
    out = StringIO()
    with mock.patch("explore.management.commands.list_systems.FnalDbApiClient",
                    return_value=api), \
         mock.patch("explore.management.commands.list_systems.curation"
                    ".curated_system_ids", return_value=set(curated)):
        call_command("list_systems", "--bearer", "x", stdout=out)
    return out.getvalue()


class ListSystemsAuditTest(TestCase):
    SYSTEMS = [
        {"id": 57, "name": "FD-VD TDE"},
        {"id": 1, "name": "FD-HD Complete Detector"},
        {"id": 99, "name": "Ghost"},
    ]

    def test_labels_curated_and_not_curated(self):
        out = _run(self.SYSTEMS, curated={57, 200})
        self.assertRegex(out, r"57\s+curated\s+FD-VD TDE")
        self.assertRegex(out, r"1\s+not curated\s+FD-HD Complete Detector")
        self.assertRegex(out, r"99\s+not curated\s+Ghost")

    def test_reports_curated_but_missing_from_hwdb(self):
        out = _run(self.SYSTEMS, curated={57, 200})  # 200 not in live HWDB
        self.assertIn("curated but missing from HWDB", out)
        self.assertIn("200", out)

    def test_summary_counts(self):
        out = _run(self.SYSTEMS, curated={57, 200})
        self.assertIn(
            "3 systems in HWDB · 1 curated · 2 not curated · 1 curated-but-missing",
            out,
        )

    def test_no_drift_when_all_present(self):
        out = _run(self.SYSTEMS, curated={57})
        self.assertNotIn("curated but missing from HWDB", out)
        self.assertIn("0 curated-but-missing", out)
