"""Tests for the extract_chart bootstrap aid (#56). Pure-function tests on
synthetic PDF primitives — no PyMuPDF needed.

    python manage.py test explore
"""

from __future__ import annotations

import yaml
from django.test import SimpleTestCase

from explore import charts
from explore.management.commands.extract_chart import (
    _chains, _draft_spec, _guess_edges, _slugify,
)


def _word(x0, y0, text, block=0, line=0):
    return (x0, y0, x0 + 4.5 * len(text), y0 + 8, text, block, line)


def _seg(x0, y0, x1, y1, color="#000000"):
    return {"x0": x0, "y0": y0, "x1": x1, "y1": y1, "color": color}


# Parent box A above child box B, joined by a two-segment elbow.
BOX_A = {"x0": 100.0, "y0": 100.0, "x1": 180.0, "y1": 118.0,
         "fill": "#ff0000", "stroke": None, "dashed": False}
BOX_B = {"x0": 116.0, "y0": 140.0, "x1": 200.0, "y1": 158.0,
         "fill": "#a27310", "stroke": None, "dashed": False}
ELBOW = [_seg(116, 149, 107, 149), _seg(107, 149, 107, 118)]
WORDS = [_word(105, 104, "Inst.", 0, 0), _word(130, 104, "CRU", 0, 0),
         _word(120, 144, "FEMB", 1, 0), _word(142, 144, "(1)", 1, 0)]


class SlugifyTest(SimpleTestCase):
    def test_strips_counts_and_punctuation(self):
        self.assertEqual(_slugify("FEMB (1)"), "femb")
        self.assertEqual(_slugify("Inst. CRU (20x4x2)"), "inst-cru")
        self.assertEqual(_slugify("Cold ADC (8)"), "cold-adc")


class ChainEdgeTest(SimpleTestCase):
    def test_elbow_chains_into_one_edge_lower_box_is_child(self):
        boxes = [dict(BOX_A, id="a", label="A"), dict(BOX_B, id="b", label="B")]
        chains = _chains(ELBOW)
        self.assertEqual(len(chains), 1)
        edges, unresolved = _guess_edges(chains, boxes)
        self.assertEqual(unresolved, 0)
        self.assertEqual(edges, [{"from": "b", "to": "a"}])

    def test_same_point_different_color_does_not_merge(self):
        segs = [_seg(0, 0, 10, 0), _seg(10, 0, 20, 0, color="#ff0000")]
        self.assertEqual(len(_chains(segs)), 2)

    def test_red_chain_is_a_cable(self):
        boxes = [dict(BOX_A, id="a", label="A"), dict(BOX_B, id="b", label="B")]
        red = [dict(s, color="#ff0000") for s in ELBOW]
        edges, _ = _guess_edges(_chains(red), boxes)
        self.assertEqual(edges[0]["kind"], "cable")

    def test_dangling_chain_is_unresolved(self):
        boxes = [dict(BOX_A, id="a", label="A")]
        edges, unresolved = _guess_edges(_chains(ELBOW), boxes)
        self.assertEqual((edges, unresolved), ([], 1))


class DraftSpecTest(SimpleTestCase):
    def _draft(self, rects=None, band_rects=None, words=None, segments=None):
        return _draft_spec(
            rects if rects is not None else [dict(BOX_A), dict(BOX_B)],
            band_rects if band_rects is not None else
            [{"y0": 20.0, "y1": 60.0, "fill": "#f4cccc"}],
            words if words is not None else
            WORDS + [_word(30, 35, "Mezzanine", 5, 0), _word(80, 35, "racks", 5, 0)],
            segments if segments is not None else list(ELBOW),
            "Test chart", "test.pdf, page 2")

    def test_draft_round_trips_through_build(self):
        draft, stats = self._draft()
        spec = yaml.safe_load(draft)
        chart = charts._build("draft", spec)
        self.assertEqual(stats["nodes"], 2)
        self.assertIn("FEMB (1)", [b["label"] for b in chart["boxes"]])

    def test_band_strip_gets_label_and_nodes_get_regions(self):
        draft, _ = self._draft()
        spec = yaml.safe_load(draft)
        strip = next(b for b in spec["bands"] if b.get("label"))
        self.assertEqual(strip["label"], "Mezzanine racks")
        # below the LAST strip is the interior region by design
        femb = next(n for n in spec["nodes"] if n["id"] == "femb")
        self.assertEqual(femb["band"], "interior")

    def test_n_types_becomes_note(self):
        words = WORDS + [_word(204, 145, "2", 6, 0), _word(210, 145, "types", 6, 0)]
        draft, _ = self._draft(words=words)
        spec = yaml.safe_load(draft)
        femb = next(n for n in spec["nodes"] if n["id"] == "femb")
        self.assertEqual(femb["note"], "2 types")

    def test_second_tree_parent_is_commented_out(self):
        box_c = dict(BOX_A, x0=220.0, x1=300.0, id=None)
        segs = ELBOW + [_seg(200, 149, 226, 118)]  # B -> C too
        words = WORDS + [_word(224, 104, "Other", 7, 0)]
        draft, stats = self._draft(rects=[dict(BOX_A), dict(BOX_B), box_c],
                                   words=words, segments=segs)
        self.assertEqual(stats["dupe_parents"], 1)
        # still loads: the second parent edge is only a comment
        charts._build("draft", yaml.safe_load(draft))


class CycleGuardTest(SimpleTestCase):
    def test_build_raises_on_edge_cycle(self):
        spec = {"nodes": [{"id": "a", "label": "A", "fill": "#000"},
                          {"id": "b", "label": "B", "fill": "#000"}],
                "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "a"}]}
        with self.assertRaisesMessage(ValueError, "unreachable"):
            charts._build("t", spec)
