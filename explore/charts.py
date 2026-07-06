"""Hierarchy chart specs: semantic spec → laid-out SVG model (#55).

One YAML per chart in ``chart_specs/`` (file name = chart id). A spec is
semantic — nodes, tree edges (child → parent) and cable edges, with NO
coordinates. ``_layout()`` reproduces the consortium chart's idiom (parent
box above an indented vertical stack of children; root subtrees arranged
left-to-right inside band rows), so a new chart version only changes the
spec where structure actually changed — a cosmetic shift in the source PDF
never touches it. The extractor (#56) bootstraps node lists; the
label → part_type_id mapping is a separate overlay (#58), not part of the
spec.
"""

from __future__ import annotations

import functools
from pathlib import Path

import yaml

CHART_DIR = Path(__file__).parent / "chart_specs"

BOX_H = 18.0
CHAR_W = 5.2          # ~IBM Plex Sans at font-size 10
NOTE_CHAR_W = 4.7     # annotations render at font-size 9
BOX_PAD = 12.0
MIN_BOX_W = 36.0
INDENT = 16.0         # child stack indent under its parent
VGAP = 5.0            # vertical gap between stacked boxes
TRUNK_X = 7.0         # bracket trunk offset inside the parent's left edge
ROOT_GAP = 40.0       # gap between root subtrees in a band row
BAND_PAD = 14.0       # padding above/below a band row's content
EMPTY_BAND_H = 40.0   # strip height for a band with no nodes (label only)
MARGIN = 30.0
CABLE_LANE = 24.0     # how far right of the boxes a cable elbow runs


def chart_ids() -> list[str]:
    return sorted(p.stem for p in CHART_DIR.glob("*.yaml"))


@functools.lru_cache(maxsize=None)
def svg_chart(chart_id: str) -> dict:
    """Template-ready model of one chart. Callers must not mutate it."""
    with open(CHART_DIR / f"{chart_id}.yaml") as f:
        spec = yaml.safe_load(f) or {}
    return _build(chart_id, spec)


def _box_w(label: str) -> float:
    return max(MIN_BOX_W, BOX_PAD + CHAR_W * len(label))


def _build(chart_id: str, spec: dict) -> dict:
    nodes = {n["id"]: dict(n) for n in spec.get("nodes") or []}
    if len(nodes) != len(spec.get("nodes") or []):
        raise ValueError(f"chart {chart_id}: duplicate node ids")

    # Split edges; tree edges give each child exactly one parent.
    parent: dict[str, str] = {}
    cables = []
    for e in spec.get("edges") or []:
        if e["from"] not in nodes or e["to"] not in nodes:
            raise ValueError(
                f"chart {chart_id}: edge {e['from']}->{e['to']} references an unknown node")
        if e.get("kind") == "cable":
            cables.append(e)
        elif e["from"] in parent:
            raise ValueError(
                f"chart {chart_id}: node {e['from']} has more than one tree parent")
        else:
            parent[e["from"]] = e["to"]

    # Sibling order = the order children appear in the nodes list.
    children: dict[str, list[str]] = {nid: [] for nid in nodes}
    for nid in nodes:
        if nid in parent:
            children[parent[nid]].append(nid)
    roots = [nid for nid in nodes if nid not in parent]

    max_x = 0.0

    def place(nid: str, x: float, y: float) -> tuple[float, float]:
        """Position nid's subtree; returns (height, right edge) incl. notes."""
        nonlocal max_x
        n = nodes[nid]
        n.update(x=x, y=y, w=_box_w(n["label"]), h=BOX_H,
                 cx=x + _box_w(n["label"]) / 2, cy=y + BOX_H / 2)
        right = x + n["w"]
        if n.get("note"):
            right += 6 + NOTE_CHAR_W * len(str(n["note"]))
        cy = y + BOX_H + VGAP
        for c in children[nid]:
            sub_h, sub_right = place(c, x + INDENT, cy)
            cy += sub_h + VGAP
            right = max(right, sub_right)
        max_x = max(max_x, right)
        return cy - VGAP - y, right

    # Band rows, top to bottom. Roots without a band land in the last one.
    band_specs = spec.get("bands") or [{"id": None}]
    default_band = band_specs[-1].get("id")
    bands, y = [], MARGIN
    for band in band_specs:
        b_roots = [r for r in roots
                   if nodes[r].get("band", default_band) == band.get("id")]
        if b_roots:
            x, row_h = MARGIN, 0.0
            for r in b_roots:
                h, right = place(r, x, y + BAND_PAD)
                x = right + ROOT_GAP
                row_h = max(row_h, h)
            band_h = row_h + 2 * BAND_PAD
        else:
            band_h = EMPTY_BAND_H
        bands.append({**band, "y": y, "h": band_h, "label_y": y + 24})
        y += band_h

    unplaced = [nid for nid, n in nodes.items() if "x" not in n]
    if unplaced:
        raise ValueError(
            f"chart {chart_id}: unreachable nodes (edge cycle?): "
            f"{', '.join(sorted(unplaced))}")

    # Bracket connectors: one arrowed trunk into the parent, plain stubs
    # from each child; cables route through a lane right of both endpoints.
    arrows = []
    for p, kids in children.items():
        if not kids:
            continue
        pn, last = nodes[p], nodes[kids[-1]]
        tx, py = pn["x"] + TRUNK_X, pn["y"] + BOX_H
        arrows.append({"color": "#000000", "marker": True,
                       "points": [(tx, last["cy"]), (tx, py)]})
        for c in kids:
            cn = nodes[c]
            arrows.append({"color": "#000000", "marker": False,
                           "points": [(cn["x"], cn["cy"]), (tx, cn["cy"])]})
    for e in cables:
        s, t = nodes[e["from"]], nodes[e["to"]]
        lane = max(s["x"] + s["w"], t["x"] + t["w"]) + CABLE_LANE
        max_x = max(max_x, lane)
        arrows.append({"color": e.get("color", "#ff0000"), "marker": True,
                       "points": [(s["x"] + s["w"], s["cy"]), (lane, s["cy"]),
                                  (lane, t["cy"]), (t["x"] + t["w"], t["cy"])]})
    for a in arrows:
        a["path"] = " ".join(f"{x:g},{y:g}" for x, y in a["points"])
        a["color_key"] = a["color"].lstrip("#")

    meta = spec.get("chart") or {}
    return {
        "id": chart_id,
        "title": meta.get("title", chart_id),
        "source": meta.get("source", ""),
        "width": max_x + MARGIN,
        "height": y + MARGIN,
        "bands": bands,
        "boxes": [n for n in nodes.values()],
        "annotations": [
            {"x": n["x"] + n["w"] + 6, "y": n["cy"], "text": n["note"]}
            for n in nodes.values() if n.get("note")
        ],
        "arrows": arrows,
        "arrow_colors": sorted({(a["color_key"], a["color"]) for a in arrows}),
    }
