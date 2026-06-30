"""Tests for the list_shippable audit (issue #46, ADR-0013).

Mirror-only (no HWDB calls): the audit lists curated component types under a
"Shipping" subsystem — HWDB's structural signal for shipping boxes.

    python manage.py test explore
"""

from __future__ import annotations

from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase

from explore.models import HierarchyNode as H


def _leaf(ptid, system_id, subsystem_name, name, n=0):
    return H.objects.create(
        level=H.LEVEL_TYPE, system_id=system_id, system_name=f"sys{system_id}",
        subsystem_id=hash(subsystem_name) % 1000, subsystem_name=subsystem_name,
        name=name, part_type_id=ptid, n_components=n)


def _run(*extra):
    out = StringIO()
    with mock.patch("explore.curation.curated_system_ids", return_value={57, 81}), \
         mock.patch("explore.curation.shipping_types", return_value={"D08120200001"}):
        call_command("list_shippable", *extra, stdout=out)
    return out.getvalue()


class ListShippableTest(TestCase):
    def setUp(self):
        # Under "Shipping" subsystems → shipping-box candidates.
        _leaf("D08120200001", 81, "CE Shipping Box", "CE Shipping box", n=2)   # curated
        _leaf("D05700600003", 57, "Shipping", "Electronics box", n=326)        # new, active
        _leaf("D05700600001", 57, "Shipping", "SGFT24 crate", n=0)             # new, empty
        # NOT under a Shipping subsystem → never surfaced.
        _leaf("D05700200005", 57, "Digital electronics", "uTCA crate", n=326)
        _leaf("D08100100003", 81, "LArASIC", "LArASIC P5B Prod", n=500)

    def test_lists_shipping_subsystem_leaves(self):
        out = _run()
        self.assertIn("D08120200001", out)
        self.assertIn("D05700600003", out)
        self.assertIn("Electronics box", out)

    def test_excludes_non_shipping_subsystem_even_if_box_like(self):
        out = _run()
        self.assertNotIn("D05700200005", out)  # "uTCA crate" but under Digital electronics
        self.assertNotIn("LArASIC", out)

    def test_flags_new_candidates_with_box_counts(self):
        out = _run()
        self.assertIn("Candidates", out)
        self.assertRegex(out, r"D05700600003.*326 boxes")
        self.assertRegex(out, r"D05700600001.*0 boxes")  # empty one still surfaced

    def test_curated_marked_yes_not_a_candidate(self):
        out = _run()
        self.assertRegex(out, r"yes\s+D08120200001")
        self.assertNotRegex(out, r"-\s+D08120200001\s+#")

    def test_summary_counts(self):
        out = _run()
        self.assertIn("3 shipping-subsystem type(s) · 1 curated · 2 not curated", out)
        self.assertIn("1 with boxes today", out)

    def test_system_filter(self):
        out = _run("--system", "81")
        self.assertIn("D08120200001", out)
        self.assertNotIn("D05700600003", out)  # system 57 excluded

    def test_empty_when_no_shipping_subsystems(self):
        H.objects.all().delete()
        _leaf("D05700200005", 57, "Digital electronics", "uTCA crate", n=10)
        out = _run()
        self.assertIn("No curated component types under a 'shipping' subsystem", out)