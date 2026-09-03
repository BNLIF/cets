"""Consortium checklist forms (issue #95, phase 1) — the iPad app's
checklist scenes as schema-driven web forms (Hajime/Greg, 2026-08-07).

- **Schema** — one JSON per checklist on the component TYPE's images, named
  ``Checklist_{typeid}_{name}.json`` (same convention as the ES config;
  re-uploading a filename appends a version and the newest wins). A type may
  carry several named checklists.
- **Shape** — a vertical flow of sections, each a list of typed fields from
  a CLOSED vocabulary mirroring the iPad widgets: ``check`` (tri-state),
  ``number`` (units + tolerance), ``table`` (point-measurement grid),
  ``text``, ``textarea``, ``datetime``, ``select``, ``photo``, ``qr``,
  ``steps``, ``static``, ``imagemap`` — plus a ``row`` grouping that renders its child
  fields side by side (stacked on phones). Order IS the layout; there are
  no coordinates.
- **Data** — submissions land in HWDB only: photos post first (for their
  image_ids), then one test record of the schema's ``test_type_name`` whose
  ``test_data.DATA`` is keyed ``{section title: {field label: value}}``.
  Nothing permanent is stored locally.
"""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

FIELD_TYPES = {"check", "number", "table", "text", "textarea", "datetime",
               "select", "photo", "qr", "steps", "static", "link", "imagemap"}

# Field types whose value may ALSO be folded into the item's latest
# specifications DATA (the ``to_spec`` flag, #96 — "sometimes they do store
# in the Item Specifications as well", Hajime 2026-08-07).
SPEC_CAPABLE = {"check", "number", "table", "text", "textarea", "datetime",
                "select", "qr"}


def available(api, part_type_id: str, rows=None) -> list[dict]:
    """``[{name, image_id, image_name, created}]`` — the newest row per
    checklist name among the type's ``Checklist_{typeid}_{name}.json``
    images. ``rows`` lets a caller that already listed the type's images
    (the part page shares the ES config's listing) skip the fetch. Any
    failure is an empty list — the card just doesn't render."""
    try:
        if rows is None:
            rows = api.get_component_type_images(part_type_id).get("data") or []
        prefix = f"Checklist_{part_type_id}_"
        best = {}
        for r in rows:
            n = (r.get("image_name") or "") if isinstance(r, dict) else ""
            if not (n.startswith(prefix) and n.lower().endswith(".json")):
                continue
            name = n[len(prefix):-len(".json")]
            cur = best.get(name)
            if name and (cur is None
                         or (r.get("created") or "") > (cur.get("created") or "")):
                best[name] = r
        return [{"name": k, "image_id": str(v["image_id"]),
                 "image_name": v.get("image_name"), "created": v.get("created")}
                for k, v in sorted(best.items())]
    except Exception as e:
        logger.warning("checklist listing for %s failed: %s", part_type_id, e)
        return []


def load(api, part_type_id: str, name: str):
    """``(normalized schema | None, message)`` for one named checklist."""
    row = next((r for r in available(api, part_type_id) if r["name"] == name), None)
    if row is None:
        return None, f"No checklist “{name}” on type {part_type_id}."
    try:
        cfg = json.loads(api.get_image_response(row["image_id"]).content)
    except Exception as e:
        logger.warning("checklist %s/%s failed to load: %s", part_type_id, name, e)
        return None, f"Checklist {row['image_name']} failed to load ({e})."
    if not isinstance(cfg, dict):
        return None, f"Checklist {row['image_name']} is not a JSON object."
    return normalize(cfg, name), f"Schema: {row['image_name']}"


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _tol_range(f: dict):
    """``(min, max, display range)`` from a tolerance spec: explicit min/max,
    or nominal ± tol — the field-level vocabulary, reused per table column
    (#109 review)."""
    nominal, tol = _num(f.get("nominal")), _num(f.get("tol"))
    lo, hi = _num(f.get("min")), _num(f.get("max"))
    if nominal is not None and tol is not None:
        # round: 1.6 + 0.1 must be 1.7, not 1.7000000000000002
        lo = round(nominal - tol, 9) if lo is None else lo
        hi = round(nominal + tol, 9) if hi is None else hi
    rng = (f"{lo:g} – {hi:g}" if lo is not None and hi is not None
           else f"≥ {lo:g}" if lo is not None
           else f"≤ {hi:g}" if hi is not None else "")
    return lo, hi, rng


# #109: computed table cells — only digits, cell refs and + - * / ( ) ever
# reach the evaluator.
_FORMULA_CHARS = re.compile(r"^[0-9.\s()+\-*/Cc]+$")
_FORMULA_TOKEN = re.compile(r"[Cc]\d+|\d+\.?\d*|\.\d+|[()+\-*/]|\S")


def _eval_formula(expr: str, values: list) -> float | None:
    """Hajime's cell arithmetic (#109): ``C1 + C2*(C3/C4)`` over one table
    row, ``C<n>`` = the 1-based column's value. A tiny recursive-descent
    parser over + - * / ( ) and numbers — deliberately NOT a general
    evaluator. None on any problem: bad syntax, a missing or non-numeric
    referenced cell, division by zero."""
    tokens = _FORMULA_TOKEN.findall(expr)
    pos = 0

    def peek():
        return tokens[pos] if pos < len(tokens) else None

    def factor():
        nonlocal pos
        t = peek()
        if t is None:
            raise ValueError
        if t == "-":
            pos += 1
            return -factor()
        if t == "(":
            pos += 1
            v = exprn()
            if peek() != ")":
                raise ValueError
            pos += 1
            return v
        if t[0] in "Cc":
            pos += 1
            i = int(t[1:]) - 1
            if not 0 <= i < len(values) or not isinstance(values[i], (int, float)) \
                    or isinstance(values[i], bool):
                raise ValueError
            return float(values[i])
        pos += 1
        return float(t)   # ValueError on anything else

    def term():
        nonlocal pos
        v = factor()
        while peek() in ("*", "/"):
            op = tokens[pos]
            pos += 1
            rhs = factor()
            if op == "/":
                if rhs == 0:
                    raise ValueError
                v /= rhs
            else:
                v *= rhs
        return v

    def exprn():
        nonlocal pos
        v = term()
        while peek() in ("+", "-"):
            op = tokens[pos]
            pos += 1
            v = v + term() if op == "+" else v - term()
        return v

    try:
        result = exprn()
        if pos != len(tokens):
            return None
        return result
    except (ValueError, ZeroDivisionError, RecursionError):
        return None


# #115: named table tints → light colors, painted as-is on the cells (the
# inputs keep their own ground). Light so the row stays a wash, not a block.
_TINTS = {"yellow": "#fff2cc", "green": "#d9ead3", "blue": "#cfe2f3",
          "red": "#f4cccc", "gray": "#efefef", "grey": "#efefef"}


def _norm_field(f: dict) -> dict | None:
    """One field off the schema, or None to drop it (unknown type, blank
    label, or a widget missing what defines it)."""
    t = str(f.get("type") or "").strip().lower()
    label = str(f.get("label") or "").strip()
    if t == "static":
        # image_id = a reference image uploaded onto the TYPE's images (#97
        # review — the iPad scenes' P1–P10 measurement diagrams), served
        # through the bearer image proxy; image = an external URL.
        # checklist = a jump link to another checklist (#118): name only →
        # this item's checklist of that name; with a part_type_id → that
        # type's PID chooser (a malformed type id falls back to name-only).
        ctid = str(f.get("part_type_id") or "").strip().upper()
        out = {"type": t, "label": label,
               "image": str(f.get("image") or "").strip(),
               "image_id": str(f.get("image_id") or "").strip(),
               "url": str(f.get("url") or "").strip(),
               "note": str(f.get("note") or "").strip(),
               "checklist": str(f.get("checklist") or "").strip(),
               "checklist_type": ctid if re.fullmatch(r"[A-Z]\d{11}", ctid) else ""}
        for k in ("col", "span", "newline"):   # #120: grid placement hints
            if f.get(k) is not None:
                out[k] = f[k]
        return out if (out["image"] or out["image_id"] or out["url"]
                       or out["note"] or out["checklist"]) else None
    if t not in FIELD_TYPES or not label:
        return None
    out = {"type": t, "label": label, "units": str(f.get("units") or "").strip(),
           "to_spec": bool(f.get("to_spec")) and t in SPEC_CAPABLE}
    # #120: grid placement hints — only consumed in a section that declares
    # ``grid``; popped (or dropped) by normalize either way.
    for k in ("col", "span", "newline"):
        if f.get(k) is not None:
            out[k] = f[k]
    if t == "link":
        # subcomponent link (#96): the scanned child PID is linked into the
        # named functional position — or the first free one matching the
        # child's type when no position is pinned (the scan page's rule).
        out["position"] = str(f.get("position") or "").strip()
    if t in ("qr", "link", "imagemap"):
        # #112 (Hajime): the box may require a Type ID — a scan of any other
        # type won't fill it (checked in the scan modal, painted on typed
        # input, and dropped here at parse). Malformed ids are ignored.
        # On an imagemap (#113) the guard applies to every slot.
        tid = str(f.get("type_id") or "").strip().upper()
        if re.fullmatch(r"[A-Z]\d{11}", tid):
            out["type_id"] = tid
    if t == "imagemap":
        # #113 (Top CRP): a background drawing with tappable slots — tap a
        # slot to scan the board mounted there. Slots are percent coordinates
        # on the image; values store ``{slot label: PID}``. The image is a
        # reference picture on the TYPE's HWDB images (as ``static``'s
        # image_id); slots outside the image or unnamed are dropped.
        out["image_id"] = str(f.get("image_id") or "").strip()
        slots, seen = [], set()
        for s in f.get("slots") or []:
            if not isinstance(s, dict):
                continue
            lab = str(s.get("label") or "").strip()
            x, y = _num(s.get("x")), _num(s.get("y"))
            if not lab or lab in seen or x is None or y is None \
                    or not (0 <= x <= 100 and 0 <= y <= 100):
                continue
            seen.add(lab)
            slots.append({"label": lab, "x": round(x, 2), "y": round(y, 2)})
        out["slots"] = slots
        if not out["image_id"] or not slots:
            return None
    if t in ("number", "table"):
        out["min"], out["max"], out["range"] = _tol_range(f)
    if t == "table":
        # #109 (Hajime): a column may be {"label": …, "formula": "C1 + C2*(C3/C4)"}
        # — computed from the row's other cells, C<n> = 1-based column index —
        # and may carry its OWN tolerance (nominal/tol or min/max), overriding
        # the table-wide one (a computed Total has a different range).
        cols, formulas, texts, col_tol = [], {}, {}, {}
        for c in f.get("columns") or []:
            if isinstance(c, dict):
                label = str(c.get("label") or "").strip()
                fx = str(c.get("formula") or "").strip()
                # #114 (HVS): "text" makes a constant cell (the Expected
                # column) — fixed display, not editable, referenceable by
                # formulas when it's a plain number. Text beats formula.
                tx = str(c.get("text") or "").strip()
                if label and tx:
                    texts[label] = tx
                elif label and fx and _FORMULA_CHARS.match(fx):
                    formulas[label] = fx
                lo, hi, rng = _tol_range(c)
                if label and (lo is not None or hi is not None):
                    col_tol[label] = {"min": lo, "max": hi, "range": rng}
            else:
                label = str(c).strip()
            if label:
                cols.append(label)
        out["columns"] = cols
        # #115 (HVS): a table-wide background tint keyed to the reference
        # drawing (one iPad row = one Dashboard table). Named colors map to
        # base hexes; anything else must be #rrggbb or it's dropped. The
        # template mixes the base into the theme surface, so tints stay
        # legible in dark mode.
        color = str(f.get("color") or "").strip().lower()
        color = _TINTS.get(color, color)
        if re.fullmatch(r"#[0-9a-f]{6}", color):
            out["color"] = color
        if texts:
            out["texts"] = texts
        if formulas:
            out["formulas"] = formulas
        if col_tol:
            out["col_tol"] = col_tol
        if not out["columns"]:
            return None
    if t == "select":
        out["options"] = [str(o).strip() for o in f.get("options") or []
                          if str(o).strip()]
        if not out["options"]:
            return None
    if t == "steps":
        # #106: leading spaces indent a step under the previous one (2 spaces
        # per level, editor convention); the stored value key is the stripped
        # text either way, so indenting later never orphans old submissions.
        out["steps"] = [str(s).rstrip() for s in f.get("steps") or []
                        if str(s).strip()]
        if not out["steps"]:
            return None
    return out


# #103: HWDB's standard item fields a checklist can carry (Hajime's "default
# fields" — the iPad app's fixed header). On by default; a schema lists the
# subset it wants in ``item_fields`` (``[]`` = none).
ITEM_FIELDS = ["manufacturer", "status", "is_installed", "qaqc_uploaded",
               "certified_qaqc", "location", "serial_number", "item_comments",
               "test_comments"]
ITEM_FIELD_LABELS = {
    "manufacturer": "Manufacturer", "status": "Component status",
    "is_installed": "Is installed", "qaqc_uploaded": "QA/QC uploaded",
    "certified_qaqc": "Certified QA/QC", "location": "Location",
    "serial_number": "Serial number", "item_comments": "Item comments",
    "test_comments": "Test comments",
}
# HWDB has no status-vocabulary endpoint (probed 2026-08-26) — the
# Dashboard's list, shared with the exec summary.
STATUS_OPTIONS = [
    {"value": 0, "label": "Unknown"},
    {"value": 100, "label": "In Fabrication"},
    {"value": 110, "label": "Waiting on QA/QC Tests"},
    {"value": 120, "label": "QA/QC Tests - Passed All"},
    {"value": 130, "label": "QA/QC Tests - Non-conforming"},
    {"value": 140, "label": "QA/QC Tests - Use As Is"},
    {"value": 150, "label": "In Rework"},
    {"value": 160, "label": "In Repair"},
    {"value": 170, "label": "Permanently Unavailable"},
    {"value": 180, "label": "Broken or Needs Repair"},
]
_ITEM_FLAGS = ("is_installed", "qaqc_uploaded", "certified_qaqc")


def _grid_place(leaves: list, n: int) -> list:
    """#120: deterministic cursor placement on an ``n``-column grid. Each
    leaf's optional ``col`` (start column), ``span`` (columns occupied, or
    "full") and ``newline`` are consumed into ``g = {r, c, s}`` — explicit
    coordinates, so gaps are expressible and overlaps impossible. A ``col``
    already passed on the current line wraps to the next line; a span that
    doesn't fit in the remainder wraps too."""
    r, c = 1, 1
    for f in leaves:
        span, col, nl = f.pop("span", None), f.pop("col", None), f.pop("newline", None)
        s = n if span == "full" else max(1, min(int(_num(span) or 1), n))
        if nl and c > 1:
            r, c = r + 1, 1
        tgt = _num(col)
        if tgt is not None:
            tgt = max(1, min(int(tgt), n - s + 1))
            if tgt < c:
                r += 1
            c = tgt
        elif c + s - 1 > n:
            r, c = r + 1, 1
        f["g"] = {"r": r, "c": c, "s": s}
        c += s
        if c > n:
            r, c = r + 1, 1
    return leaves


def normalize(cfg: dict, name: str) -> dict:
    """A tolerant read of the schema JSON. Unknown field types and malformed
    entries are dropped; a ``row`` groups its (non-row) children side by
    side. Every kept leaf gets a stable ``key`` used as its form-input
    name — labels stay display-only and may repeat across sections."""
    schema = {"name": str(cfg.get("name") or "").strip() or name,
              "test_type_name": str(cfg.get("test_type_name") or "").strip(),
              "instructions": str(cfg.get("instructions") or "").strip(),
              # #97: HWDB role ids allowed to submit; empty = anyone (the ES
              # signee convention).
              "roles": [r for r in (cfg.get("roles") or [])
                        if isinstance(r, int) and not isinstance(r, bool)],
              # #103: absent = every standard field; a list = that subset
              "item_fields": ([f for f in cfg["item_fields"] if f in ITEM_FIELDS]
                              if isinstance(cfg.get("item_fields"), list)
                              else list(ITEM_FIELDS)),
              "sections": []}
    for si, s in enumerate(cfg.get("sections") or []):
        if not isinstance(s, dict):
            continue
        title = str(s.get("title") or "").strip()
        fields = []
        for fi, f in enumerate(s.get("fields") or []):
            if not isinstance(f, dict):
                continue
            if str(f.get("type") or "").strip().lower() == "row":
                kids = []
                for ki, k in enumerate(f.get("fields") or []):
                    if not isinstance(k, dict):
                        continue
                    # #117: a "column" inside a row stacks several fields in
                    # ONE cell (one field left, three stacked right). A
                    # single-field column is just that field.
                    if str(k.get("type") or "").strip().lower() == "column":
                        stack = []
                        for ji, kk in enumerate(k.get("fields") or []):
                            nk = _norm_field(kk) if isinstance(kk, dict) else None
                            if nk:
                                nk["key"] = f"f{si}-{fi}-{ki}-{ji}"
                                stack.append(nk)
                        if len(stack) == 1:
                            kids.append(stack[0])
                        elif stack:
                            kids.append({"type": "column", "fields": stack})
                        continue
                    nk = _norm_field(k)
                    if nk:
                        nk["key"] = f"f{si}-{fi}-{ki}"
                        kids.append(nk)
                if kids:
                    fields.append({"type": "row", "fields": kids})
            else:
                nf = _norm_field(f)
                if nf:
                    nf["key"] = f"f{si}-{fi}"
                    fields.append(nf)
        if title and fields:
            sec = {"title": title, "fields": fields}
            # #120: a section may declare a column grid; its fields are then
            # flattened (row/column trees don't mix with a grid) and placed
            # by the cursor algorithm. Absent/1 = today's vertical flow.
            g = _num(s.get("grid"))
            if g is not None and 2 <= int(g) <= 4:
                flat = []
                for f in fields:
                    flat.extend(_row_leaves(f))
                sec["grid"] = int(g)
                sec["fields"] = _grid_place(flat, int(g))
            else:
                for f in fields:
                    for leaf in _row_leaves(f):
                        for k in ("col", "span", "newline"):
                            leaf.pop(k, None)
            if s.get("collapsed") is True:
                sec["collapsed"] = True            # #98: opens folded
            if isinstance(s.get("when"), dict):
                sec["when"] = s["when"]            # resolved below
            schema["sections"].append(sec)
    _resolve_when(schema)
    return schema


def _resolve_when(schema: dict) -> None:
    """#98: a section's ``when: {field, equals}`` names one of the schema's
    ``select`` fields by label and one of its options; resolve it to the
    select's input key (the runtime toggles on that input's value) or drop
    it when nothing matches, so a typo shows the section rather than hiding
    it forever."""
    selects = {leaf["label"]: leaf for _, leaf in leaf_fields(schema)
               if leaf["type"] == "select"}
    for sec in schema["sections"]:
        w = sec.pop("when", None)
        if not w:
            continue
        label = str(w.get("field") or "").strip()
        eq = str(w.get("equals") or "").strip()
        sel = selects.get(label)
        if sel and eq in sel["options"]:
            sec["when"] = {"field": label, "key": sel["key"], "equals": eq}


def _row_leaves(f: dict) -> list[dict]:
    """Flat leaves of one top-level field — a row's cells, with any stacked
    ``column`` cells (#117) unwrapped."""
    if f["type"] != "row":
        return [f]
    out = []
    for k in f["fields"]:
        out.extend(k["fields"] if k.get("type") == "column" else [k])
    return out


def leaf_fields(schema: dict):
    """Yield ``(section title, field)`` for every leaf (rows flattened)."""
    for sec in schema["sections"]:
        for f in sec["fields"]:
            for leaf in _row_leaves(f):
                yield sec["title"], leaf


def _fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


def bind(schema: dict, test_data: dict | None) -> dict:
    """A deep copy of the schema with each leaf's display value filled from
    a previous submission's ``DATA`` (the iPad's "revive" — blank when the
    item has none). Tables get ``cells`` and steps get ``items`` rows so the
    template never has to zip lists."""
    import copy
    bound = copy.deepcopy(schema)
    data = (test_data or {}).get("DATA")
    data = data if isinstance(data, dict) else {}
    for sec in bound["sections"]:
        sdata = data.get(sec["title"])
        sdata = sdata if isinstance(sdata, dict) else {}
        for f in sec["fields"]:
            for leaf in _row_leaves(f):
                _bind_leaf(leaf, sdata.get(leaf["label"]))
    return bound


def _bind_leaf(f: dict, v) -> None:
    t = f["type"]
    if t == "check":
        f["value"] = "pass" if v is True else ("fail" if v is False else "")
    elif t == "table":
        cells = v if isinstance(v, dict) else {}
        ct = f.get("col_tol") or {}
        tx = f.get("texts") or {}
        # a column's own tolerance replaces the table-wide one wholesale;
        # a constant cell (#114) always shows its fixed text, never paints
        f["cells"] = [{"column": c, "name": f"{f['key']}-c{i}",
                       "value": tx[c] if c in tx else _fmt(cells.get(c)),
                       "formula": (f.get("formulas") or {}).get(c, ""),
                       "text": tx.get(c, ""),
                       "min": None if c in tx else
                              (ct[c]["min"] if c in ct else f["min"]),
                       "max": None if c in tx else
                              (ct[c]["max"] if c in ct else f["max"]),
                       "range": ct[c]["range"] if c in ct and c not in tx else ""}
                      for i, c in enumerate(f["columns"])]
    elif t == "steps":
        done = v if isinstance(v, dict) else {}
        f["items"] = [{"label": s.strip(), "name": f"{f['key']}-s{i}",
                       "level": min((len(s) - len(s.lstrip(" "))) // 2, 4),
                       "done": bool(done.get(s.strip()))}
                      for i, s in enumerate(f["steps"])]
    elif t == "imagemap":
        vals = v if isinstance(v, dict) else {}
        f["items"] = [{"label": s["label"], "x": s["x"], "y": s["y"],
                       "name": f"{f['key']}-m{i}",
                       "value": _fmt(vals.get(s["label"]))}
                      for i, s in enumerate(f["slots"])]
    elif t == "photo":
        f["existing"] = v if isinstance(v, dict) and v.get("image_id") else None
    elif t != "static":   # number, text, textarea, datetime, select, qr
        f["value"] = _fmt(v)


def _num_or_str(raw: str):
    n = _num(raw)
    return n if n is not None else raw


def parse(schema: dict, post) -> dict:
    """The submitted form as the test record's ``DATA``
    (``{section: {label: value}}``). Blank inputs are omitted; an untouched
    tri-state check is omitted too (blank = "not inspected", the iPad
    convention). Photos are merged in by the view after uploading."""
    data = {}
    for title, f in leaf_fields(schema):
        t, key = f["type"], f["key"]
        if t in ("static", "photo"):
            continue
        if t == "check":
            raw = post.get(key) or ""
            if raw in ("pass", "fail"):
                value = raw == "pass"
            else:
                continue
        elif t == "number":
            raw = (post.get(key) or "").strip()
            if not raw:
                continue
            value = _num_or_str(raw)
        elif t == "table":
            formulas = f.get("formulas") or {}
            texts = f.get("texts") or {}
            # #114: constant cells first, so formulas can reference a numeric
            # one; posted overrides for them are ignored like formulas'.
            cells = {c: _num_or_str(tx) for c, tx in texts.items()}
            typed = False
            for i, c in enumerate(f["columns"]):
                if c in formulas or c in texts:
                    continue   # computed/fixed below, whatever was posted
                raw = (post.get(f"{key}-c{i}") or "").strip()
                if raw:
                    cells[c] = _num_or_str(raw)
                    typed = True
            # an untouched table stays omitted — constants alone (and what
            # they'd compute) aren't a submission
            if not typed:
                continue
            # #109: computed columns, left to right — a formula may reference
            # plain cells and computed ones to its LEFT; anything unresolvable
            # leaves the cell out.
            for c in f["columns"]:
                if c in formulas:
                    v = _eval_formula(formulas[c],
                                      [cells.get(col) for col in f["columns"]])
                    if v is not None:
                        cells[c] = round(v, 9)
            value = cells
        elif t == "steps":
            value = {s.strip(): bool(post.get(f"{key}-s{i}"))
                     for i, s in enumerate(f["steps"])}
        elif t == "imagemap":
            # #113: one PID per filled slot; the #112 type guard applies to
            # every slot. Empty maps are omitted like any blank field.
            tid = f.get("type_id")
            vals = {}
            for i, s in enumerate(f["slots"]):
                raw = (post.get(f"{key}-m{i}") or "").strip()
                if not raw or (tid and not raw.upper().startswith(tid + "-")):
                    continue
                vals[s["label"]] = raw
            if not vals:
                continue
            value = vals
        else:   # text, textarea, datetime, select, qr, link
            raw = (post.get(key) or "").strip()
            if not raw:
                continue
            # #112: a type-guarded qr/link box drops a wrong-type PID —
            # the server backstop behind the scan modal's refusal.
            tid = f.get("type_id")
            if tid and not raw.upper().startswith(tid + "-"):
                continue
            value = raw
        data.setdefault(title, {})[f["label"]] = value
    return data


def _opt(options, value):
    return next((o for o in options if o["value"] == value), None)


def item_card(schema: dict, item: dict | None, opts: dict | None,
              saved: dict | None = None) -> list[dict]:
    """#103: the "Item" card's widgets — one per enabled standard field,
    pre-filled from the item's current HWDB record (or a draft's saved
    values, which win). ``opts``: ``manufacturers`` [{value,label}] from the
    type record, ``institutions`` [{value,label}] for Location."""
    item = item or {}
    opts = opts or {}
    saved = saved or {}
    def cur(name, default=None):
        s = saved.get(ITEM_FIELD_LABELS[name])
        if isinstance(s, dict) and "id" in s:
            return s["id"]
        return s if s is not None else default
    out = []
    for name in schema.get("item_fields") or []:
        w = {"name": name, "key": f"item-{name}", "label": ITEM_FIELD_LABELS[name]}
        if name == "manufacturer":
            m = item.get("manufacturer")
            w.update(kind="select", options=opts.get("manufacturers") or [],
                     value=cur(name, m.get("id") if isinstance(m, dict) else None),
                     hint="from the type definition")
        elif name == "status":
            st = item.get("status")
            w.update(kind="select", options=STATUS_OPTIONS,
                     value=cur(name, st.get("id") if isinstance(st, dict) else None))
        elif name in _ITEM_FLAGS:
            w.update(kind="check", value=bool(cur(name, item.get(name))))
        elif name == "location":
            loc = item.get("location")
            w.update(kind="location", options=opts.get("institutions") or [],
                     value=cur(name, loc.get("id") if isinstance(loc, dict) else None),
                     current=(loc.get("name") if isinstance(loc, dict) else "") or "",
                     hint="posts a location update only when changed")
        elif name == "serial_number":
            w.update(kind="text", value=cur(name, item.get("serial_number") or ""))
        elif name == "item_comments":
            w.update(kind="textarea", value=cur(name, item.get("comments") or ""))
        else:  # test_comments — per submission, never from the item
            w.update(kind="textarea", value=saved.get(ITEM_FIELD_LABELS[name]) or "",
                     hint="goes on the test record")
        out.append(w)
    return out


def item_values(schema: dict, post, item: dict | None, opts: dict | None) -> dict | None:
    """#103: what the Item card asks HWDB to change. None when the card
    wasn't in the POST (older drafts, schemas without item fields).
    Returns ``patch`` (only fields that differ from the item's record —
    empty = skip the PATCH), ``location`` ({id} when changed, else None),
    ``arrived`` (ISO string), ``test_comments`` and ``record`` — the
    label→value dict stored in the test record's DATA["Item"]."""
    if post.get("item-card") != "1":
        return None
    item = item or {}
    opts = opts or {}
    fields = schema.get("item_fields") or []
    patch, record = {}, {}
    def _int(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return None
    if "manufacturer" in fields:
        mid = _int(post.get("item-manufacturer"))
        cur = (item.get("manufacturer") or {}).get("id") if isinstance(item.get("manufacturer"), dict) else None
        if mid is not None:
            if mid != cur:
                patch["manufacturer"] = {"id": mid}
            o = _opt(opts.get("manufacturers") or [], mid)
            record["Manufacturer"] = {"id": mid, "name": o["label"] if o else ""}
    if "status" in fields:
        sid = _int(post.get("item-status"))
        cur = (item.get("status") or {}).get("id") if isinstance(item.get("status"), dict) else None
        if sid is not None:
            if sid != cur:
                patch["status"] = {"id": sid}
            o = _opt(STATUS_OPTIONS, sid)
            record["Component status"] = {"id": sid, "name": o["label"] if o else ""}
    for flag in _ITEM_FLAGS:
        if flag in fields:
            v = post.get(f"item-{flag}") == "on"
            if v != bool(item.get(flag)):
                patch[flag] = v
            record[ITEM_FIELD_LABELS[flag]] = v
    if "serial_number" in fields:
        v = (post.get("item-serial_number") or "").strip()
        if v != (item.get("serial_number") or ""):
            patch["serial_number"] = v
        record["Serial number"] = v
    if "item_comments" in fields:
        v = (post.get("item-item_comments") or "").strip()
        if v != (item.get("comments") or ""):
            patch["comments"] = v
        record["Item comments"] = v
    location = None
    if "location" in fields:
        lid = _int(post.get("item-location"))
        cur = (item.get("location") or {}).get("id") if isinstance(item.get("location"), dict) else None
        if lid is not None:
            o = _opt(opts.get("institutions") or [], lid)
            record["Location"] = {"id": lid, "name": o["label"] if o else ""}
            if lid != cur:
                location = {"id": lid}
    test_comments = (post.get("item-test_comments") or "").strip() if "test_comments" in fields else ""
    if "test_comments" in fields:
        record["Test comments"] = test_comments
    return {"patch": patch, "location": location,
            "arrived": (post.get("item-arrived") or "").strip(),
            "test_comments": test_comments, "record": record}


def test_payload(schema: dict, data: dict, comments: str) -> dict:
    return {"comments": comments, "test_type": schema["test_type_name"],
            "test_data": {"DATA": data}}


def spec_values(schema: dict, data: dict) -> dict:
    """The submitted values whose fields carry ``to_spec`` (#96), nested
    ``{section: {label: value}}`` exactly like the test record's DATA — so
    same-labelled fields in different sections (variant H's and J's
    "Thickness", #98 review) don't overwrite each other. These ALSO fold into
    the item's latest specifications DATA (the test record keeps the full
    set regardless)."""
    out = {}
    for title, f in leaf_fields(schema):
        if not f.get("to_spec"):
            continue
        sec = data.get(title)
        if isinstance(sec, dict) and f["label"] in sec:
            out.setdefault(title, {})[f["label"]] = sec[f["label"]]
    return out


def link_requests(schema: dict, data: dict) -> list[dict]:
    """The submitted ``link`` fields with a PID:
    ``[{label, pid, position}]`` — the view patches each into the item's
    subcomponents ahead of the test record."""
    out = []
    for title, f in leaf_fields(schema):
        if f["type"] != "link":
            continue
        sec = data.get(title)
        pid = sec.get(f["label"]) if isinstance(sec, dict) else None
        if isinstance(pid, str) and pid.strip():
            out.append({"label": f["label"], "pid": pid.strip(),
                        "position": f["position"]})
    return out


def raw_load(api, part_type_id: str, name: str):
    """``(raw cfg dict | None, image_name | None)`` — unnormalized, unknown
    keys preserved, for the editor page (#96)."""
    row = next((r for r in available(api, part_type_id) if r["name"] == name),
               None)
    if row is None:
        return None, None
    try:
        raw = json.loads(api.get_image_response(row["image_id"]).content)
        return (raw if isinstance(raw, dict) else None), row["image_name"]
    except Exception as e:
        logger.warning("raw checklist %s/%s failed: %s", part_type_id, name, e)
        return None, row["image_name"]


def export_csv(schema: dict, part_id: str, test_data: dict | None) -> str:
    """A submission as CSV text (#97 — the iPad's "send via email" payload):
    section, label, value rows in schema order. Photos flatten to their HWDB
    image name/id; dict/list values to JSON."""
    import csv
    import io as _io
    buf = _io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Checklist", schema["name"]])
    w.writerow(["Part ID", part_id])
    w.writerow(["Test type", schema["test_type_name"]])
    w.writerow([])
    w.writerow(["Section", "Field", "Value"])
    for title, label, v in export_rows(schema, test_data):
        w.writerow([title, label, v])
    return buf.getvalue()


def export_rows(schema: dict, test_data: dict | None):
    """Yield ``(section, label, value)`` for every value-bearing leaf in
    schema order — the CSV's and the email's shared row walk. Photos
    flatten to their HWDB image name/id; dict/list values to JSON; missing
    values to ""."""
    data = (test_data or {}).get("DATA")
    data = data if isinstance(data, dict) else {}
    item = data.get("Item")
    for label, v in (item.items() if isinstance(item, dict) else []):   # #103 card first
        if isinstance(v, dict) and "name" in v:
            v = f"{v.get('name', '')} (id={v.get('id', '')})"
        yield "Item", label, _fmt(v)
    for title, f in leaf_fields(schema):
        if f["type"] == "static":
            continue
        sec = data.get(title)
        v = sec.get(f["label"]) if isinstance(sec, dict) else None
        if f["type"] == "photo" and isinstance(v, dict):
            v = f"{v.get('image_name', '')} (image_id={v.get('image_id', '')})"
        elif isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False)
        yield title, f["label"], "" if v is None else _fmt(v)


EMAIL_BODY_MAX = 1800   # mailto: bodies past ~2 kB get truncated by clients


def email_body(schema: dict, part_id: str, test_data: dict | None,
               page_url: str, submitted_on: str = "") -> str:
    """The plain-text twin of the CSV for a ``mailto:`` draft (#99): a link
    back to the checklist, then ``Section / Field: value`` lines for filled
    fields only, cut off with a pointer to the CSV when the body would
    exceed what mail clients accept in a URL."""
    head = [f"Checklist: {schema['name']}", f"Part ID: {part_id}"]
    if submitted_on:
        head.append(f"Submitted: {submitted_on}")
    head += [page_url, ""]
    lines, n, cut = [], sum(len(h) + 1 for h in head), False
    for title, label, v in export_rows(schema, test_data):
        if v == "":
            continue
        line = f"{title} / {label}: {v}"
        if n + len(line) + 1 > EMAIL_BODY_MAX:
            cut = True
            break
        lines.append(line)
        n += len(line) + 1
    if cut:
        lines.append("… (truncated — attach the CSV for the full data)")
    else:
        lines.append("")
        lines.append("(mail can't be attached automatically — download the CSV and attach it if needed)")
    return "\n".join(head + lines)


def merge_data(base: dict | None, over: dict) -> dict:
    """``base`` DATA with ``over`` DATA folded in, section-wise (#97: a
    draft's values win over the last submission's, but untouched sections —
    photo references especially — survive)."""
    out = {k: (dict(v) if isinstance(v, dict) else v)
           for k, v in (base or {}).items()}
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


def builtin_templates() -> list[dict]:
    """``[{key, title, cfg}]`` — the repo's example schemas
    (``docs/checklists/*.example.json``), offered by the editor as starting
    points (#96 — Hajime: "we could even provide a few templates")."""
    from django.conf import settings
    out = []
    root = settings.BASE_DIR / "docs" / "checklists"
    try:
        paths = sorted(root.glob("*.example.json"))
    except OSError:
        return []
    for p in paths:
        try:
            cfg = json.loads(p.read_text())
        except (OSError, ValueError) as e:
            logger.warning("template %s unreadable: %s", p.name, e)
            continue
        if isinstance(cfg, dict):
            key = p.name[:-len(".example.json")]
            out.append({"key": key,
                        "title": str(cfg.get("name") or key), "cfg": cfg})
    return out
