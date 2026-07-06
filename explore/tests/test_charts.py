"""Tests for the detector hierarchy chart (#55): semantic spec loading,
the house layout, and the /hw/hierarchy/ SVG page.

    python manage.py test explore
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from explore import charts


def _by_label(chart, label):
    return next(b for b in chart["boxes"] if b["label"] == label)


class ChartSpecTest(TestCase):
    def test_fd_vd_v4_is_listed(self):
        self.assertIn("fd-vd-v4", charts.chart_ids())

    def test_svg_chart_shape(self):
        chart = charts.svg_chart("fd-vd-v4")
        self.assertGreater(chart["width"], 0)
        self.assertGreater(chart["height"], 0)
        self.assertTrue(chart["boxes"])
        self.assertTrue(chart["arrows"])
        self.assertTrue(chart["bands"])

    def test_children_stack_indented_below_parent(self):
        chart = charts.svg_chart("fd-vd-v4")
        femb = _by_label(chart, "FEMB (1)")
        kids = [_by_label(chart, l)
                for l in ("LArASIC (8)", "Cold ADC (8)", "Cold DATA (2)")]
        for kid in kids:
            self.assertEqual(kid["x"], femb["x"] + charts.INDENT)
            self.assertGreater(kid["y"], femb["y"])
        # spec order preserved top to bottom, no overlap
        ys = [k["y"] for k in kids]
        self.assertEqual(ys, sorted(ys))
        self.assertGreaterEqual(ys[1] - ys[0], charts.BOX_H)

    def test_band_rows_stack_in_spec_order(self):
        chart = charts.svg_chart("fd-vd-v4")
        mez, roof, interior = chart["bands"]
        self.assertEqual(mez["label"], "Mezzanine racks")
        self.assertLess(mez["y"], roof["y"])
        self.assertLess(roof["y"], interior["y"])
        # the tree lives in the interior row, below the roof strip
        root = _by_label(chart, "Inst. CRU (20x4x2)")
        self.assertGreater(root["y"], roof["y"] + roof["h"])

    def test_cable_edge_routes_with_arrowhead(self):
        chart = charts.svg_chart("fd-vd-v4")
        cable = next(a for a in chart["arrows"] if a["color"] == "#ff0000")
        self.assertTrue(cable["marker"])
        self.assertEqual(len(cable["points"]), 4)
        self.assertIn(("ff0000", "#ff0000"), chart["arrow_colors"])

    def test_note_becomes_annotation(self):
        chart = charts.svg_chart("fd-vd-v4")
        self.assertEqual(chart["annotations"][0]["text"], "7 types")

    def test_unknown_edge_ref_raises(self):
        spec = {"nodes": [{"id": "a", "label": "A", "fill": "#000"}],
                "edges": [{"from": "a", "to": "ghost"}]}
        with self.assertRaisesMessage(ValueError, "unknown node"):
            charts._build("t", spec)

    def test_second_tree_parent_raises(self):
        spec = {"nodes": [{"id": "a", "label": "A", "fill": "#000"},
                          {"id": "b", "label": "B", "fill": "#000"},
                          {"id": "c", "label": "C", "fill": "#000"}],
                "edges": [{"from": "a", "to": "b"}, {"from": "a", "to": "c"}]}
        with self.assertRaisesMessage(ValueError, "more than one tree parent"):
            charts._build("t", spec)


class HierarchyViewTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("hc", "h@h.io", "pw")
        self.client.force_login(self.user)

    def test_renders_chart_svg(self):
        html = self.client.get(reverse("explore:hierarchy")).content.decode()
        self.assertIn("<svg", html)
        self.assertIn("FEMB (1)", html)
        self.assertIn("FD-VD Complete detector (v4)", html)
        self.assertIn("Cryostat roof", html)

    def test_dev_instance_serves_same_chart(self):
        html = self.client.get("/hw/dev/hierarchy/").content.decode()
        self.assertIn("FEMB (1)", html)

    def test_anonymous_is_redirected_to_login(self):
        self.client.logout()
        resp = self.client.get(reverse("explore:hierarchy"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("login", resp["Location"])
