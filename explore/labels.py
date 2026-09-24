"""#175: QR / bar-code label sheets — a port of the HWDB Python utility's
``hwdb-labels`` (``Sisyphus/HWDBUtility/PDFLabels.py`` + its
``default_labels.py``; https://dune.github.io/computing-HWDB/barqrcode/).

The utility's configuration has four nodes — page sizes, label templates
(a sheet's geometry), layouts (elements placed on one label) and label
sets — and its element types are ``qr`` (the item's HWDB page URL),
``bar`` (the external ID ``PID-CC###``), ``part id``, ``external id``,
``part name`` and ``text`` with ``${field}`` substitution over the item
record. The same names and numbers are kept here so a layout written for
the utility reads the same; the codes are drawn as vectors (reportlab's
QR widget and Code128) instead of fetching HWDB's PNGs, which encode the
very same strings.

The PDF opens with the utility's intro page and alignment-template page
per sheet type, then the label pages. ``preview_png`` renders one label
for the editor through pymupdf.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import local

import fitz
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import code128
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib import units
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas as rl_canvas

logger = logging.getLogger(__name__)

UNITS = {"mm": units.mm, "cm": units.cm, "inch": units.inch, "pica": units.pica}

PAGE_SIZES = {
    "A4": {"units": "mm", "size": [210.0, 297.0]},
    "Letter": {"units": "inch", "size": [8.5, 11.0]},
}

# Sheet geometry, verbatim from the utility's default_labels.py: label
# size and the left / top offsets of every column / row, in the page's units.
TEMPLATES = {
    "A4-4x11-Generic": {
        "description": "A4 (210×297 mm), 51.5×26.6 mm labels, 44 per sheet",
        "page size": "A4", "label size": [51.5, 26.6],
        "horizontal offsets": [2.0, 53.5, 105.0, 156.5],
        "vertical offsets": [2.2, 28.8, 55.4, 82.0, 108.6, 135.2, 161.8, 188.4,
                             215.0, 241.6, 268.02],
        "rounding": 2.0},
    "A4-3x4-Generic": {
        "description": "A4 (210×297 mm), 67×72 mm labels, 12 per sheet",
        "page size": "A4", "label size": [67.0, 72.0],
        "horizontal offsets": [3.0, 72.0, 141.0],
        "vertical offsets": [2.5, 75.5, 148.5, 221.5],
        "rounding": 2.0},
    "A4-6x11-Herma": {
        "description": "A4 (210×297 mm), 25.4×25.4 mm labels, 66 per sheet",
        "page size": "A4", "label size": [25.4, 25.4],
        "horizontal offsets": [16.1, 46.58, 77.06, 107.54, 138.02, 168.5],
        "vertical offsets": [11.3, 36.7, 62.1, 87.5, 112.9, 138.3, 163.7, 189.1,
                             214.5, 239.9, 265.3],
        "rounding": 2.0},
    "Letter-2x2-Avery": {
        "description": "Letter (8.5”×11”), 5”×3.5” labels, 4 per sheet",
        "page size": "Letter", "label size": [3.5, 5.0],
        "horizontal offsets": [0.5, 4.5], "vertical offsets": [0.5, 5.5],
        "rounding": 0.125},
    "Letter-2x3-Avery": {
        "description": "Letter (8.5”×11”), 4”×3.333” labels, 6 per sheet",
        "page size": "Letter", "label size": [4.0, 3.333],
        "horizontal offsets": [0.156, 4.344], "vertical offsets": [0.5, 3.833, 7.167],
        "rounding": 0.125},
    "Letter-2x4-Avery": {
        "description": "Letter (8.5”×11”), 4”×2.5” labels, 8 per sheet",
        "page size": "Letter", "label size": [4.0, 2.5],
        "horizontal offsets": [0.156, 4.344], "vertical offsets": [0.5, 3.0, 5.5, 8.0],
        "rounding": 0.125},
    "Letter-2x5-Avery": {
        "description": "Letter (8.5”×11”), 4”×2” labels, 10 per sheet",
        "page size": "Letter", "label size": [4.0, 2.0],
        "horizontal offsets": [0.156, 4.344], "vertical offsets": [0.5, 2.5, 4.5, 6.5, 8.5],
        "rounding": 0.125},
    "Letter-2x6-Avery": {
        "description": "Letter (8.5”×11”), 4”×1.5” labels, 12 per sheet",
        "page size": "Letter", "label size": [4.0, 1.5],
        "horizontal offsets": [0.156, 4.344],
        "vertical offsets": [1.0, 2.5, 4.0, 5.5, 7.0, 8.5],
        "rounding": 0.125},
    "Letter-2x7-Avery": {
        "description": "Letter (8.5”×11”), 4”×1.333” labels, 14 per sheet",
        "page size": "Letter", "label size": [4.0, 1.33333],
        "horizontal offsets": [0.15625, 4.34375],
        "vertical offsets": [0.833, 2.167, 3.5, 4.833, 6.167, 7.5, 8.833],
        "rounding": 0.125},
    "Letter-3x5-Avery": {
        "description": "Letter (8.5”×11”), 2.625”×2” labels, 15 per sheet",
        "page size": "Letter", "label size": [2.625, 2.0],
        "horizontal offsets": [0.156, 2.906, 5.656],
        "vertical offsets": [0.5, 2.5, 4.5, 6.5, 8.5],
        "rounding": 0.125},
    "Letter-3x10-Avery": {
        "description": "Letter (8.5”×11”), 2.625”×1” labels, 30 per sheet",
        "page size": "Letter", "label size": [2.625, 1.0],
        "horizontal offsets": [0.156, 2.906, 5.656],
        "vertical offsets": [0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5, 9.5],
        "rounding": 0.125},
}


def _qr_layout(template, orientation, qr_anchor, qr_size, id_y, name_y, font):
    return {"label template": template, "orientation": orientation, "elements": [
        {"element type": "qr", "alignment": "top-center", "anchor": qr_anchor,
         "size": qr_size, "preserve aspect ratio": True},
        {"element type": "part id", "alignment": "top-center", "anchor": ["50%", id_y],
         "font size": font, "fit width": True},
        {"element type": "part name", "alignment": "top-center", "anchor": ["50%", name_y],
         "font size": font, "fit width": True}]}


# The utility's default layouts — the editor's presets. Their text elements
# carry "fit width" (our extension) so a long part name shrinks to the label.
LAYOUTS = {
    "QR-A4-3x4-Generic": _qr_layout("A4-3x4-Generic", "portrait", ["50%", "4%"], ["100%", "73%"], "82%", "90%", "5%"),
    "QR-A4-6x11-Herma_10107": _qr_layout("A4-6x11-Herma", "portrait", ["50%", "4%"], ["75%", "75%"], "83%", "90%", "5%"),
    "QR-Letter-2x2-Avery": _qr_layout("Letter-2x2-Avery", "portrait", ["50%", "4%"], ["100%", "73%"], "82%", "90%", "5%"),
    "QR-Letter-2x3-Avery": _qr_layout("Letter-2x3-Avery", "landscape", ["50%", "4%"], ["100%", "73%"], "82%", "90%", "5%"),
    "QR-Letter-2x4-Avery": _qr_layout("Letter-2x4-Avery", "landscape", ["50%", "15%"], ["90%", "73%"], "75%", "83%", "4%"),
    "QR-Letter-2x5-Avery": _qr_layout("Letter-2x5-Avery", "landscape", ["50%", "15%"], ["90%", "73%"], "75%", "83%", "4%"),
    "QR-Letter-2x6-Avery": {
        "label template": "Letter-2x6-Avery", "orientation": "portrait", "elements": [
            {"element type": "qr", "alignment": "top-left", "anchor": ["4%", "4%"],
             "size": ["90%", "90%"], "preserve aspect ratio": True},
            {"element type": "part id", "alignment": "top-center", "anchor": ["70%", "35%"],
             "font size": "10%", "fit width": True},
            {"element type": "part name", "alignment": "top-center", "anchor": ["70%", "53%"],
             "font size": "10%", "fit width": True}]},
    "QR-Letter-3x5-Avery": _qr_layout("Letter-3x5-Avery", "landscape", ["50%", "4%"], ["100%", "73%"], "82%", "90%", "5%"),
    "Bar-Letter-2x7-Avery": {
        "label template": "Letter-2x7-Avery", "orientation": "portrait", "elements": [
            {"element type": "bar", "alignment": "top-center", "anchor": ["50%", "10%"],
             "size": ["90%", "55%"], "preserve aspect ratio": False},
            {"element type": "external id", "alignment": "top-center", "anchor": ["50%", "68%"],
             "font size": "10%", "fit width": True},
            {"element type": "part name", "alignment": "top-center", "anchor": ["50%", "81%"],
             "font size": "8%", "font face": "Helvetica", "fit width": True}]},
}

ELEMENT_TYPES = ["qr", "bar", "part id", "external id", "part name", "text"]
ALIGNMENTS = ["top-left", "top-center", "top-right", "center-left", "center", "center-right",
              "bottom-left", "bottom-center", "bottom-right"]
FONTS = ["Helvetica-Bold", "Helvetica", "Courier", "Courier-Bold", "Times-Roman", "Times-Bold"]
# The record's fields as the utility documents them — the text picker's list
# until a matched item shows its own (which adds its specifications).
STANDARD_FIELDS = ["part_id", "external_id", "part_name", "part_type_id", "serial_number",
                   "manufacturer.name", "institution.name", "institution.id", "country_code",
                   "status.name", "created", "creator.name", "comments", "specs_version"]
BAR_ASPECT = 628 / 178   # HWDB's barcode PNG after the utility's crop — its natural shape
FIT_MARGIN = 0.05        # fitted text stays this fraction of the label width clear of the edges
ITEMS_MAX = 1000         # labels per run — one full HWDB read per item
UPLOAD_MAX = 5 * 1024 * 1024

_SUB = re.compile(r"\$\{([^}]*)\}")


def resolve_text(text: str, data: dict) -> str:
    """``${a.b.0.c}`` → the value at that path in ``data`` (dicts by key,
    lists by index); an unresolvable path becomes an empty string, as in
    the utility."""
    def one(m):
        value = data
        try:
            for part in m.group(1).split("."):
                if isinstance(value, dict):
                    value = value[part]
                elif isinstance(value, list):
                    value = value[int(part)]
                else:
                    raise ValueError
        except (KeyError, IndexError, ValueError, TypeError):
            return ""
        return "" if value is None else str(value)
    return _SUB.sub(one, text or "")


def item_data(rec: dict) -> dict:
    """The item record as the utility hands it to a layout: HWDB's
    ``components/{pid}`` data plus ``external_id`` (``PID-CC###`` — country
    code and 3-digit institution id), ``part_type_id`` and ``part_name``
    copied up from ``component_type``, and ``specifications`` unwrapped
    from its one-element list."""
    d = deepcopy(rec or {})
    inst = d.get("institution") if isinstance(d.get("institution"), dict) else {}
    ctype = d.get("component_type") if isinstance(d.get("component_type"), dict) else {}
    try:
        inst_id = f"{int(inst.get('id')):03d}"
    except (TypeError, ValueError):
        inst_id = ""
    d["external_id"] = f"{d.get('part_id', '')}-{d.get('country_code') or ''}{inst_id}"
    d["part_type_id"] = ctype.get("part_type_id", "")
    d["part_name"] = ctype.get("name", "")
    specs = d.get("specifications")
    if isinstance(specs, list):
        d["specifications"] = specs[0] if specs and isinstance(specs[0], dict) else {}
    return d


def get_item(api, pid: str, attempts: int = 3) -> dict:
    """``item_data`` of one HWDB read, retried with a short backoff: the
    FNAL API server drops TLS connections under parallel load
    (``SSLEOFError`` — the same blip hierarchy.py and events.py retry
    around) and the client itself never retries."""
    last = None
    for attempt in range(attempts):
        try:
            return item_data(api.get_component(pid).get("data") or {})
        except Exception as e:  # noqa: BLE001 — transient HTTP / TLS
            last = e
            time.sleep(0.4 * (attempt + 1))
    raise last


def fetch_items(pids: list[str], make_api) -> list[dict]:
    """Every item's record (``item_data``) in ``pids`` order, read in
    parallel with one API client per thread (sessions aren't thread-safe;
    same recipe as itemsedit.live_rows), each read retried. A read that
    still fails raises."""
    tl = local()

    def _init():
        tl.api = make_api()

    with ThreadPoolExecutor(max_workers=4, initializer=_init) as pool:
        return list(pool.map(lambda pid: get_item(tl.api, pid), pids))


def field_paths(data: dict, prefix: str = "", depth: int = 3) -> list[str]:
    """Every dotted path to a scalar in ``data`` (the editor's field
    picker), depth-limited, in sorted order."""
    out = []
    for k, v in (data or {}).items():
        p = f"{prefix}{k}"
        if isinstance(v, dict) and depth > 1:
            out += field_paths(v, p + ".", depth - 1)
        elif isinstance(v, list) and depth > 1:
            for i, item in enumerate(v[:5]):
                if isinstance(item, dict):
                    out += field_paths(item, f"{p}.{i}.", depth - 1)
                elif not isinstance(item, list):
                    out.append(f"{p}.{i}")
        elif not isinstance(v, (dict, list)):
            out.append(p)
    return sorted(out)


def _pct(s, size):
    if isinstance(s, str):
        s = s.strip()
        return 0.01 * float(s[:-1] or 0) * size if s.endswith("%") else float(s or 0)
    return float(s or 0)


SHIFT_MAX = 50.0   # mm — a printer's feed offset is a few mm; anything more is a wrong sheet


def sheet_template(spec: dict) -> dict:
    """Hajime 2026-09-24: a user-defined sheet — ``{"page size": "A4"|"Letter",
    "units": "mm"|"inch", "label size": [w, h], "columns": n, "rows": m,
    "left": x0, "top": y0, "pitch": [dx, dy]}`` (pitch = label size when
    omitted) — as a TEMPLATES-shaped dict, offsets computed. The grid must
    fit the page. ValueError names what is wrong."""
    if not isinstance(spec, dict):
        raise ValueError("sheet must be an object")
    page = PAGE_SIZES.get(spec.get("page size"))
    if not page:
        raise ValueError("paper must be A4 or Letter")
    units = spec.get("units") or page["units"]
    if units not in ("mm", "inch"):
        raise ValueError("units must be mm or inch")

    def num(v, what, lo=0.0):
        try:
            x = float(v)
        except (TypeError, ValueError):
            raise ValueError(f"{what} must be a number")
        if x < lo or x != x:
            raise ValueError(f"{what} must be at least {lo:g}")
        return x

    size = spec.get("label size") or [None, None]
    lw, lh = num(size[0], "label width", 1e-3), num(size[1], "label height", 1e-3)
    cols, rows = int(num(spec.get("columns"), "columns", 1)), int(num(spec.get("rows"), "rows", 1))
    left, top = num(spec.get("left", 0), "left margin"), num(spec.get("top", 0), "top margin")
    pitch = spec.get("pitch") or [lw, lh]
    dx, dy = num(pitch[0], "column pitch", 1e-3), num(pitch[1], "row pitch", 1e-3)
    scale = 1.0 if units == page["units"] else (25.4 if units == "mm" else 1 / 25.4)
    pw, ph = page["size"][0] * scale, page["size"][1] * scale   # the page in the sheet's units
    right, bottom = left + (cols - 1) * dx + lw, top + (rows - 1) * dy + lh
    if right > pw + 1e-6 or bottom > ph + 1e-6:
        raise ValueError(f"the grid runs off the page — {right:g} × {bottom:g} {units} "
                         f"on {pw:g} × {ph:g} {units}")
    return {"description": f"{spec['page size']}, {cols}×{rows} of {lw:g}×{lh:g} {units} labels, "
                           f"{cols * rows} per sheet (custom)",
            "page size": spec["page size"], "units": units, "label size": [lw, lh],
            "horizontal offsets": [left + i * dx for i in range(cols)],
            "vertical offsets": [top + j * dy for j in range(rows)],
            "rounding": 0.0}


def template_for(layout: dict) -> dict:
    """The layout's sheet, derived: a custom ``sheet`` when it carries one,
    else its named template."""
    if isinstance(layout.get("sheet"), dict):
        t = sheet_template(layout["sheet"])
    else:
        t = deepcopy(TEMPLATES[layout.get("label template") or "A4-3x4-Generic"])
    page = PAGE_SIZES[t["page size"]]
    u = UNITS[t.get("units") or page["units"]]
    t["unit"] = u
    t["page"] = [UNITS[page["units"]] * x for x in page["size"]]
    t["label"] = [u * x for x in t["label size"]]
    t["round"] = u * t.get("rounding", 0)
    t["h"] = [u * x for x in t["horizontal offsets"]]
    t["v"] = [u * x for x in t["vertical offsets"]]
    t["per_page"] = len(t["h"]) * len(t["v"])
    return t


def _template(name: str) -> dict:
    return template_for({"label template": name})


def _draw_code(cvs, kind: str, value: str, x, y, w, h, align: str, preserve: bool, rotate):
    """A QR (square) or Code128 (``BAR_ASPECT``) scaled into the ``w``×``h``
    box hung on the anchor as the utility hangs its PNGs."""
    ww, hh = w, h
    if preserve and w > 0 and h > 0:
        natural = 1.0 if kind == "qr" else BAR_ASPECT
        ratio = (w / h) / natural
        if ratio > 1:
            ww = w / ratio
        else:
            hh = h * ratio
    valign, halign = _split_align(align)
    hx = {"left": 0, "center": ww / 2, "right": ww}[halign]
    vy = {"top": 0, "center": hh / 2, "bottom": h}[valign]
    cvs.saveState()
    cvs.translate(x, -y)
    cvs.rotate(rotate)
    cvs.translate(-hx, vy - hh)
    if kind == "qr":
        widget = QrCodeWidget(value, barBorder=1)
        b = widget.getBounds()
        d = Drawing(ww, hh, transform=[ww / (b[2] - b[0]), 0, 0, hh / (b[3] - b[1]),
                                       -b[0], -b[1]])
        d.add(widget)
        renderPDF.draw(d, cvs, 0, 0)
    else:
        probe = code128.Code128(value, barWidth=1, barHeight=hh)
        bc = code128.Code128(value, barWidth=ww / probe.width, barHeight=hh)
        bc.drawOn(cvs, 0, 0)
    cvs.restoreState()


def _split_align(align: str):
    align = align or "top-left"
    if align == "center":
        align = "center-center"
    v, h = align.split("-")
    return v, h


def _draw_text(cvs, text, x, y, font_size, font, align, rotate, fit_w=None):
    """``fit_w`` (an extension of the utility's format: ``"fit width": true``
    with the element's ``size`` width) shrinks the font until the text fits
    that width — long part names on small labels."""
    if font not in FONTS:
        font = "Helvetica-Bold"
    if fit_w and text:
        w = stringWidth(text, font, font_size * 1.35)
        if w > fit_w:
            font_size *= fit_w / w
    valign, halign = _split_align(align)
    v_off = {"top": 0, "center": font_size / 2, "bottom": font_size}[valign]
    cvs.saveState()
    cvs.translate(x, -y)
    cvs.rotate(rotate)
    cvs.setFillColorRGB(0, 0, 0)
    cvs.setFont(font, font_size * 1.35)   # the utility's factor — keeps its presets' sizes
    yy = -font_size + v_off
    if halign == "left":
        cvs.drawString(0, yy, text)
    elif halign == "right":
        cvs.drawRightString(0, yy, text)
    else:
        cvs.drawCentredString(0, yy, text)
    cvs.restoreState()


def draw_label(cvs, tpl: dict, layout: dict, data: dict | None, ui_base: str, outline=False):
    """One label with its top-left corner at the canvas origin (y down =
    negative), as the utility's ``_generate_label``. ``data`` None = an
    empty slot (outline only when asked)."""
    lw, lh = tpl["label"]
    if outline:
        cvs.saveState()
        cvs.setLineWidth(1)
        cvs.setStrokeColorRGB(0.8, 0.8, 0.8)
        cvs.setFillColorRGB(0.9, 0.9, 0.9)
        cvs.roundRect(0, -lh, lw, lh, tpl["round"], fill=1)
        cvs.restoreState()
    if data is None:
        return
    cvs.saveState()
    if layout.get("orientation") == "landscape":
        cvs.translate(0, -lh)
        cvs.rotate(90)
        lw, lh = lh, lw
    for el in layout.get("elements") or []:
        kind = el.get("element type")
        if kind not in ELEMENT_TYPES:
            continue
        ax, ay = el.get("anchor") or [0, 0]
        sw, sh = el.get("size") or ["100%", "100%"]
        x, y = _pct(ax, lw), _pct(ay, lh)
        w, h = _pct(sw, lw), _pct(sh, lh)
        align = el.get("alignment") or "top-left"
        rotate = float(el.get("rotate") or 0)
        if kind in ("qr", "bar"):
            value = f"{ui_base}/view/component/{data.get('part_id', '')}" if kind == "qr" \
                else data.get("external_id", "")
            _draw_code(cvs, kind, value, x, y, w, h, align,
                       bool(el.get("preserve aspect ratio")), rotate)
        else:
            if kind == "text":
                text = resolve_text(el.get("text", ""), data)
            else:
                text = str(data.get({"part id": "part_id", "external id": "external_id",
                                     "part name": "part_name"}[kind], "") or "")
            fit_w = None
            if el.get("fit width"):
                # the element's width, clipped to what the anchor + alignment
                # leave inside the label minus a cutting margin each side
                m = FIT_MARGIN * lw
                halign = _split_align(align)[1]
                avail = {"left": lw - m - x, "right": x - m,
                         "center": 2 * min(x, lw - x) - 2 * m}[halign]
                fit_w = max(1.0, min(w, avail))
            _draw_text(cvs, text, x, y, _pct(el.get("font size", 10), lh),
                       el.get("font face") or "Helvetica-Bold", align, rotate, fit_w=fit_w)
    cvs.restoreState()


def _intro_page(cvs, tpl, num_pages):
    pw, ph = tpl["page"]
    cvs.setPageSize((pw, ph))
    m = 0.5 * units.inch
    cvs.setFont("Helvetica-Bold", 26)
    cvs.setFillColorRGB(0.486, 0.682, 0.835)
    cvs.drawString(m, ph - m - 0.75 * units.inch, "Hardware Item QR/bar Code Labels")
    cvs.setFont("Helvetica", 14)
    cvs.drawString(m, ph - m - 1.25 * units.inch, f"Label Template: {tpl['description']}")
    template_page = cvs.getPageNumber() + 1
    first, last = template_page + 1, template_page + num_pages
    t = cvs.beginText(m, ph - m - 2.25 * units.inch)
    t.setFillColorRGB(0.949, 0.408, 0.169)
    t.textLine(f"Print template on page {template_page} on normal paper and check alignment "
               "with your label")
    t.textLine("sheet. You may need to disable \"fit to page\" or adjust other settings to achieve")
    t.textLine("proper alignment.")
    t.textLine("")
    t.setFillColorRGB(0.486, 0.682, 0.835)
    t.textLine(f"Insert label sheet and print page {first} from this document." if first == last
               else f"Insert label sheet and print pages {first}-{last} from this document.")
    cvs.drawText(t)
    cvs.showPage()


def _template_page(cvs, tpl, shift=(0.0, 0.0)):
    pw, ph = tpl["page"]
    lw, lh = tpl["label"]
    sx, sy = shift
    cvs.setPageSize((pw, ph))
    cvs.setLineWidth(1)
    cvs.setStrokeColorRGB(0.8, 0.8, 0.8)
    cvs.setFillColorRGB(0.9, 0.9, 0.9)
    for v in tpl["v"]:
        for h in tpl["h"]:
            cvs.roundRect(h + sx, ph - v - sy - lh, lw, lh, tpl["round"], fill=1)
    cvs.showPage()


def build_pdf(layouts: list[dict], items: list[dict], ui_base: str, intro: bool = True,
              shift_mm: tuple[float, float] = (0.0, 0.0)) -> bytes:
    """The label sheets: for every sheet the chosen layouts use, the intro +
    alignment pages (``intro``) and then one label per (layout, item) —
    every item under the first layout, then under the next, as the utility's
    label sets print. ``shift_mm`` (right, down) moves everything on every
    sheet, alignment page included — Hajime 2026-09-24: the small correction
    a particular printer needs."""
    buf = io.BytesIO()
    cvs = rl_canvas.Canvas(buf)
    cvs.setTitle("HWDB Item Bar/QR Code Labels")
    cvs.setAuthor("HWDB Explorer")
    sx, sy = (max(-SHIFT_MAX, min(SHIFT_MAX, float(s or 0))) * units.mm for s in shift_mm)
    groups: dict[str, list] = {}
    for lay in layouts:
        try:
            tpl = template_for(lay)
        except (KeyError, ValueError):
            continue
        key = json.dumps(lay.get("sheet"), sort_keys=True) if lay.get("sheet") else lay.get("label template")
        groups.setdefault(key, [tpl, []])[1].extend((lay, it) for it in items)
    for tpl, jobs in groups.values():
        pw, ph = tpl["page"]
        pages = -(-len(jobs) // tpl["per_page"])
        if intro:
            _intro_page(cvs, tpl, pages)
            _template_page(cvs, tpl, (sx, sy))
        cvs.setPageSize((pw, ph))
        slots = [(h, v) for v in tpl["v"] for h in tpl["h"]]
        for i, (lay, it) in enumerate(jobs):
            h, v = slots[i % tpl["per_page"]]
            cvs.saveState()
            cvs.translate(h + sx, ph - v - sy)
            draw_label(cvs, tpl, lay, it, ui_base, outline=bool(lay.get("draw outline")))
            cvs.restoreState()
            if (i + 1) % tpl["per_page"] == 0 or i + 1 == len(jobs):
                cvs.showPage()
    cvs.save()
    return buf.getvalue()


def preview_png(layout: dict, data: dict, ui_base: str, dpi: int = 220) -> bytes:
    """One label (the sheet's label size, grey outline) as a PNG for the
    editor — the same drawing code as the sheets, rasterised by pymupdf."""
    tpl = template_for(layout)
    lw, lh = tpl["label"]
    buf = io.BytesIO()
    cvs = rl_canvas.Canvas(buf, pagesize=(lw, lh))
    cvs.translate(0, lh)
    draw_label(cvs, tpl, layout, data, ui_base, outline=True)
    cvs.showPage()
    cvs.save()
    doc = fitz.open(stream=buf.getvalue(), filetype="pdf")
    try:
        return doc.load_page(0).get_pixmap(dpi=dpi, alpha=False).tobytes("png")
    finally:
        doc.close()


_ID_HEADERS = re.compile(r"^\s*(pid|part[ _-]?id|serial([ _-]?number)?|sn|id)\s*$", re.I)


def upload_entries(name: str, blob: bytes) -> str:
    """The item list in an uploaded CSV / TSV / Excel file, one entry per
    line: the column whose header names a PID or serial, else the first
    column; a header row that is not itself an item is dropped when the
    resolver reports it unmatched."""
    rows: list[list[str]] = []
    if (name or "").lower().endswith((".xlsx", ".xlsm")):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(blob), read_only=True, data_only=True)
        try:
            for r in wb.worksheets[0].iter_rows(values_only=True):
                rows.append(["" if c is None else str(c) for c in r])
        finally:
            wb.close()
    else:
        text = blob.decode("utf-8-sig", errors="replace")
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        rows = [list(r) for r in csv.reader(io.StringIO(text), dialect)]
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        return ""
    col = 0
    for i, c in enumerate(rows[0]):
        if _ID_HEADERS.match(c or ""):
            col = i
            rows = rows[1:]
            break
    return "\n".join((r[col] if col < len(r) else "").strip() for r in rows)
