"""Bootstrap a hierarchy chart spec from the consortium chart PDF or PPTX (#56).

A one-time aid, not a pipeline (see the #55 pivot): parses one chart page into
a DRAFT of the semantic spec format (explore/chart_specs/) — nodes with
fill/stroke/dashed and a band guess, best-guess edges from chained connector
segments, "N types" annotations attached as notes — for a human to fix up:
sibling order, guessed edge directions, legend boxes, underlined type
references. Ongoing chart updates are small hand edits to the spec, not
re-extraction.

Both source formats the consortium distributes are accepted (dispatch on the
file extension) and emit coordinates in the same 1920x1080 pt space, so the
two drafts / layout overlays can be diffed against each other as a
cross-check. Prefer the .pptx when available: shape labels, fills and glued
connector endpoints come straight out of the slide XML instead of being
reassembled from PDF words and line segments.

The draft always loads through ``explore.charts._build`` (round-trip safe):
an edge that would give a node a second tree parent is emitted as a comment.

The .pptx path is stdlib-only. The PDF path needs PyMuPDF, deliberately NOT
in requirements.txt (dev-only; the server never runs this):

    pip install pymupdf
    python manage.py extract_chart ~/Downloads/HWDB_FD-VD_hierarchy.pptx \\
        --page 2 --title "FD-VD Complete detector (v4)" > draft.yaml
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import yaml
from django.core.management.base import BaseCommand, CommandError

BOX_MIN, BOX_MAX = 6.0, 300.0   # node-box size window (PDF points)
BAND_MIN_W = 1200.0             # a painted rect this wide is a band strip
CHAIN_TOL = 1.5                 # endpoint-coincidence tolerance for chaining
EDGE_TOL = 6.0                  # chain tip → box edge tolerance
NOTE_TOL = 20.0                 # "N types" → nearest box-edge tolerance
NOTE_RX = re.compile(r"^\d+\s+types?$")
_LIGATURES = str.maketrans({"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl"})


def _hex(color) -> str | None:
    if color is None:
        return None
    return "#%02x%02x%02x" % tuple(round(v * 255) for v in color)


def _is_black(hexcolor: str) -> bool:
    return all(int(hexcolor[i:i + 2], 16) < 60 for i in (1, 3, 5))


def _is_red(hexcolor: str) -> bool:
    r, g, b = (int(hexcolor[i:i + 2], 16) for i in (1, 3, 5))
    return r > 150 and g < 90 and b < 90


def _is_light(hexcolor: str) -> bool:
    r, g, b = (int(hexcolor[i:i + 2], 16) for i in (1, 3, 5))
    return 0.299 * r + 0.587 * g + 0.114 * b > 190


def _slugify(label: str) -> str:
    base = re.sub(r"\s*\([^)]*\)\s*$", "", label).lower()
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    return base or "node"


def _attach_labels(rects: list[dict], words: list[tuple]) -> set[int]:
    """Set each rect's ``label`` from the words fully inside it; returns the
    indices of words consumed. Words: (x0, y0, x1, y1, text, block, line)."""
    used: set[int] = set()
    for r in rects:
        inside = [(i, w) for i, w in enumerate(words)
                  if w[0] >= r["x0"] - 1 and w[2] <= r["x1"] + 1
                  and w[1] >= r["y0"] - 1 and w[3] <= r["y1"] + 1]
        inside.sort(key=lambda iw: (iw[1][5], iw[1][6], iw[1][0]))
        label = " ".join(w[4] for _, w in inside)
        r["label"] = label.translate(_LIGATURES)
        used.update(i for i, _ in inside)
    return used


def _lines(words: list[tuple], used: set[int]) -> list[dict]:
    """Group the unconsumed words into text lines (by block/line index)."""
    groups: dict[tuple, list[tuple]] = {}
    for i, w in enumerate(words):
        if i not in used:
            groups.setdefault((w[5], w[6]), []).append(w)
    lines = []
    for ws in groups.values():
        ws.sort(key=lambda w: w[0])
        lines.append({
            "x0": min(w[0] for w in ws), "y0": min(w[1] for w in ws),
            "x1": max(w[2] for w in ws), "y1": max(w[3] for w in ws),
            "text": " ".join(w[4] for w in ws).translate(_LIGATURES),
        })
    return sorted(lines, key=lambda l: (l["y0"], l["x0"]))


def _chains(segments: list[dict]) -> list[dict]:
    """Union same-color segments with coincident endpoints into connector
    chains; a chain's ``tips`` are the endpoints used exactly once."""
    def key(s, x, y):
        return (s["color"], round(x / CHAIN_TOL), round(y / CHAIN_TOL))

    parent = list(range(len(segments)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    by_key: dict[tuple, int] = {}
    for i, s in enumerate(segments):
        for x, y in ((s["x0"], s["y0"]), (s["x1"], s["y1"])):
            k = key(s, x, y)
            if k in by_key:
                parent[find(i)] = find(by_key[k])
            else:
                by_key[k] = i

    groups: dict[int, list[int]] = {}
    for i in range(len(segments)):
        groups.setdefault(find(i), []).append(i)

    chains = []
    for idxs in groups.values():
        counts: dict[tuple, list] = {}
        for i in idxs:
            s = segments[i]
            for x, y in ((s["x0"], s["y0"]), (s["x1"], s["y1"])):
                entry = counts.setdefault(key(s, x, y), [0, (x, y)])
                entry[0] += 1
        chains.append({
            "color": segments[idxs[0]]["color"],
            "tips": [xy for n, xy in counts.values() if n == 1],
        })
    return chains


def _box_at(pt: tuple, nodes: list[dict]) -> dict | None:
    x, y = pt
    hits = [n for n in nodes
            if n["x0"] - EDGE_TOL <= x <= n["x1"] + EDGE_TOL
            and n["y0"] - EDGE_TOL <= y <= n["y1"] + EDGE_TOL]
    return min(hits, key=lambda n: (n["x1"] - n["x0"]) * (n["y1"] - n["y0"]),
               default=None)


def _guess_edges(chains: list[dict], nodes: list[dict]) -> tuple[list[dict], int]:
    """Chains whose tips touch exactly two boxes become edges. Direction is a
    guess: the lower box is taken as the child (``from``)."""
    edges, unresolved = [], 0
    for ch in chains:
        touched: list[dict] = []
        for tip in ch["tips"]:
            n = _box_at(tip, nodes)
            if n is not None and all(t["id"] != n["id"] for t in touched):
                touched.append(n)
        if len(touched) != 2:
            unresolved += 1
            continue
        a, b = touched
        frm, to = (a, b) if a["y0"] >= b["y0"] else (b, a)
        edge = {"from": frm["id"], "to": to["id"]}
        if not _is_black(ch["color"]):
            edge["kind"] = "cable"
            if not _is_red(ch["color"]):
                edge["color"] = ch["color"]
        edges.append(edge)
    return edges, unresolved


def _band_regions(band_rects: list[dict], lines: list[dict]) -> tuple[list[dict], object]:
    """Ordered band entries (strips get their label from the leftmost loose
    text line inside them) plus a region_of(cy) -> band id function."""
    strips = sorted(band_rects, key=lambda b: b["y0"])
    for i, s in enumerate(strips):
        # band titles sit inside the strip or hug its top edge, and are the
        # tallest text there (annotations nearby are much smaller)
        inside = [l for l in lines
                  if s["y0"] - 15 <= (l["y0"] + l["y1"]) / 2 <= s["y1"] and l["x0"] < 400]
        title = max(inside, key=lambda l: (l["y1"] - l["y0"], -l["x0"]), default=None)
        s["label"] = title["text"] if title else None
        s["id"] = _slugify(s["label"]) if s["label"] else f"band-{i + 1}"
        if title:
            s["label_x"] = round(title["x0"], 1)
            s["label_y"] = round((title["y0"] + title["y1"]) / 2, 1)
            lines.remove(title)

    def region_of(cy: float) -> str:
        if strips and cy < strips[0]["y0"]:
            return "top"
        for i, s in enumerate(strips):
            if cy <= s["y1"]:
                return s["id"]
            if i + 1 < len(strips) and cy < strips[i + 1]["y0"]:
                return f"below-{s['id']}"
        return "interior"

    entries = [{"id": "top"}]
    for i, s in enumerate(strips):
        entries.append({"id": s["id"], "label": s["label"], "fill": s["fill"]})
        entries.append({"id": f"below-{s['id']}"} if i + 1 < len(strips)
                       else {"id": "interior"})
    if not strips:
        entries = [{"id": "interior"}]
    return entries, region_of


def _flow(d: dict) -> str:
    return yaml.safe_dump(d, default_flow_style=True, sort_keys=False,
                          width=10 ** 9).strip()


def _classify_notes(nodes: list[dict], lines: list[dict]):
    """Split loose text lines into near-box "N types" notes (attached onto the
    nodes) and everything else (returned as leftovers)."""
    def rect_dist2(n, cx, cy):
        dx = max(n["x0"] - cx, 0.0, cx - n["x1"])
        dy = max(n["y0"] - cy, 0.0, cy - n["y1"])
        return dx * dx + dy * dy

    leftovers = []
    for line in lines:
        cx, cy = (line["x0"] + line["x1"]) / 2, (line["y0"] + line["y1"]) / 2
        if NOTE_RX.match(line["text"]):
            nearest = min(nodes, key=lambda n: rect_dist2(n, cx, cy), default=None)
            if nearest is not None and rect_dist2(nearest, cx, cy) <= NOTE_TOL ** 2:
                nearest["note"] = (nearest.get("note", "") + "; " if nearest.get("note")
                                   else "") + line["text"]
                continue
        leftovers.append(line)
    return leftovers


def _layout_overlay(rects, band_rects, lines, canvas):
    """Assemble the generated layout overlay YAML: node id -> geometry, band
    strips with their real extents, and loose annotation texts."""
    nodes = [r for r in rects if r["label"]]
    seen: dict[str, int] = {}
    for n in nodes:
        base = _slugify(n["label"])
        seen[base] = seen.get(base, 0) + 1
        n["id"] = base if seen[base] == 1 else f"{base}-{seen[base]}"
    _band_regions(band_rects, lines)  # attaches strip labels, consumes titles
    strips = sorted(band_rects, key=lambda b: b["y0"])
    leftovers = _classify_notes(nodes, lines)
    if strips:  # page furniture (title, legend text) lives above the first strip
        leftovers = [l for l in leftovers if l["y1"] > strips[0]["y0"]]

    out = [
        "# GENERATED by `manage.py extract_chart --layout` — do NOT hand-edit.",
        "# PDF-faithful geometry for the sibling spec: regenerate this file",
        "# wholesale whenever the consortium updates the chart PDF.",
        "",
        f"canvas: {_flow(canvas)}",
        "",
        "bands:",
    ]
    out += [f"  - {_flow({k: s[k] for k in ('y0', 'y1', 'fill', 'label', 'label_x', 'label_y') if s.get(k) is not None})}"
            for s in strips]
    out += ["", "nodes:"]
    for n in sorted(nodes, key=lambda n: n["id"]):
        geom = {"x": round(n["x0"], 1), "y": round(n["y0"], 1),
                "w": round(n["x1"] - n["x0"], 1), "h": round(n["y1"] - n["y0"], 1)}
        out.append(f"  {n['id']}: {_flow(geom)}")
    out += ["", "annotations:"]
    out += [f"  - {_flow({'x': round(l['x0'], 1), 'y': round((l['y0'] + l['y1']) / 2, 1), 'text': l['text']})}"
            for l in leftovers]
    return "\n".join(out) + "\n", {"nodes": len(nodes), "annotations": len(leftovers)}


def _draft_spec(rects, band_rects, lines, segments, title, source):
    """Assemble the draft YAML (string) and extraction stats (dict)."""
    nodes = [r for r in rects if r["label"]]
    seen: dict[str, int] = {}
    for n in nodes:
        base = _slugify(n["label"])
        seen[base] = seen.get(base, 0) + 1
        n["id"] = base if seen[base] == 1 else f"{base}-{seen[base]}"

    band_entries, region_of = _band_regions(band_rects, lines)
    for n in nodes:
        n["band"] = region_of((n["y0"] + n["y1"]) / 2)
    used_bands = {n["band"] for n in nodes}
    band_entries = [b for b in band_entries
                    if b["id"] in used_bands or b.get("label")]

    # "N types" annotations become notes on the box whose edge is nearest.
    leftovers = _classify_notes(nodes, lines)

    edges, unresolved = _guess_edges(_chains(segments), nodes)

    band_order = {b["id"]: i for i, b in enumerate(band_entries)}
    nodes.sort(key=lambda n: (band_order.get(n["band"], 99),
                              round(n["x0"] / 60), n["y0"]))

    out = [
        "# DRAFT chart spec generated by extract_chart (#56) — fix up by hand:",
        "# sibling order, guessed edge directions (child -> parent), legend",
        "# boxes, underlined type references. Format: see chart_specs/ (#55).",
        "",
        yaml.safe_dump({"chart": {"title": title, "source": source}},
                       sort_keys=False).rstrip(),
        "",
        "bands:",
    ]
    out += [f"  - {_flow(b)}" for b in band_entries]
    out += ["", "nodes:"]
    for n in nodes:
        d = {"id": n["id"], "label": n["label"], "fill": n["fill"], "band": n["band"]}
        if n.get("stroke"):
            d["stroke"] = n["stroke"]
        if n.get("dashed"):
            d["dashed"] = True
        if _is_light(n["fill"]):
            d["text"] = "#000000"
        if n.get("note"):
            d["note"] = n["note"]
        out.append(f"  - {_flow(d)}")
    out += ["", "edges:"]
    parented: set[str] = set()
    n_dupes = 0
    for e in edges:
        if e.get("kind") != "cable":
            if e["from"] in parented:
                out.append(f"  # - {_flow(e)}  # second tree parent — resolve by hand")
                n_dupes += 1
                continue
            parented.add(e["from"])
        out.append(f"  - {_flow(e)}")
    if leftovers:
        out.append("")
        out.append("# Unplaced text (band titles, arrow labels, underlined type refs):")
        out += [f"#   {l['text']!r} @ ({l['x0']:.0f}, {l['y0']:.0f})" for l in leftovers]
    stats = {"nodes": len(nodes), "edges": len(edges) - n_dupes,
             "cables": sum(1 for e in edges if e.get("kind") == "cable"),
             "dupe_parents": n_dupes, "unresolved_chains": unresolved,
             "leftover_lines": len(leftovers)}
    return "\n".join(out) + "\n", stats


def _extract_pdf(path, page_no):
    """(rects, band_rects, segments, lines, canvas) from a PDF page via
    PyMuPDF: box labels are re-attached from the page's words, connector
    chains from its raw line/curve segments."""
    try:
        import fitz
    except ImportError:
        raise CommandError("PyMuPDF is required: pip install pymupdf (dev-only).")
    page = fitz.open(path)[page_no - 1]

    rects, band_rects, segments = [], [], []
    for d in page.get_drawings():
        r, fill, stroke = d["rect"], d.get("fill"), d.get("color")
        op = d.get("fill_opacity")
        painted = fill is not None and (op is None or op > 0)
        has_re = any(it[0] == "re" for it in d["items"])
        if painted and r.width >= BAND_MIN_W and 20 < r.height < 300:
            band_rects.append({"y0": r.y0, "y1": r.y1, "fill": _hex(fill)})
        elif ((painted or (stroke and has_re))
                and BOX_MIN < r.height < BOX_MAX and 8 < r.width < BOX_MAX):
            fill_hex = _hex(fill) if painted else "#ffffff"
            stroke_hex = _hex(stroke) if stroke else None
            rects.append({
                "x0": r.x0, "y0": r.y0, "x1": r.x1, "y1": r.y1,
                "fill": fill_hex,
                "stroke": stroke_hex if stroke_hex != fill_hex else None,
                "dashed": bool(d.get("dashes") and d["dashes"] != "[] 0"),
            })
        elif stroke and not has_re:
            for it in d["items"]:
                if it[0] == "l":
                    p0, p1 = it[1], it[2]
                elif it[0] == "c":
                    p0, p1 = it[1], it[4]
                else:
                    continue
                segments.append({"x0": p0.x, "y0": p0.y, "x1": p1.x, "y1": p1.y,
                                 "color": _hex(stroke)})

    words = [tuple(w[:7]) for w in page.get_text("words")]
    used = _attach_labels(rects, words)
    lines = _lines(words, used)
    canvas = {"width": round(page.rect.width), "height": round(page.rect.height)}
    return rects, band_rects, segments, lines, canvas


_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
_EMU = 12700.0  # EMU per point — a 1920x1080 pt slide, same space as the PDF


def _sp_text(sp) -> str:
    paras = ["".join(t.text or "" for t in p.findall(f".//{_A}t"))
             for p in sp.iter(f"{_A}p")]
    return " ".join(" ".join(paras).split())


def _solid(el, theme) -> str | None:
    """Color of el's <a:solidFill> child (None if absent or noFill)."""
    sf = el.find(f"{_A}solidFill") if el is not None else None
    if sf is None:
        return None
    srgb = sf.find(f"{_A}srgbClr")
    if srgb is not None:
        return "#" + srgb.get("val").lower()
    sch = sf.find(f"{_A}schemeClr")
    return theme.get(sch.get("val")) if sch is not None else None


def _theme_colors(zf) -> dict:
    out = {}
    root = ET.fromstring(zf.read("ppt/theme/theme1.xml"))
    for el in root.find(f"{_A}themeElements/{_A}clrScheme"):
        name = el.tag.rsplit("}", 1)[1]
        srgb, sysc = el.find(f"{_A}srgbClr"), el.find(f"{_A}sysClr")
        val = srgb.get("val") if srgb is not None else sysc.get("lastClr", "FFFFFF")
        out[name] = "#" + val.lower()
    for alias, name in (("bg1", "lt1"), ("bg2", "lt2"), ("tx1", "dk1"), ("tx2", "dk2")):
        out.setdefault(alias, out[name])
    return out


def _extract_pptx(path, slide_no):
    """(rects, band_rects, segments, lines, canvas) from a pptx slide, stdlib
    only. Box labels come straight off the shapes; glued connector endpoints
    (stCxn/endCxn) are snapped onto the referenced box so the edge guesser
    resolves them exactly; text-box shapes become loose annotation lines."""
    zf = zipfile.ZipFile(path)
    theme = _theme_colors(zf)
    slide = ET.fromstring(zf.read(f"ppt/slides/slide{slide_no}.xml"))
    sz = ET.fromstring(zf.read("ppt/presentation.xml")).find(f"{_P}sldSz")
    canvas = {"width": round(int(sz.get("cx")) / _EMU),
              "height": round(int(sz.get("cy")) / _EMU)}

    rects, band_rects, segments, lines = [], [], [], []
    bboxes: dict[str, tuple] = {}  # shape id -> (x0, y0, x1, y1), for glue
    glues: list[tuple] = []        # (segment index, cxn shape id)

    def walk(container, ax, bx, ay, by):
        """ax/bx, ay/by: child-EMU -> slide-EMU affine (X = ax*x + bx)."""
        for el in container:
            tag = el.tag.rsplit("}", 1)[1]
            if tag == "grpSp":
                x = el.find(f"{_P}grpSpPr/{_A}xfrm")
                off, ext = x.find(f"{_A}off"), x.find(f"{_A}ext")
                cho, che = x.find(f"{_A}chOff"), x.find(f"{_A}chExt")
                sx = int(ext.get("cx")) / (int(che.get("cx")) or 1)
                sy = int(ext.get("cy")) / (int(che.get("cy")) or 1)
                walk(el, ax * sx, ax * (int(off.get("x")) - int(cho.get("x")) * sx) + bx,
                     ay * sy, ay * (int(off.get("y")) - int(cho.get("y")) * sy) + by)
                continue
            if tag not in ("sp", "cxnSp"):
                continue
            sppr = el.find(f"{_P}spPr")
            x = sppr.find(f"{_A}xfrm") if sppr is not None else None
            off = x.find(f"{_A}off") if x is not None else None
            ext = x.find(f"{_A}ext") if x is not None else None
            if off is None or ext is None:
                continue
            ex0, ey0 = int(off.get("x")), int(off.get("y"))
            x0, y0 = (ax * ex0 + bx) / _EMU, (ay * ey0 + by) / _EMU
            x1 = (ax * (ex0 + int(ext.get("cx"))) + bx) / _EMU
            y1 = (ay * (ey0 + int(ext.get("cy"))) + by) / _EMU
            ln = sppr.find(f"{_A}ln")
            stroke = _solid(ln, theme)
            rot = int(x.get("rot") or 0) % 21600000

            if tag == "cxnSp":
                # straight connector = the bbox diagonal; flips pick which one.
                # rot is only ever 180 deg here, which maps the diagonal onto
                # itself, so it never changes the endpoint set.
                flip_h, flip_v = x.get("flipH") == "1", x.get("flipV") == "1"
                seg = {"x0": x1 if flip_h else x0, "y0": y1 if flip_v else y0,
                       "x1": x0 if flip_h else x1, "y1": y0 if flip_v else y1,
                       "color": stroke or "#000000"}
                nv = el.find(f"{_P}nvCxnSpPr/{_P}cNvCxnSpPr")
                for name in ("stCxn", "endCxn"):
                    cxn = nv.find(f"{_A}{name}") if nv is not None else None
                    if cxn is not None:
                        glues.append((len(segments), cxn.get("id")))
                segments.append(seg)
                continue

            if rot in (5400000, 16200000):  # +-90 deg: drawn bbox swaps w/h
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                w, h = x1 - x0, y1 - y0
                x0, x1, y0, y1 = cx - h / 2, cx + h / 2, cy - w / 2, cy + w / 2
            nvpr = el.find(f"{_P}nvSpPr/{_P}cNvPr")
            if nvpr is not None:
                bboxes[nvpr.get("id")] = (x0, y0, x1, y1)
            fill = _solid(sppr, theme)
            text = _sp_text(el)
            if fill and x1 - x0 >= BAND_MIN_W and 20 < y1 - y0 < 300:
                band_rects.append({"y0": y0, "y1": y1, "fill": fill})
                if text:  # band title lives inside the strip shape
                    sizes = [int(r.get("sz")) for r in el.iter(f"{_A}rPr") if r.get("sz")]
                    th = max(sizes, default=1400) / 100.0
                    cy = (y0 + y1) / 2
                    lines.append({"x0": x0 + 4, "y0": cy - th / 2, "text": text,
                                  "x1": x0 + 4 + 0.55 * th * len(text), "y1": cy + th / 2})
            elif (fill or stroke) and BOX_MIN < y1 - y0 < BOX_MAX and 8 < x1 - x0 < BOX_MAX:
                dash = ln.find(f"{_A}prstDash") if ln is not None else None
                rects.append({"x0": x0, "y0": y0, "x1": x1, "y1": y1,
                              "label": text, "fill": fill or "#ffffff",
                              "stroke": stroke if stroke != fill else None,
                              "dashed": dash is not None and dash.get("val") != "solid"})
            elif text:
                # text boxes are padded well beyond the text; shrink the width
                # to a text estimate so note/box proximity matches the PDF's
                sizes = [int(r.get("sz")) for r in el.iter(f"{_A}rPr") if r.get("sz")]
                tw = 0.55 * max(sizes, default=1400) / 100.0 * len(text)
                lines.append({"x0": x0, "y0": y0, "x1": min(x1, x0 + tw), "y1": y1,
                              "text": text})

    walk(slide.find(f"{_P}cSld/{_P}spTree"), 1.0, 0.0, 1.0, 0.0)

    for i, sid in glues:  # clamp the endpoint nearer to the glued box onto it
        box = bboxes.get(sid)
        if box is None:
            continue
        seg = segments[i]

        def gap2(px, py):
            dx = max(box[0] - px, 0.0, px - box[2])
            dy = max(box[1] - py, 0.0, py - box[3])
            return dx * dx + dy * dy

        end = ("x0", "y0") if gap2(seg["x0"], seg["y0"]) <= gap2(seg["x1"], seg["y1"]) \
            else ("x1", "y1")
        # nearest-point projection, not the center: connectors glued to the
        # same box must keep distinct endpoints or they chain into one blob
        seg[end[0]] = min(max(seg[end[0]], box[0]), box[2])
        seg[end[1]] = min(max(seg[end[1]], box[1]), box[3])

    lines.sort(key=lambda l: (l["y0"], l["x0"]))
    return rects, band_rects, segments, lines, canvas


class Command(BaseCommand):
    help = "Bootstrap a DRAFT hierarchy chart spec from a consortium chart PDF or PPTX page (dev-only; the PDF path needs pymupdf)."

    def add_arguments(self, parser):
        parser.add_argument("file", help="Path to the consortium chart PDF or PPTX.")
        parser.add_argument("--page", type=int, default=2,
                            help="1-based PDF page / pptx slide to extract (default: 2).")
        parser.add_argument("--title", default=None,
                            help="Chart title (default: derived from the file name).")
        parser.add_argument("--layout", action="store_true",
                            help="Emit a layout overlay (node id -> geometry, band "
                                 "strips, loose annotation texts) instead of a draft "
                                 "spec. Regenerate it wholesale on every chart "
                                 "update; node ids match the draft's.")

    def handle(self, *args, **opts):
        path = Path(opts["file"])
        is_pptx = path.suffix.lower() == ".pptx"
        try:
            extract = _extract_pptx if is_pptx else _extract_pdf
            rects, band_rects, segments, lines, canvas = extract(path, opts["page"])
        except CommandError:
            raise
        except Exception as exc:
            raise CommandError(f"cannot extract {path} page {opts['page']}: {exc}")

        if opts["layout"]:
            overlay, stats = _layout_overlay(rects, band_rects, lines, canvas)
            self.stdout.write(overlay)
            self.stderr.write(
                f"layout overlay: {stats['nodes']} node geometries, "
                f"{stats['annotations']} annotation texts."
            )
            return
        title = opts["title"] or path.stem
        source = f"{path.name}, {'slide' if is_pptx else 'page'} {opts['page']}"
        draft, stats = _draft_spec(rects, band_rects, lines, segments, title, source)
        self.stdout.write(draft)
        self.stderr.write(
            f"extracted {stats['nodes']} nodes, {stats['edges']} edges "
            f"({stats['cables']} cables, {stats['dupe_parents']} duplicate parents "
            f"commented out), {stats['unresolved_chains']} connector chains unresolved, "
            f"{stats['leftover_lines']} text lines unplaced."
        )

