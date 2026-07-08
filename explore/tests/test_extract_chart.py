"""Tests for the extract_chart bootstrap aid (#56). Pure-function tests on
synthetic PDF primitives and an in-memory minimal pptx — no PyMuPDF needed.

    python manage.py test explore
"""

from __future__ import annotations

import io
import zipfile

import yaml
from django.test import SimpleTestCase

from explore import charts
from explore.management.commands.extract_chart import (
    _attach_labels, _chains, _draft_spec, _extract_pptx, _guess_edges,
    _lines, _slugify,
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
        rects = rects if rects is not None else [dict(BOX_A), dict(BOX_B)]
        words = (words if words is not None else
                 WORDS + [_word(30, 35, "Mezzanine", 5, 0), _word(80, 35, "racks", 5, 0)])
        used = _attach_labels(rects, words)
        return _draft_spec(
            rects,
            band_rects if band_rects is not None else
            [{"y0": 20.0, "y1": 60.0, "fill": "#f4cccc"}],
            _lines(words, used),
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


_XMLNS = ('xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
          'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"')

# Band strip with its title inside, red box A over scheme-colored box B, a
# "2 types" text-box annotation right of B, and a glued A-B connector inside
# a 2x-scaled group.
_SLIDE = f"""<p:sld {_XMLNS}><p:cSld><p:spTree>
 <p:sp><p:nvSpPr><p:cNvPr id="5" name=""/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
  <p:spPr><a:xfrm><a:off x="0" y="1270000"/><a:ext cx="24384000" cy="1270000"/></a:xfrm>
   <a:solidFill><a:srgbClr val="F4CCCC"/></a:solidFill><a:ln><a:noFill/></a:ln></p:spPr>
  <p:txBody><a:bodyPr/><a:p><a:r><a:rPr sz="1700"/><a:t>Mezzanine racks</a:t></a:r></a:p></p:txBody></p:sp>
 <p:sp><p:nvSpPr><p:cNvPr id="10" name=""/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
  <p:spPr><a:xfrm><a:off x="1270000" y="3810000"/><a:ext cx="1016000" cy="228600"/></a:xfrm>
   <a:solidFill><a:srgbClr val="FF0000"/></a:solidFill></p:spPr>
  <p:txBody><a:bodyPr/><a:p><a:r><a:t>Inst. CRU</a:t></a:r></a:p></p:txBody></p:sp>
 <p:sp><p:nvSpPr><p:cNvPr id="11" name=""/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
  <p:spPr><a:xfrm><a:off x="1470000" y="4318000"/><a:ext cx="1016000" cy="228600"/></a:xfrm>
   <a:solidFill><a:schemeClr val="accent6"/></a:solidFill></p:spPr>
  <p:txBody><a:bodyPr/><a:p><a:r><a:t>FEMB (1)</a:t></a:r></a:p></p:txBody></p:sp>
 <p:sp><p:nvSpPr><p:cNvPr id="12" name=""/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>
  <p:spPr><a:xfrm><a:off x="2540000" y="4360000"/><a:ext cx="790500" cy="142800"/></a:xfrm>
   <a:noFill/><a:ln><a:noFill/></a:ln></p:spPr>
  <p:txBody><a:bodyPr/><a:p><a:r><a:rPr sz="700"/><a:t>2 types</a:t></a:r></a:p></p:txBody></p:sp>
 <p:grpSp><p:nvGrpSpPr><p:cNvPr id="20" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
  <p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="24384000" cy="13716000"/>
   <a:chOff x="0" y="0"/><a:chExt cx="12192000" cy="6858000"/></a:xfrm></p:grpSpPr>
  <p:cxnSp><p:nvCxnSpPr><p:cNvPr id="21" name=""/><p:cNvCxnSpPr>
    <a:stCxn id="10" idx="2"/><a:endCxn id="11" idx="0"/></p:cNvCxnSpPr><p:nvPr/></p:nvCxnSpPr>
   <p:spPr><a:xfrm><a:off x="889000" y="2019300"/><a:ext cx="95250" cy="139700"/></a:xfrm>
    <a:ln><a:solidFill><a:srgbClr val="000000"/></a:solidFill></a:ln></p:spPr></p:cxnSp></p:grpSp>
</p:spTree></p:cSld></p:sld>"""

_THEME_ACCENTS = "".join(
    f'<a:accent{i}><a:srgbClr val="{v}"/></a:accent{i}>'
    for i, v in enumerate(("0365C0", "00882B", "DCBD23", "DE6A10", "C82506", "773F9B"), 1))
_THEME = f"""<a:theme {_XMLNS}><a:themeElements><a:clrScheme name="t">
 <a:dk1><a:srgbClr val="000000"/></a:dk1><a:lt1><a:srgbClr val="FFFFFF"/></a:lt1>
 <a:dk2><a:srgbClr val="53585F"/></a:dk2><a:lt2><a:srgbClr val="DCDEE0"/></a:lt2>
 {_THEME_ACCENTS}
 <a:hlink><a:srgbClr val="0000FF"/></a:hlink><a:folHlink><a:srgbClr val="FF00FF"/></a:folHlink>
</a:clrScheme></a:themeElements></a:theme>"""


def _pptx():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("ppt/presentation.xml",
                    f'<p:presentation {_XMLNS}><p:sldSz cx="24384000" cy="13716000"/></p:presentation>')
        zf.writestr("ppt/theme/theme1.xml", _THEME)
        zf.writestr("ppt/slides/slide2.xml", _SLIDE)
    buf.seek(0)
    return buf


class PptxExtractTest(SimpleTestCase):
    def test_minimal_slide_extracts_all_primitives(self):
        rects, band_rects, segments, lines, canvas = _extract_pptx(_pptx(), 2)
        self.assertEqual(canvas, {"width": 1920, "height": 1080})
        self.assertEqual(band_rects, [{"y0": 100.0, "y1": 200.0, "fill": "#f4cccc"}])
        self.assertEqual([r["label"] for r in rects], ["Inst. CRU", "FEMB (1)"])
        self.assertEqual(rects[1]["fill"], "#773f9b")  # schemeClr accent6
        # one glued connector, group 2x transform applied, endpoints on the boxes
        self.assertEqual(len(segments), 1)
        seg = segments[0]
        self.assertEqual((seg["x0"], seg["y0"], seg["x1"], seg["y1"]),
                         (140.0, 318.0, 155.0, 340.0))
        texts = [l["text"] for l in lines]
        self.assertIn("Mezzanine racks", texts)  # strip title, synthesized line
        self.assertIn("2 types", texts)

    def test_draft_from_pptx_primitives(self):
        rects, band_rects, segments, lines, _ = _extract_pptx(_pptx(), 2)
        draft, _ = _draft_spec(rects, band_rects, lines, segments,
                               "Test chart", "test.pptx, slide 2")
        spec = yaml.safe_load(draft)
        charts._build("draft", spec)  # round-trip safe
        strip = next(b for b in spec["bands"] if b.get("label"))
        self.assertEqual(strip["label"], "Mezzanine racks")
        femb = next(n for n in spec["nodes"] if n["id"] == "femb")
        self.assertEqual(femb["note"], "2 types")
        self.assertEqual(femb["band"], "interior")
        self.assertIn({"from": "femb", "to": "inst-cru"}, spec["edges"])


class CycleGuardTest(SimpleTestCase):
    def test_build_raises_on_edge_cycle(self):
        spec = {"nodes": [{"id": "a", "label": "A", "fill": "#000"},
                          {"id": "b", "label": "B", "fill": "#000"}],
                "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "a"}]}
        with self.assertRaisesMessage(ValueError, "unreachable"):
            charts._build("t", spec)
