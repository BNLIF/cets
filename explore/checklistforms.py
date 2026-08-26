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
  ``steps``, ``static`` — plus a ``row`` grouping that renders its child
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

logger = logging.getLogger(__name__)

FIELD_TYPES = {"check", "number", "table", "text", "textarea", "datetime",
               "select", "photo", "qr", "steps", "static", "link"}

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


def _norm_field(f: dict) -> dict | None:
    """One field off the schema, or None to drop it (unknown type, blank
    label, or a widget missing what defines it)."""
    t = str(f.get("type") or "").strip().lower()
    label = str(f.get("label") or "").strip()
    if t == "static":
        # image_id = a reference image uploaded onto the TYPE's images (#97
        # review — the iPad scenes' P1–P10 measurement diagrams), served
        # through the bearer image proxy; image = an external URL.
        out = {"type": t, "label": label,
               "image": str(f.get("image") or "").strip(),
               "image_id": str(f.get("image_id") or "").strip(),
               "url": str(f.get("url") or "").strip(),
               "note": str(f.get("note") or "").strip()}
        return out if (out["image"] or out["image_id"] or out["url"]
                       or out["note"]) else None
    if t not in FIELD_TYPES or not label:
        return None
    out = {"type": t, "label": label, "units": str(f.get("units") or "").strip(),
           "to_spec": bool(f.get("to_spec")) and t in SPEC_CAPABLE}
    if t == "link":
        # subcomponent link (#96): the scanned child PID is linked into the
        # named functional position — or the first free one matching the
        # child's type when no position is pinned (the scan page's rule).
        out["position"] = str(f.get("position") or "").strip()
    if t in ("number", "table"):
        # tolerance: explicit min/max, or nominal ± tol
        nominal, tol = _num(f.get("nominal")), _num(f.get("tol"))
        lo, hi = _num(f.get("min")), _num(f.get("max"))
        if nominal is not None and tol is not None:
            # round: 1.6 + 0.1 must be 1.7, not 1.7000000000000002
            lo = round(nominal - tol, 9) if lo is None else lo
            hi = round(nominal + tol, 9) if hi is None else hi
        out["min"], out["max"] = lo, hi
        out["range"] = (f"{lo:g} – {hi:g}" if lo is not None and hi is not None
                        else f"≥ {lo:g}" if lo is not None
                        else f"≤ {hi:g}" if hi is not None else "")
    if t == "table":
        out["columns"] = [str(c).strip() for c in f.get("columns") or []
                          if str(c).strip()]
        if not out["columns"]:
            return None
    if t == "select":
        out["options"] = [str(o).strip() for o in f.get("options") or []
                          if str(o).strip()]
        if not out["options"]:
            return None
    if t == "steps":
        out["steps"] = [str(s).strip() for s in f.get("steps") or []
                        if str(s).strip()]
        if not out["steps"]:
            return None
    return out


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
                    nk = _norm_field(k) if isinstance(k, dict) else None
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


def leaf_fields(schema: dict):
    """Yield ``(section title, field)`` for every leaf (rows flattened)."""
    for sec in schema["sections"]:
        for f in sec["fields"]:
            for leaf in (f["fields"] if f["type"] == "row" else [f]):
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
            for leaf in (f["fields"] if f["type"] == "row" else [f]):
                _bind_leaf(leaf, sdata.get(leaf["label"]))
    return bound


def _bind_leaf(f: dict, v) -> None:
    t = f["type"]
    if t == "check":
        f["value"] = "pass" if v is True else ("fail" if v is False else "")
    elif t == "table":
        cells = v if isinstance(v, dict) else {}
        f["cells"] = [{"column": c, "name": f"{f['key']}-c{i}",
                       "value": _fmt(cells.get(c))}
                      for i, c in enumerate(f["columns"])]
    elif t == "steps":
        done = v if isinstance(v, dict) else {}
        f["items"] = [{"label": s, "name": f"{f['key']}-s{i}",
                       "done": bool(done.get(s))}
                      for i, s in enumerate(f["steps"])]
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
            cells = {}
            for i, c in enumerate(f["columns"]):
                raw = (post.get(f"{key}-c{i}") or "").strip()
                if raw:
                    cells[c] = _num_or_str(raw)
            if not cells:
                continue
            value = cells
        elif t == "steps":
            value = {s: bool(post.get(f"{key}-s{i}"))
                     for i, s in enumerate(f["steps"])}
        else:   # text, textarea, datetime, select, qr
            raw = (post.get(key) or "").strip()
            if not raw:
                continue
            value = raw
        data.setdefault(title, {})[f["label"]] = value
    return data


def test_payload(schema: dict, data: dict, comments: str) -> dict:
    return {"comments": comments, "test_type": schema["test_type_name"],
            "test_data": {"DATA": data}}


def spec_values(schema: dict, data: dict) -> dict:
    """The submitted values whose fields carry ``to_spec`` (#96), flat
    ``{label: value}`` — these ALSO fold into the item's latest
    specifications DATA (the test record keeps the full set regardless)."""
    out = {}
    for title, f in leaf_fields(schema):
        if not f.get("to_spec"):
            continue
        sec = data.get(title)
        if isinstance(sec, dict) and f["label"] in sec:
            out[f["label"]] = sec[f["label"]]
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
    data = (test_data or {}).get("DATA")
    data = data if isinstance(data, dict) else {}
    for title, f in leaf_fields(schema):
        if f["type"] == "static":
            continue
        sec = data.get(title)
        v = sec.get(f["label"]) if isinstance(sec, dict) else None
        if f["type"] == "photo" and isinstance(v, dict):
            v = f"{v.get('image_name', '')} (image_id={v.get('image_id', '')})"
        elif isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False)
        w.writerow([title, f["label"], "" if v is None else v])
    return buf.getvalue()


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
