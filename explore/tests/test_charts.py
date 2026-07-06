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

    def test_overlay_places_boxes_at_pdf_positions(self):
        chart = charts.svg_chart("fd-vd-v4")
        femb = _by_label(chart, "FEMB (1)")
        self.assertAlmostEqual(femb["x"], 705.6, places=0)
        self.assertAlmostEqual(femb["y"], 912.4, places=0)
        self.assertEqual((chart["width"], chart["height"]), (1920, 1080))

    def test_overlay_band_strips_at_pdf_positions(self):
        chart = charts.svg_chart("fd-vd-v4")
        mez = next(b for b in chart["bands"] if b["label"] == "Mezzanine racks")
        self.assertAlmostEqual(mez["y"], 123.8, places=0)

    def test_cable_edges_route_with_arrowheads(self):
        chart = charts.svg_chart("fd-vd-v4")
        cable = next(a for a in chart["arrows"] if a["color"] == "#ff0000")
        self.assertTrue(cable["marker"])
        self.assertGreaterEqual(len(cable["points"]), 2)
        self.assertIn(("ff0000", "#ff0000"), chart["arrow_colors"])

    def test_long_labels_shrink_to_fit_their_box(self):
        chart = charts.svg_chart("fd-vd-v4")
        for box in chart["boxes"]:
            avail = (box["h"] if box["vertical"] else box["w"]) - 6
            est = charts.CHAR_W * len(box["label"])
            if est > avail:
                self.assertLess(box["font"], 10)
                self.assertAlmostEqual(box["squeeze"], avail, places=1)
            else:
                self.assertNotIn("font", box)

    def test_tall_boxes_get_vertical_labels(self):
        chart = charts.svg_chart("fd-vd-v4")
        tall = _by_label(chart, "BDE signal cable (6)")
        self.assertTrue(tall["vertical"])
        self.assertFalse(_by_label(chart, "FEMB (1)")["vertical"])

    def test_notes_and_loose_texts_become_annotations(self):
        texts = [a["text"] for a in charts.svg_chart("fd-vd-v4")["annotations"]]
        self.assertIn("7 types", texts)          # note on Adapter board
        self.assertIn("to TMS rack", texts)      # loose text from the overlay

    def test_house_layout_stacks_children_indented(self):
        spec = {"nodes": [{"id": "p", "label": "P", "fill": "#000"},
                          {"id": "a", "label": "A", "fill": "#000"},
                          {"id": "b", "label": "B", "fill": "#000"}],
                "edges": [{"from": "a", "to": "p"}, {"from": "b", "to": "p"}]}
        chart = charts._build("t", spec)
        p, a, b = (next(n for n in chart["boxes"] if n["id"] == i) for i in "pab")
        self.assertEqual(a["x"], p["x"] + charts.INDENT)
        self.assertEqual(b["x"], p["x"] + charts.INDENT)
        self.assertGreater(a["y"], p["y"])
        self.assertGreaterEqual(b["y"] - a["y"], charts.BOX_H)

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
        # pan/zoom affordances (#57)
        self.assertIn('id="hc-reset"', html)
        self.assertIn("svg.addEventListener", html)

    def test_dev_instance_serves_same_chart(self):
        html = self.client.get("/hw/dev/hierarchy/").content.decode()
        self.assertIn("FEMB (1)", html)

    def test_anonymous_is_redirected_to_login(self):
        self.client.logout()
        resp = self.client.get(reverse("explore:hierarchy"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("login", resp["Location"])
