"""Executive-summary signing engine (issue #64), matching the Python
Dashboard's behavior (mechanics mapped on #53/#54):

- **Config** — newest ``ES_{typeid}_*.json`` on the component TYPE's images:
  consortium name, test description, todos checklist, signees
  ``[{name, rank, roles}]``, reference URLs. No config → DEFAULT mode.
- **State** — HWDB's ``"ES"`` test record is the single source of truth:
  ``test_data.ES`` holds one ``{name, signature, rank, timestamp, comments}``
  entry per signee and ``test_data.todos`` the checklist state. Every
  signature re-fetches the record, merges by name, and re-posts the whole
  list. Nothing is stored locally.
- **Order** — negative-rank signees sign first (any order among them), then
  non-negative ranks descending (rank 0 last); each row additionally
  role-gated against the caller's ``whoami`` roles.
- **PDF** — reportlab platypus (the Dashboard's stack), DETAIL layout incl.
  config plots; filename ``ExecutiveSummary_{pid}_{YYYYmmdd_HHMMSS}.pdf`` —
  the pre-shipping gate's convention.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import re
from datetime import datetime

from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer,
    Table, TableStyle,
)

logger = logging.getLogger(__name__)

# The Dashboard's status vocabulary. Ids 1-3 are the obsolete pre-change set
# (#75): kept in the label map so ESes written before the change still
# display, but no longer offered as options — new assignments are Unknown (0)
# or the 100+ values (Shipping Procedure Appendix B).
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
_OBSOLETE_STATUS_LABELS = {
    1: "(obsolete) Available",
    2: "(obsolete) Temporarily Unavailable",
    3: "(obsolete) Permanently Unavailable",
}
STATUS_LABEL_BY_ID = {**_OBSOLETE_STATUS_LABELS,
                      **{o["value"]: o["label"] for o in STATUS_OPTIONS}}
STATUS_ID_BY_LABEL = {o["label"]: o["value"] for o in STATUS_OPTIONS}

TIMESTAMP_FMT = "%Y-%m-%d %H:%M"      # signature timestamps (Dashboard format)
FILENAME_TS_FMT = "%Y%m%d_%H%M%S"     # PDF filename timestamps


# ---- Config ---------------------------------------------------------------

def _newest_config_row(rows, part_type_id: str) -> dict | None:
    """The newest ``ES_{typeid}_*.json`` row from a type-images listing."""
    prefix = f"ES_{part_type_id}_"
    matches = [r for r in rows if isinstance(r, dict)
               and (r.get("image_name") or "").startswith(prefix)
               and (r.get("image_name") or "").lower().endswith(".json")]
    return max(matches, key=lambda r: r.get("created") or "") if matches else None


# Starting point for a type with no config yet — the Dashboard's schema
# (the same fields ES_Z00100300001_test_v8.json carries), empty.
CONFIG_TEMPLATE = {
    "consortium_name": "",
    "test_description": "",
    "todos": {"title": "QC Checks", "check_list": []},
    "signees": [],
    "references": [],
    "plots": [],
}


def load_raw_config(api, part_type_id: str):
    """``(raw config dict, filename)`` — the newest ES config verbatim
    (unnormalized, unknown fields preserved), for the editor page.
    ``(None, None)`` when the type has none or it can't be read."""
    try:
        rows = api.get_component_type_images(part_type_id).get("data") or []
        newest = _newest_config_row(rows, part_type_id)
        if newest is None:
            return None, None
        raw = json.loads(api.get_image_response(str(newest["image_id"])).content)
        return (raw if isinstance(raw, dict) else None), newest.get("image_name")
    except Exception as e:
        logger.warning("ES raw config load for %s failed: %s", part_type_id, e)
        return None, None


def load_config(api, part_type_id: str):
    """The newest ``ES_{typeid}_*.json`` from the type's images, normalized.
    Returns ``(cfg | None, message)`` — None means DEFAULT mode."""
    try:
        rows = api.get_component_type_images(part_type_id).get("data") or []
        newest = _newest_config_row(rows, part_type_id)
    except Exception as e:
        logger.warning("ES config listing for %s failed: %s", part_type_id, e)
        return None, f"Couldn’t list the type’s attachments ({e})."
    if newest is None:
        return None, f"No ES config on the type (expected ES_{part_type_id}_*.json)."
    try:
        resp = api.get_image_response(str(newest["image_id"]))
        cfg = json.loads(resp.content)
    except Exception as e:
        logger.warning("ES config download for %s failed: %s", part_type_id, e)
        return None, f"Config {newest.get('image_name')} failed to load ({e})."
    return _normalize(cfg), f"Config: {newest.get('image_name')}"


def _normalize(cfg: dict) -> dict:
    """The Dashboard's tolerant reading of the config fields."""
    desc = cfg.get("test_description")
    if isinstance(desc, dict):
        desc = desc.get("default_text") or desc.get("label") or ""
    todos = cfg.get("todos")
    if isinstance(todos, list):  # accept a bare list of checklist strings
        todos = {"title": "QC Checks", "check_list": [str(t) for t in todos]}
    if not isinstance(todos, dict):
        todos = {}
    signees = []
    for s in cfg.get("signees") or []:
        if not isinstance(s, dict) or not s.get("name"):
            continue
        try:
            rank = int(s.get("rank", -1))
        except (TypeError, ValueError):
            rank = -1
        roles = [r for r in (s.get("roles") or []) if isinstance(r, int)]
        signees.append({"name": str(s["name"]), "rank": rank, "roles": roles})
    refs = []
    for r in cfg.get("references") or []:
        if isinstance(r, str):
            refs.append({"url": r, "comments": ""})
        elif isinstance(r, dict) and r.get("url"):
            refs.append({"url": str(r["url"]), "comments": str(r.get("comments") or "")})
    # Plots: every entry becomes a slot the page can fill. image_path entries
    # resolve from a test record (the Dashboard convention); numeric
    # data_paths entries render from the item's latest test record (single
    # item only — no type-wide "sum"); either kind can instead carry a
    # manually-uploaded image (see plot_upload_prefix).
    plots = []
    for i, p in enumerate(cfg.get("plots") or []):
        if not isinstance(p, dict):
            continue
        base = {"index": i,
                "title": str(p.get("title") or "Plot"),
                "test_type_name": str(p.get("test_type_name") or "").strip(),
                "slug": _plot_slug(i, p.get("title")),
                # single_pid addressing — the Dashboard applies it to BOTH
                # plot kinds (numeric data often lives on a child, e.g. a
                # SiPM board inside a box).
                "part_id": str(p.get("part_id") or "").strip(),
                "sub_part_id": (p.get("sub_part_id")
                                if isinstance(p.get("sub_part_id"), dict) else None),
                # Optional per-plot field group (#85, Hajime/Greg — the APA
                # DB's filled fields next to each plot): a field WITH a
                # data_path resolves live from the QC test record; one
                # WITHOUT is typed on the plot page and stored in the ES
                # test record. Labels are explicit, never data-path keys.
                "fields": [{"label": str(f["label"]).strip(),
                            "data_path": str(f.get("data_path") or "").strip()}
                           for f in p.get("fields") or []
                           if isinstance(f, dict) and str(f.get("label") or "").strip()]}
        ip = p.get("image_path")
        if isinstance(ip, dict) and (ip.get("image_name") or "").strip():
            try:
                ho = int(ip.get("history_order") or 0)
            except (TypeError, ValueError):
                ho = 0
            plots.append({**base, "kind": "image",
                          "image_name": (ip.get("image_name") or "").strip(),
                          "history_order": max(ho, 0)})
        else:
            try:
                bins = int(p.get("bins") or 40)
            except (TypeError, ValueError):
                bins = 40
            plots.append({**base, "kind": "numeric", "bins": bins,
                          "data_paths": [str(x) for x in p.get("data_paths") or []]})
    return {
        "consortium_name": cfg.get("consortium_name") or cfg.get("consortium name") or "",
        "test_description": str(desc or ""),
        "todos": {"title": str(todos.get("title") or "QC Checks"),
                  "check_list": [str(t) for t in todos.get("check_list") or []]},
        "signees": signees,
        "references": refs,
        "plots": plots,
    }


# ---- ES record state ------------------------------------------------------

def fetch_es_state(api, part_id: str
                   ) -> tuple[list, dict | None, list, list | None, dict]:
    """Latest ``(ES list, todos payload, comments log, sub-ES selection,
    plot fields)`` off the item's "ES" test record — the Dashboard's source
    of truth for who has signed. ``comments_log`` (#82), ``sub_es`` (#83)
    and ``plot_fields`` (#85, ``{slug: {label: value}}`` typed on the plot
    pages) are absent on records written before those features; sub_es None
    means "never chosen" (callers default to everything)."""
    try:
        data = api.get_tests(part_id, test_type_id="ES").get("data") or []
    except Exception as e:
        logger.warning("ES test fetch for %s failed: %s", part_id, e)
        return [], None, [], None, {}
    td = (data[0].get("test_data") or {}) if data and isinstance(data[0], dict) else {}
    es = td.get("ES")
    todos = td.get("todos")
    log = td.get("comments_log")
    sub_es = td.get("sub_es")
    plot_fields = td.get("plot_fields")
    return ((es if isinstance(es, list) else []),
            (todos if isinstance(todos, dict) else None),
            (log if isinstance(log, list) else []),
            (sub_es if isinstance(sub_es, list) else None),
            (plot_fields if isinstance(plot_fields, dict) else {}))


def merge_es_entry(es_list, name, signature, rank, timestamp, comments) -> list:
    """Upsert-by-name into the consolidated ES list (Dashboard semantics:
    one entry per signee, re-signing replaces in place)."""
    entry = {"name": name, "signature": signature, "rank": int(rank),
             "timestamp": timestamp, "comments": (comments or "").strip()}
    out, replaced = [], False
    for ent in es_list or []:
        if isinstance(ent, dict) and ent.get("name") == name:
            out.append(entry)
            replaced = True
        elif isinstance(ent, dict):
            out.append(ent)
    if not replaced:
        out.append(entry)
    return out


def append_comment_log(log, name, status_label, text, timestamp,
                       signature="") -> list:
    """The append-only signee comments log (#82, Hajime's ES-structure
    request): each entry keeps who wrote, when, and the Component Status
    at that time. Sign-flow entries also carry ``signature`` — ``name`` is
    the config's position name, so the person who actually signed shows
    next to it (Hajime 2026-07-31). Empty text appends nothing; existing
    entries are never edited or removed."""
    out = [e for e in log or [] if isinstance(e, dict)]
    text = (text or "").strip()
    if text:
        entry = {"name": name, "timestamp": timestamp,
                 "status": status_label, "text": text}
        if (signature or "").strip():
            entry["signature"] = signature.strip()
        out.append(entry)
    return out


def es_test_payload(es_list, todos_payload, comments,
                    comments_log=None, sub_es=None, plot_fields=None) -> dict:
    payload = {"comments": comments, "test_type": "ES",
               "test_data": {"ES": es_list}}
    if isinstance(todos_payload, dict):
        payload["test_data"]["todos"] = todos_payload
    if comments_log:
        payload["test_data"]["comments_log"] = comments_log
    if sub_es is not None:
        payload["test_data"]["sub_es"] = sub_es
    if plot_fields:
        payload["test_data"]["plot_fields"] = plot_fields
    return payload


def set_plot_fields(plot_fields, slug: str, values: dict) -> dict:
    """The saved manual field values with one plot's group replaced (#85):
    other slots ride through, non-dict garbage is dropped, blank values are
    not stored (the label just renders empty)."""
    out = {k: v for k, v in (plot_fields or {}).items()
           if isinstance(v, dict) and k != slug}
    kept = {str(k): str(v).strip() for k, v in (values or {}).items()
            if str(v or "").strip()}
    if kept:
        out[slug] = kept
    return out


def todos_payload(cfg, checked: list[int]) -> dict:
    check_list = cfg["todos"]["check_list"]
    return {"title": cfg["todos"]["title"], "check_list": check_list,
            "checked": sorted(i for i in set(checked) if 0 <= i < len(check_list))}


# ---- Config plots -----------------------------------------------------------
# The Dashboard's image plots: each image_path entry points at an image
# already attached to a test record in HWDB. Numeric data_paths plots (Plotly
# histograms, optional type-wide "sum") are NOT rendered: the sum variant
# means a live fetch across every item of the type, which the Explorer's
# keep-the-mirror-light rule forbids. Instead, ANY slot accepts a manually
# uploaded image (rendered elsewhere, e.g. by the Dashboard), posted onto the
# item under a deterministic ESPlot_* name; the newest upload wins the slot.

def _plot_slug(index: int, title) -> str:
    """Filename-safe identity of one config plot slot, e.g. ``p02-Gain-hist``.
    The index keeps same-titled plots apart; a reordered config shifts which
    uploads each slot sees, like every other newest-wins convention here."""
    words = re.sub(r"[^A-Za-z0-9]+", "-", str(title or "plot")).strip("-")[:40]
    return f"p{index:02d}-{words or 'plot'}"


def plot_upload_prefix(part_id: str, plot: dict) -> str:
    """Name prefix for a manually-uploaded plot image on the item — unique per
    config slot, so the newest matching upload is findable later (HWDB is
    append-only; uploads are never replaced, just superseded)."""
    return f"ESPlot_{part_id}_{plot['slug']}_"


def _newest_upload(item_images, prefix: str):
    ups = [r for r in item_images or [] if isinstance(r, dict)
           and (r.get("image_name") or "").startswith(prefix)]
    return max(ups, key=lambda r: (r.get("created") or "",
                                   r.get("image_name") or ""), default=None)


def _find_image_id(test_rec, image_name: str) -> str | None:
    """The image_id for ``image_name`` within one test record — the
    Dashboard's lookup: common list fields first, then a recursive walk."""
    want = (image_name or "").strip()
    if not want or not isinstance(test_rec, dict):
        return None
    for k in ("images", "test_images", "image_list", "images_list", "attachments"):
        v = test_rec.get(k)
        if not isinstance(v, list):
            continue
        for it in v:
            if isinstance(it, dict) and (it.get("image_name") or it.get("name")
                                         or it.get("filename") or "").strip() == want:
                iid = it.get("image_id") or it.get("id")
                if iid:
                    return str(iid)

    def walk(obj):
        if isinstance(obj, dict):
            if ((obj.get("image_name") or "").strip() == want
                    and (obj.get("image_id") or obj.get("id"))):
                return str(obj.get("image_id") or obj.get("id"))
            for v in obj.values():
                if (out := walk(v)):
                    return out
        elif isinstance(obj, list):
            for v in obj:
                if (out := walk(v)):
                    return out
        return None

    return walk(test_rec)


def _test_record_at(api, pid: str, test_type_name: str, history_order: int):
    """``(record, error)`` — the test record at ``history_order`` (0 = latest),
    the Dashboard's addressing into the history list."""
    if not pid or not test_type_name:
        return None, "Missing pid/test_type_name."
    try:
        data = api.get_tests(pid, test_type_id=test_type_name,
                             history=True).get("data") or []
    except Exception as e:
        return None, f"Test fetch failed for {pid} / {test_type_name}: {e}"
    if not data:
        return None, f"No test history found for {pid} / {test_type_name}."
    if history_order >= len(data):
        return None, f"history_order={history_order} out of range (N={len(data)})."
    rec = data[history_order]
    return (rec if isinstance(rec, dict) else None), None


def _resolve_sub_part_id(children_of, part_id: str, layer, pos_name) -> str | None:
    """The Dashboard's subtree addressing: layer 1 = the item's direct
    children, matched by functional position; ties break on lowest PID."""
    try:
        layer = int(layer)
    except (TypeError, ValueError):
        return None
    want = (pos_name or "").strip()
    if layer < 1 or not want:
        return None
    level = [part_id]
    for depth in range(1, layer + 1):
        rows = [m for pid in level for m in children_of(pid)]
        if depth == layer:
            matches = sorted({m["part_id"] for m in rows if m.get("part_id")
                              and (m.get("functional_position") or "").strip() == want})
            return matches[0] if matches else None
        level = [m["part_id"] for m in rows if m.get("part_id")]
        if not level:
            return None
    return None


def _get_by_path(obj, path: str):
    """The Dashboard's data_path addressing into test_data: a plain key
    (``"MRB Resistance"``) wins verbatim, else dotted keys with ``[idx]``
    list indices (``"DATA[0].SiPM[3].V"``). ``None`` on any miss."""
    if not isinstance(obj, dict) or not isinstance(path, str) or not path.strip():
        return None
    if path in obj:
        return obj.get(path)
    cur = obj
    for part in path.split("."):
        m = re.match(r"^([^\[\]]*)((?:\[\d+\])*)$", part)
        if not m:
            return None
        key, idxs = m.group(1), re.findall(r"\[(\d+)\]", m.group(2))
        if key:
            if not isinstance(cur, dict) or key not in cur:
                return None
            cur = cur[key]
        for i in map(int, idxs):
            if not isinstance(cur, list) or i >= len(cur):
                return None
            cur = cur[i]
    return cur


def _flatten_numeric(value) -> list[float]:
    """Nested lists/scalars → flat list[float]; non-numbers (and bools)
    dropped, dicts ignored — the Dashboard's rule."""
    out = []

    def rec(v):
        if isinstance(v, bool) or v is None:
            return
        if isinstance(v, (int, float)):
            out.append(float(v))
            return
        if isinstance(v, str):
            try:
                out.append(float(v.strip()))
            except ValueError:
                pass
            return
        if isinstance(v, (list, tuple)):
            for t in v:
                rec(t)

    rec(value)
    return out


def render_numeric_plot(test_data: dict, plot: dict, label: str):
    """``(png bytes | None, note | None)`` — the Dashboard's single-PID
    numeric plots, drawn with matplotlib instead of Plotly: 1 data_path →
    histogram (numeric when >80% of values parse, else categorical bar);
    2 paths → scatter. Type-wide "sum" populations are NOT rendered (that's
    a fan-out over every item of the type — see the mirror-light rule)."""
    try:
        from matplotlib.figure import Figure
    except ImportError:
        return None, "matplotlib is not installed on the server."
    paths = plot.get("data_paths") or []
    title = f"{plot['title']} — {label}"

    def _png(draw):
        # Figure (not pyplot) — no global state, safe under threaded gunicorn.
        fig = Figure(figsize=(5.2, 3.4), dpi=110)
        ax = fig.add_subplot()
        draw(ax)
        ax.set_title(title, fontsize=10)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        return buf.getvalue()

    if len(paths) == 1:
        v = _get_by_path(test_data, paths[0])
        values = v if isinstance(v, list) else ([] if v is None else [v])
        if not values:
            return None, f"No data at data_path '{paths[0]}'."
        nums = _flatten_numeric(values)
        if len(nums) > 0.8 * len(values):
            stats = (f"N={len(nums)}  mean={sum(nums) / len(nums):.4g}  "
                     f"min={min(nums):.4g}  max={max(nums):.4g}")

            def draw(ax):
                ax.hist(nums, bins=plot.get("bins") or 40)
                ax.set_xlabel(f"{paths[0]}\n{stats}", fontsize=8)
                ax.set_ylabel("count", fontsize=8)
            return _png(draw), None
        cats = {}
        for x in values:
            k = "True" if x is True else ("False" if x is False else str(x))
            cats[k] = cats.get(k, 0) + 1

        def draw(ax):
            ax.bar(list(cats), list(cats.values()))
            ax.set_xlabel(f"{paths[0]}  (N={len(values)}, unique={len(cats)})",
                          fontsize=8)
            ax.set_ylabel("count", fontsize=8)
            ax.tick_params(axis="x", rotation=25, labelsize=7)
        return _png(draw), None

    if len(paths) == 2:
        xs = _flatten_numeric(_get_by_path(test_data, paths[0]))
        ys = _flatten_numeric(_get_by_path(test_data, paths[1]))
        n = min(len(xs), len(ys))
        if not n:
            return None, f"No numeric (x,y) pairs at data_paths {paths}."

        def draw(ax):
            ax.scatter(xs[:n], ys[:n], s=12, alpha=0.7)
            ax.set_xlabel(f"{paths[0]}  (N={n})", fontsize=8)
            ax.set_ylabel(paths[1], fontsize=8)
        return _png(draw), None

    return None, "Invalid config: data_paths must have length 1 (histogram) or 2 (scatter)."


def _fmt_field_value(v):
    """A resolved data_path value as display text; None passes through (the
    caller reports the miss)."""
    if v is None:
        return None
    if isinstance(v, float):
        return f"{v:g}"
    if isinstance(v, (str, int, bool)):
        return str(v)
    return json.dumps(v)   # a list/object at the path — shown verbatim


def resolve_plot_fields(api, plot, pid: str, saved: dict) -> list[dict]:
    """The plot's field group (#85) as display rows ``{label, data_path,
    auto, value, error}``: data_path fields read the resolved pid's LATEST
    test record of the plot's test type (live — never stored, same rule as
    numeric plots); manual fields read the values typed on the plot page
    (``saved``, the ES record's ``plot_fields[slug]``)."""
    rows = []
    rec, err = (None, None)
    if any(f["data_path"] for f in plot["fields"]):
        rec, err = _test_record_at(api, pid, plot["test_type_name"], 0)
    td = (rec or {}).get("test_data") or {}
    for f in plot["fields"]:
        if f["data_path"]:
            value = None if err else _fmt_field_value(_get_by_path(td, f["data_path"]))
            rows.append({**f, "auto": True, "value": value,
                         "error": err or (None if value is not None else
                                          f"No value at data_path '{f['data_path']}'.")})
        else:
            rows.append({**f, "auto": False,
                         "value": str(saved.get(f["label"]) or ""), "error": None})
    return rows


def resolve_plots(api, cfg, part_id: str, children_of, item_images,
                  plot_fields=None) -> list[dict]:
    """Resolve every config plot slot. Image slots resolve to an HWDB
    image_id (the page streams the bytes through the existing image proxy);
    the newest manual ESPlot_* upload on the item wins any slot; image_path
    slots without one fall back to their test record (``children_of(pid)``
    returns manifest rows for sub_part_id addressing); numeric data_paths
    slots render from the resolved pid's latest test record (``png_b64``,
    single-item only — no type-wide "sum" fan-out). An uploaded numeric slot
    still renders (page toggle between the two) but the upload keeps the PDF
    (``bytes`` stays unset so download_plot_images fetches it). Failures land
    in ``error``, shown verbatim. ``plot_fields`` (#85) is the ES record's
    saved manual field values; each block gets its field group resolved
    under the same pid addressing as the plot."""
    blocks = []
    for p in cfg["plots"]:
        blk = {**p, "pid": part_id, "image_id": None, "error": None,
               "uploaded": False, "upload_name": None, "is_pdf": False}
        # single_pid addressing (both kinds, the Dashboard's rule): explicit
        # part_id or sub_part_id in the config, else the item itself. First,
        # so the field group resolves under it even when an upload covers
        # the slot.
        if p["sub_part_id"]:
            resolved = _resolve_sub_part_id(
                children_of, part_id,
                p["sub_part_id"].get("layer"), p["sub_part_id"].get("pos_name"))
            blk["pid"] = resolved or part_id
        elif p["part_id"]:
            blk["pid"] = p["part_id"]
        if p["fields"]:
            blk["fields"] = resolve_plot_fields(
                api, p, blk["pid"], (plot_fields or {}).get(p["slug"]) or {})
        up = _newest_upload(item_images, plot_upload_prefix(part_id, p))
        if up:
            blk.update(image_id=str(up["image_id"]), uploaded=True,
                       upload_name=up.get("image_name"))
            if p["kind"] == "image":
                blocks.append(blk)
                continue
        if p["kind"] == "image":
            blk["is_pdf"] = p["image_name"].lower().endswith(".pdf")
            rec, err = _test_record_at(api, blk["pid"], p["test_type_name"],
                                       p["history_order"])
            if err:
                blk["error"] = err
            else:
                blk["image_id"] = _find_image_id(rec, p["image_name"])
                if not blk["image_id"]:
                    blk["error"] = (
                        f"Could not find image_name='{p['image_name']}' in test record "
                        f"(pid={blk['pid']}, test={p['test_type_name']}, "
                        f"history_order={p['history_order']}).")
        else:  # numeric — draw from the resolved pid's latest test record
            rec, err = _test_record_at(api, blk["pid"], p["test_type_name"], 0)
            png, note = (None, err) if err else render_numeric_plot(
                rec.get("test_data") or {}, p, blk["pid"])
            if png:
                blk["png_b64"] = base64.b64encode(png).decode()
                blk["render_bytes"] = png   # kept for a "plot from data" PDF choice
                if not blk["uploaded"]:
                    blk["bytes"] = png
            elif not blk["uploaded"]:
                # only a real problem when the upload isn't covering the slot
                blk["error"] = note
        blocks.append(blk)
    return blocks


def download_plot_images(api, blocks) -> None:
    """Fill ``bytes`` on resolved blocks for PDF embedding. PDF attachments
    are linked on the page but not rasterized into the summary (that needs
    pymupdf, which we don't carry)."""
    for b in blocks:
        if b.get("bytes"):  # numeric slot, already rendered from test data
            continue
        if not b.get("image_id"):
            if not b.get("error"):
                b["error"] = "No image available for this plot (nothing uploaded)."
            continue
        if b["is_pdf"]:
            b["error"] = (f"PDF attachment {b['image_name']} is not embedded "
                          "in the summary (view it on the ES page).")
            continue
        try:
            b["bytes"] = api.get_image_response(str(b["image_id"])).content
        except Exception as e:
            b["error"] = f"Failed to download image (image_id={b['image_id']}): {e}"


# ---- Signing order / gating -----------------------------------------------

def _sort_key(signee):
    """Display + PDF row order: negative ranks first (stable by name), then
    rank descending — the actual signing order."""
    rank = signee["rank"]
    return (0, signee["name"]) if rank < 0 else (1, -rank, signee["name"])


def compute_status(cfg, es_list, user_role_ids, role_names=None) -> dict:
    """Per-signee signing state, the Dashboard's rules: all negative-rank
    signees before any non-negative; non-negatives highest-rank-first; each
    row role-gated against the caller's roles."""
    signed = {e.get("name"): e for e in es_list or []
              if isinstance(e, dict) and (e.get("signature") or "").strip()}
    signees = sorted(cfg["signees"], key=_sort_key)
    neg_unsigned = any(s["rank"] < 0 and s["name"] not in signed for s in signees)
    nonneg_unsigned = [s["rank"] for s in signees
                       if s["rank"] >= 0 and s["name"] not in signed]
    next_rank = max(nonneg_unsigned) if nonneg_unsigned else None
    rows = []
    for s in signees:
        already = s["name"] in signed
        if s["rank"] < 0:
            allowed = not already
        else:
            allowed = (not already) and (not neg_unsigned) and s["rank"] == next_rank
        role_ok = not s["roles"] or bool(set(s["roles"]) & set(user_role_ids))
        rows.append({
            **s, "entry": signed.get(s["name"]),
            "allowed": allowed and role_ok,
            "role_ok": role_ok,
            "role_names": [str((role_names or {}).get(r, r)) for r in s["roles"]],
        })
    all_signed = bool(signees) and all(s["name"] in signed for s in signees)
    # RESET is allowed only for holders of the lowest non-negative-rank
    # signee's roles (the final approver), per the Dashboard.
    nonneg = [s for s in signees if s["rank"] >= 0]
    reset_roles = min(nonneg, key=lambda s: s["rank"])["roles"] if nonneg else []
    reset_allowed = not reset_roles or bool(set(reset_roles) & set(user_role_ids))
    return {"rows": rows, "all_signed": all_signed, "reset_allowed": reset_allowed}


# ---- PDF ------------------------------------------------------------------

# ---- The "datasheet" PDF layout (2026-07-31): hairline section rules and
# aligned columns instead of boxed fields — least ink, most rows per page.
# One header (no title + "Selected Item Numbers" duplication), the three
# status fields as one row, the comments log and sub-components on their
# own pages, plots kept. ----

_INK = colors.HexColor("#16202a")
_HAIRLINE = colors.HexColor("#c8d0d6")
_GREY = "#6a767f"


def _ds(name: str, **kw) -> ParagraphStyle:
    return ParagraphStyle(name, parent=getSampleStyleSheet()["Normal"], **kw)


# Flush-left tables draw the section rules edge to edge; the last column
# keeps no right padding so right-aligned text meets the rule's end.
def _flush(extra=()):
    return [("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (-1, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2), *extra]


def _qr_drawing(url: str, size: float = 76):
    """A QR code pointing at ``url`` (reportlab's built-in widget), scaled
    to ``size`` points square."""
    from reportlab.graphics.barcode.qr import QrCodeWidget
    from reportlab.graphics.shapes import Drawing
    widget = QrCodeWidget(url)
    x1, y1, x2, y2 = widget.getBounds()
    d = Drawing(size, size, transform=[size / (x2 - x1), 0, 0,
                                       size / (y2 - y1), 0, 0])
    d.add(widget)
    return d


def _summary_header(part_id: str, facts: list[tuple[str, str]],
                    qr_url: str = "", kind: str = "") -> Table:
    """The header block above the heavy rule: title + facts grid on the
    left, a QR code to the live part page on the right. ``facts`` values
    may carry Paragraph markup (pre-escaped by the caller)."""
    title = Paragraph(f'<font size="13.5"><b>Executive Summary{escape(kind)}: '
                      f'<font face="Courier-Bold">{escape(part_id)}</font></b>'
                      f'</font>', _ds("hd-t", leading=17, spaceAfter=7))
    key = _ds("hd-k", fontSize=8.5, leading=11.5)
    val = _ds("hd-v", fontSize=8.5, leading=11.5)
    rows = [[Paragraph(f"<b>{escape(k)}</b>", key), Paragraph(v, val)]
            for k, v in facts]
    facts_t = Table(rows, colWidths=[88, 282])
    facts_t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                 ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                 ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                                 ("TOPPADDING", (0, 0), (-1, -1), 0.5),
                                 ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]))
    right = _qr_drawing(qr_url) if qr_url else ""
    outer = Table([[[title, facts_t], right]], colWidths=[382, 86])
    outer.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 1.8, _INK),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("ALIGN", (-1, 0), (-1, -1), "RIGHT"),
                               *_flush([("BOTTOMPADDING", (0, 0), (-1, -1), 8)])]))
    return outer


def _section(title: str, note: str = "") -> list:
    left = Paragraph(f'<font size="8"><b>{escape(title.upper())}</b></font>',
                     _ds("sec-l"))
    right = Paragraph(f'<para align="right"><font size="7.5" color="{_GREY}">'
                      f'{escape(note)}</font></para>', _ds("sec-r"))
    t = Table([[left, right]], colWidths=[240, 228])
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.9, _INK),
                           ("VALIGN", (0, 0), (-1, -1), "BOTTOM"), *_flush()]))
    return [Spacer(1, 13), t, Spacer(1, 4)]


def _yesno(flag, style) -> Paragraph:
    if flag is None:
        return Paragraph("—", style)
    color, text = ("#19b478", "Yes") if flag else ("#dc3c3c", "No")
    return Paragraph(f'<font color="{color}"><b>{text}</b></font>', style)


def _gate_grid(status_label, certified, uploaded) -> Table:
    key = _ds("g-k", fontSize=6.8, leading=9, textColor=colors.HexColor(_GREY))
    val = _ds("g-v", fontSize=9, leading=11.5)
    cells = [[Paragraph("COMPONENT STATUS", key),
              Paragraph("CERTIFIED QA/QC", key),
              Paragraph("ALL QA/QC UPLOADED", key)],
             [Paragraph(f"<b>{escape(status_label or 'Unknown')}</b>", val),
              _yesno(bool(certified), val), _yesno(bool(uploaded), val)]]
    t = Table(cells, colWidths=[180, 120, 168])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), *_flush()]))
    return t


def _checks_grid(items, checked) -> Table:
    cell = _ds("ck", fontSize=8.5, leading=11.5)
    cols, rows = 2, []
    for i in range(0, len(items), cols):
        row = []
        for j, item in enumerate(items[i:i + cols]):
            mark = ('<font face="ZapfDingbats" color="#19b478" size="7">4</font>'
                    if i + j in checked else f'<font color="{_GREY}">—</font>')
            row.append(Paragraph(f"{mark} {escape(item)}", cell))
        row += [""] * (cols - len(row))
        rows.append(row)
    t = Table(rows, colWidths=[234, 234])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), *_flush()]))
    return t


def _col_head(text: str) -> Paragraph:
    return Paragraph(f'<font size="7" color="{_GREY}">{escape(text)}</font>',
                     _ds("col-h", leading=9))


def _signoff_table(rows) -> Table:
    """Sign-offs: Position / Signature / Date / Comment (latest), one row
    per configured signee in signing order."""
    cell = _ds("so-c", fontSize=8.5, leading=11)
    body = [[_col_head("POSITION"), _col_head("SIGNATURE"),
             _col_head("DATE"), _col_head("COMMENT (LATEST)")]]
    for r in rows:
        e = r["entry"] or {}
        body.append([Paragraph(escape(r["name"]), cell),
                     Paragraph(escape(e.get("signature") or "—"), cell),
                     Paragraph(escape(e.get("timestamp") or "—"), cell),
                     Paragraph(escape(e.get("comments") or "—"), cell)])
    t = Table(body, colWidths=[100, 100, 90, 178], repeatRows=1)
    t.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, 0), 0.9, _INK),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, _HAIRLINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), *_flush()]))
    return t


def _log_flowables(log: list[dict]) -> list:
    """The append-only comments log, NEWEST FIRST, as a Time / Who /
    QA-QC Status / Comment table — the comment column is the widest so long
    notes wrap there; reset markers span the width as centered grey rows."""
    ts = _ds("lg-t", fontName="Courier", fontSize=7.5, leading=10.5)
    who = _ds("lg-w", fontSize=8.5, leading=11)
    st = _ds("lg-s", fontSize=8, leading=10.5, textColor=colors.HexColor("#8a949c"))
    txt = _ds("lg-x", fontSize=8.5, leading=11)
    body = [[_col_head("TIME"), _col_head("WHO"),
             _col_head("QA/QC STATUS"), _col_head("COMMENT")]]
    resets = []
    for e in reversed(log):
        if e.get("event") == "reset":
            resets.append(len(body))
            body.append([Paragraph(
                f'<para align="center"><font color="#8a949c"><i>— signatures reset'
                f' · {escape(e.get("timestamp") or "")}'
                f'{" · " + escape(e["name"]) if e.get("name") else ""} —</i></font>'
                f'</para>', txt), "", "", ""])
            continue
        # sign-flow entries: name is the POSITION — the typed signature
        # identifies the person, so the PERSON gets the bold, not the title
        if e.get("signature"):
            who_txt = f'<b>{escape(e["signature"])}</b> · {escape(e.get("name") or "")}'
        else:
            who_txt = f'<b>{escape(e.get("name") or "")}</b>'
        body.append([Paragraph(escape(e.get("timestamp") or ""), ts),
                     Paragraph(who_txt, who),
                     Paragraph(escape(e.get("status") or "—"), st),
                     Paragraph(escape(e.get("text") or ""), txt)])
    t = Table(body, colWidths=[76, 126, 76, 190], repeatRows=1)
    style = [("LINEBELOW", (0, 0), (-1, 0), 0.9, _INK),
             ("LINEBELOW", (0, 1), (-1, -1), 0.4, _HAIRLINE),
             ("VALIGN", (0, 0), (-1, -1), "TOP"), *_flush()]
    for i in resets:
        style.append(("SPAN", (0, i), (-1, i)))
    t.setStyle(TableStyle(style))
    return [t]


def _reference_flowables(refs: list[dict]) -> list:
    """Clickable references: the comment is the link text (URL when there is
    none), with the raw URL trailing in grey so print readers keep it."""
    small = _ds("ref", fontSize=8.5, leading=12.5)
    out = []
    for r in refs:
        href = escape(r["url"], {'"': "&quot;"})
        label = escape(r.get("comments") or r["url"])
        tail = (f' <font size="7" color="{_GREY}">— {escape(r["url"])}</font>'
                if r.get("comments") else "")
        out.append(Paragraph(
            f'• <link href="{href}" color="blue"><u>{label}</u></link>{tail}', small))
    return out


def append_pdf(base: bytes, extra: bytes) -> bytes:
    """The generated summary with the supplemental-material PDF appended.
    Raises ``ValueError`` on an unreadable supplemental file (the summary is
    never posted half-merged)."""
    from pypdf import PdfReader, PdfWriter
    writer = PdfWriter()
    writer.append(io.BytesIO(base))
    try:
        writer.append(PdfReader(io.BytesIO(extra)))
    except Exception as e:
        raise ValueError(f"unreadable supplemental PDF ({e})") from e
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def build_detail_pdf(part_id: str, form: dict) -> bytes:
    """The DETAIL summary in the datasheet layout: page one carries the
    header block (title + facts grid + QR code to the live part page),
    the status/QA-QC section (flags + QC checklist as one gate), the
    sign-off table, the sub-components table with per-child "Exe.Sum."
    links to each generated summary PDF, and clickable references; the
    full append-only comments log gets its own page (newest first — it
    outgrows the sign-off table's latest-comment column); then the config
    plots."""
    buf = io.BytesIO()
    facts = []
    if form.get("type_name"):
        value = escape(form["type_name"])
        if form.get("type_path"):
            value += (f' <font color="{_GREY}">in {escape(form["type_path"])}'
                      f'</font>')
        if form.get("instance"):
            value += f' &nbsp;·&nbsp; HWDB: <b>{escape(form["instance"])}</b>'
        facts.append(("Component type", value))
    elif form.get("instance"):
        facts.append(("HWDB", f'<b>{escape(form["instance"])}</b>'))
    if form.get("consortium"):
        facts.append(("Consortium", escape(form["consortium"])))
    facts.append(("Generated", f"{datetime.now():{TIMESTAMP_FMT}}"))
    if form.get("description"):
        facts.append(("Description", escape(form["description"])))
    story = [_summary_header(part_id, facts, qr_url=form.get("part_url") or "")]

    # Status, flags and the QC checklist share one section — they are all
    # the same gate.
    todos = form.get("todos") or {}
    n = len(todos.get("check_list") or [])
    checked = {i for i in (todos.get("checked") or [])
               if isinstance(i, int) and 0 <= i < n}
    note = (f"{todos.get('title') or 'QC Checks'}: {len(checked)} of {n} confirmed"
            if n else "")
    story += _section("Status & QA/QC", note)
    story.append(_gate_grid(form.get("status_label"), form.get("certified_flag"),
                            form.get("uploaded_flag")))
    if n:
        story += [Spacer(1, 7), _checks_grid(todos["check_list"], checked)]

    rows = form.get("signee_rows") or []
    signed = sum(1 for r in rows if r.get("entry"))
    story += _section("Sign-offs", f"{signed} of {len(rows)} signed")
    story.append(_signoff_table(rows))

    subtree = form.get("subtree") or ([], False)
    n_sub = len(subtree[0])
    story += _section("Sub-components",
                      f"{n_sub} direct sub-component{'s' if n_sub != 1 else ''}")
    story += subtree_flowables(*subtree)

    refs = form.get("references") or []
    if refs:
        story += _section("References")
        story += _reference_flowables(refs)

    # The full append-only comments log (Hajime 2026-07-30) on its own page —
    # the sign-off table only carries each signee's LATEST comment.
    log = [e for e in form.get("comments_log") or [] if isinstance(e, dict)]
    if log:
        story.append(PageBreak())
        story += _section("Comments log", "newest first · append-only; survives resets")
        story += _log_flowables(log)

    plot_blocks = form.get("plot_blocks") or []
    if plot_blocks:
        story.append(PageBreak())
        story += _section("Plots")
        title = _ds("pl-t", fontSize=9.5, leading=12)
        src_style = _ds("pl-s", fontSize=7.5, leading=10,
                        textColor=colors.HexColor(_GREY))
        for pb in plot_blocks:
            if pb.get("uploaded"):
                src = f"Uploaded image: {pb['upload_name']}"
            elif pb.get("kind") == "numeric":
                src = f"Numeric plot (data_paths: {', '.join(pb.get('data_paths') or [])})"
            else:
                src = (f"Image: {pb['image_name']} "
                       f"(history_order={pb['history_order']}) · {pb['pid']}")
            story += [
                Spacer(1, 10),
                Paragraph(f"<b>{escape(pb['title'])}</b> — "
                          f"{escape(pb['test_type_name'])}", title),
                Paragraph(escape(src), src_style),
            ]
            # The plot's field group (#85) as a compact label/value grid —
            # auto values were resolved from the latest QC record when this
            # PDF was generated; manual ones come from the ES record.
            flds = [f for f in pb.get("fields") or []
                    if isinstance(f, dict) and "value" in f]
            if flds:
                f_lab = _ds("pf-l", fontSize=7.5, leading=10,
                            textColor=colors.HexColor(_GREY))
                f_val = _ds("pf-v", fontSize=8.5, leading=11)
                ft = Table(
                    [[Paragraph(escape(f["label"]), f_lab),
                      Paragraph(escape(f.get("value") or "")
                                or f'<font color="{_GREY}">—</font>', f_val)]
                     for f in flds],
                    colWidths=[160, 308])
                ft.setStyle(TableStyle([
                    ("LINEBELOW", (0, 0), (-1, -1), 0.4, _HAIRLINE),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"), *_flush()]))
                story += [Spacer(1, 4), ft]
            if pb.get("bytes"):
                try:
                    img = Image(io.BytesIO(pb["bytes"]))
                    iw, ih = img.imageWidth, img.imageHeight
                    # fit the letter body (~468x648pt) with room for captions
                    scale = min(460 / iw, 400 / ih, 1.0) if iw and ih else 1.0
                    img.drawWidth, img.drawHeight = iw * scale, ih * scale
                    story += [Spacer(1, 6), img]
                except Exception as e:
                    story.append(Paragraph(f"(image could not be embedded: {e})",
                                           src_style))
            elif pb.get("error"):
                story.append(Paragraph(f"⚠ {escape(pb['error'])}", src_style))

    SimpleDocTemplate(buf, pagesize=letter,
                      title=f"Executive Summary: {part_id}").build(story)
    return buf.getvalue()


def build_default_pdf(part_id: str, signinfo: dict,
                      subtree: tuple[list[dict], bool]) -> bytes:
    """The configless DEFAULT summary in the same datasheet layout: header
    block, the status/QA-QC row, the single whoami sign-off row, and the
    sub-components table — no checklist, no references."""
    buf = io.BytesIO()
    facts = []
    if signinfo.get("instance"):
        facts.append(("HWDB", f'<b>{escape(signinfo["instance"])}</b>'))
    facts.append(("Generated", f"{datetime.now():{TIMESTAMP_FMT}}"))
    story = [_summary_header(part_id, facts, kind=" (default)",
                             qr_url=signinfo.get("part_url") or "")]
    story += _section("Status & QA/QC")
    story.append(_gate_grid(signinfo.get("status_label"),
                            signinfo.get("certified_flag"),
                            signinfo.get("uploaded_flag")))
    story += _section("Sign-off")
    cell = _ds("dso-c", fontSize=8.5, leading=11)
    table = Table(
        [[_col_head("SIGNATURE"), _col_head("DATE"), _col_head("COMMENT")],
         [Paragraph(escape(signinfo.get("signature") or "—"), cell),
          Paragraph(escape(signinfo.get("timestamp") or "—"), cell),
          Paragraph(escape(signinfo.get("comments") or "—"), cell)]],
        colWidths=[130, 100, 238])
    table.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, 0), 0.9, _INK),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, _HAIRLINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), *_flush()]))
    story.append(table)
    n_sub = len(subtree[0])
    story += _section("Sub-components",
                      f"{n_sub} direct sub-component{'s' if n_sub != 1 else ''}")
    story += subtree_flowables(*subtree)
    SimpleDocTemplate(buf, pagesize=letter,
                      title=f"Executive Summary (default): {part_id}").build(story)
    return buf.getvalue()


def subtree_flowables(rows: list[dict], truncated: bool) -> list:
    """The Sub-components page: the direct sub-components (one level only —
    Hajime 2026-07-30), one row each with the three QC statuses and, for
    children that already have a generated executive summary, an "Exe.Sum."
    link straight to that PDF (``es_url``, added by the view; the column
    stays empty otherwise). ``rows`` come from ``parts.subtree_rows``."""
    styles = getSampleStyleSheet()
    if not rows:
        return [Paragraph("No sub-components.", styles["Normal"])]
    cell = _ds("subtree-cell", fontSize=8, leading=10.5)

    body = [[_col_head("Part"), _col_head("Type"), _col_head("Position"),
             _col_head("Status"), _col_head("QC-UPL."), _col_head("QC-CERT."),
             _col_head("Exe.Sum.")]]
    for r in rows:
        conn = f".{r['connection']}" if r.get("connection") else ""  # cable end (#72)
        part = (f'<font face="Courier" size="7.5">{escape(r["part_id"] + conn)}'
                f'</font>')
        body.append([
            Paragraph("&nbsp;" * 4 * r["depth"] + part, cell),
            Paragraph(escape(r.get("type_name") or "—"), cell),
            Paragraph(escape(r.get("functional_position") or "—"), cell),
            Paragraph(escape(r.get("status") or "—"), cell),
            _yesno(r.get("uploaded"), cell), _yesno(r.get("certified"), cell),
            (Paragraph(f'<link href="{escape(r["es_url"], {chr(34): "&quot;"})}"'
                       f' color="blue"><u>open</u></link>', cell)
             if r.get("es_url") else ""),
        ])
    table = Table(body, colWidths=[116, 82, 70, 72, 40, 44, 44], repeatRows=1)
    table.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, 0), 0.9, _INK),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, _HAIRLINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), *_flush()]))
    out = [table]
    if truncated:
        out.append(Spacer(1, 6))
        out.append(Paragraph(
            "⚠ List truncated — too many sub-components to list them all.",
            styles["Normal"]))
    return out
