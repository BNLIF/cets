"""Tests for CE leaf link-outs in the explorer (issue #31, ADR-0010).

CE component types render the same generic plots as everyone, plus extra
deep-links to the existing rich CE pages. Non-CE leaves get no such links.

    python manage.py test hwdb
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from hwdb.models import ComponentTypeNode


def _node(ptid, system_id, system_name, subsystem_name, **kw):
    return ComponentTypeNode.objects.create(
        part_type_id=ptid, system_id=system_id, system_name=system_name,
        subsystem_id=kw.get("subsystem_id", 1), subsystem_name=subsystem_name,
        component_type_name=kw.get("component_type_name", "leaf"),
        full_name=kw.get("full_name", ""), n_components=kw.get("n_components", 1),
    )


class CeLinkOutTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("ce", "c@c.io", "pw")
        self.client.force_login(self.user)

    def _html(self, ptid):
        return self.client.get(reverse("hwdb:explore") + f"?node={ptid}").content.decode()

    def test_larasic_leaf_links_to_ce_pages(self):
        _node("D08100100003", 81, "FD CE", "LArASIC", component_type_name="LArASIC P5B Prod")
        html = self._html("D08100100003")
        self.assertIn(reverse("hwdb:larasic"), html)       # Detailed QC & upload
        self.assertIn(reverse("larasic"), html)            # LArASIC chips
        self.assertIn(reverse("hwdb:dashboard"), html)     # CE progress dashboard

    def test_femb_leaf_links_to_femb_and_dashboard(self):
        _node("D08101100041", 81, "FD CE", "FEMB", component_type_name="MiniSAS FEMB FD-VD")
        html = self._html("D08101100041")
        self.assertIn(reverse("femb"), html)
        self.assertIn(reverse("hwdb:dashboard"), html)

    def test_non_ce_leaf_has_no_ce_links(self):
        _node("D05700200001", 57, "FD-VD TDE", "Digital electronics", component_type_name="AMC")
        html = self._html("D05700200001")
        self.assertNotIn("CE progress dashboard", html)

    def test_ce_leaf_without_rich_page_has_no_links(self):
        # A FD CE subsystem with no dedicated page (e.g. cables) gets no link-outs.
        _node("D08102100021", 81, "FD CE", "Cold Signal Cables", component_type_name="MiniSAS CRP")
        html = self._html("D08102100021")
        self.assertNotIn("CE progress dashboard", html)
