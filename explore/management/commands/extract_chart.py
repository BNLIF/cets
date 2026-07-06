"""Bootstrap a hierarchy chart spec from the consortium chart PDF (#56).

A one-time aid, not a pipeline (see the #55 pivot): parses one PDF page into
a DRAFT of the semantic spec format (explore/chart_specs/) — nodes with
fill/stroke/dashed and a band guess, best-guess edges from chained connector
segments, "N types" annotations attached as notes — for a human to fix up:
sibling order, guessed edge directions, legend boxes, underlined type
references. Ongoing chart updates are small hand edits to the spec, not
re-extraction.

The draft always loads through ``explore.charts._build`` (round-trip safe):
an edge that would give a node a second tree parent is emitted as a comment.

PyMuPDF is required and deliberately NOT in requirements.txt (dev-only; the
server never runs this):

    pip install pymupdf
    python manage.py extract_chart ~/Downloads/HWDB_FD-VD_hierarchy.pptx.pdf \\
        --page 2 --title "FD-VD Complete detector (v4)" > draft.yaml
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml
from django.core.management.base import BaseCommand, CommandError

BOX_MIN, BOX_MAX = 6.0, 300.0   # node-box size window (PDF points)
BAND_MIN_W = 1200.0             # a painted rect this wide is a band strip
CHAIN_TOL = 1.5                 # endpoint-coincidence tolerance for chaining
EDGE_TOL = 6.0                  # chain tip → box edge tolerance
NOTE_TOL = 20.0                 # "N types" → nearest box-edge tolerance
NOTE_RX = re.compile(r"^\d+\s+types?$")


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
        r["label"] = label.replace("ﬂ", "fl").replace("ﬁ", "fi")
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
            "text": " ".join(w[4] for w in ws).replace("ﬂ", "fl").replace("ﬁ", "fi"),
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


def _draft_spec(rects, band_rects, words, segments, title, source):
    """Assemble the draft YAML (string) and extraction stats (dict)."""
    used = _attach_labels(rects, words)
    nodes = [r for r in rects if r["label"]]
    seen: dict[str, int] = {}
    for n in nodes:
        base = _slugify(n["label"])
        seen[base] = seen.get(base, 0) + 1
        n["id"] = base if seen[base] == 1 else f"{base}-{seen[base]}"

    lines = _lines(words, used)
    band_entries, region_of = _band_regions(band_rects, lines)
    for n in nodes:
        n["band"] = region_of((n["y0"] + n["y1"]) / 2)
    used_bands = {n["band"] for n in nodes}
    band_entries = [b for b in band_entries
                    if b["id"] in used_bands or b.get("label")]

    # "N types" annotations become notes on the box whose edge is nearest.
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


class Command(BaseCommand):
    help = "Bootstrap a DRAFT hierarchy chart spec from a consortium chart PDF page (dev-only, needs pymupdf)."

    def add_arguments(self, parser):
        parser.add_argument("pdf", help="Path to the consortium chart PDF.")
        parser.add_argument("--page", type=int, default=2,
                            help="1-based PDF page to extract (default: 2).")
        parser.add_argument("--title", default=None,
                            help="Chart title (default: derived from the file name).")

    def handle(self, *args, **opts):
        try:
            import fitz
        except ImportError:
            raise CommandError("PyMuPDF is required: pip install pymupdf (dev-only).")

        try:
            page = fitz.open(opts["pdf"])[opts["page"] - 1]
        except Exception as exc:
            raise CommandError(f"cannot open {opts['pdf']} page {opts['page']}: {exc}")

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
        title = opts["title"] or Path(opts["pdf"]).stem
        source = f"{Path(opts['pdf']).name}, page {opts['page']}"
        draft, stats = _draft_spec(rects, band_rects, words, segments, title, source)
        self.stdout.write(draft)
        self.stderr.write(
            f"extracted {stats['nodes']} nodes, {stats['edges']} edges "
            f"({stats['cables']} cables, {stats['dupe_parents']} duplicate parents "
            f"commented out), {stats['unresolved_chains']} connector chains unresolved, "
            f"{stats['leftover_lines']} text lines unplaced."
        )

