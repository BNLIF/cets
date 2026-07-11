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
- **PDF** — reportlab platypus (the Dashboard's stack), DETAIL layout minus
  config plots (unsupported here yet); filename
  ``ExecutiveSummary_{pid}_{YYYYmmdd_HHMMSS}.pdf`` — the pre-shipping gate's
  convention.
"""

from __future__ import annotations

import io
import json
import logging
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import (
    PageBreak, Paragraph, Preformatted, SimpleDocTemplate, Spacer, Table,
    TableStyle,
)

logger = logging.getLogger(__name__)

# The Dashboard's status vocabulary, verbatim.
STATUS_OPTIONS = [
    {"value": 0, "label": "Unknown"},
    {"value": 1, "label": "(obsolete) Available"},
    {"value": 2, "label": "(obsolete) Temporarily Unavailable"},
    {"value": 3, "label": "(obsolete) Permanently Unavailable"},
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
STATUS_LABEL_BY_ID = {o["value"]: o["label"] for o in STATUS_OPTIONS}
STATUS_ID_BY_LABEL = {o["label"]: o["value"] for o in STATUS_OPTIONS}

TIMESTAMP_FMT = "%Y-%m-%d %H:%M"      # signature timestamps (Dashboard format)
FILENAME_TS_FMT = "%Y%m%d_%H%M%S"     # PDF filename timestamps


# ---- Config ---------------------------------------------------------------

def load_config(api, part_type_id: str):
    """The newest ``ES_{typeid}_*.json`` from the type's images, normalized.
    Returns ``(cfg | None, message)`` — None means DEFAULT mode."""
    prefix = f"ES_{part_type_id}_"
    try:
        rows = api.get_component_type_images(part_type_id).get("data") or []
    except Exception as e:
        logger.warning("ES config listing for %s failed: %s", part_type_id, e)
        return None, f"Couldn’t list the type’s attachments ({e})."
    matches = [r for r in rows if isinstance(r, dict)
               and (r.get("image_name") or "").startswith(prefix)
               and (r.get("image_name") or "").lower().endswith(".json")]
    if not matches:
        return None, f"No ES config on the type (expected {prefix}*.json)."
    newest = max(matches, key=lambda r: r.get("created") or "")
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
    return {
        "consortium_name": cfg.get("consortium_name") or cfg.get("consortium name") or "",
        "test_description": str(desc or ""),
        "todos": {"title": str(todos.get("title") or "QC Checks"),
                  "check_list": [str(t) for t in todos.get("check_list") or []]},
        "signees": signees,
        "references": refs,
        "has_plots": bool(cfg.get("plots")),
    }


# ---- ES record state ------------------------------------------------------

def fetch_es_state(api, part_id: str) -> tuple[list, dict | None]:
    """Latest ``(ES list, todos payload)`` off the item's "ES" test record —
    the Dashboard's source of truth for who has signed."""
    try:
        data = api.get_tests(part_id, test_type_id="ES").get("data") or []
    except Exception as e:
        logger.warning("ES test fetch for %s failed: %s", part_id, e)
        return [], None
    td = (data[0].get("test_data") or {}) if data and isinstance(data[0], dict) else {}
    es = td.get("ES")
    todos = td.get("todos")
    return (es if isinstance(es, list) else []), (todos if isinstance(todos, dict) else None)


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


def es_test_payload(es_list, todos_payload, comments) -> dict:
    payload = {"comments": comments, "test_type": "ES",
               "test_data": {"ES": es_list}}
    if isinstance(todos_payload, dict):
        payload["test_data"]["todos"] = todos_payload
    return payload


def todos_payload(cfg, checked: list[int]) -> dict:
    check_list = cfg["todos"]["check_list"]
    return {"title": cfg["todos"]["title"], "check_list": check_list,
            "checked": sorted(i for i in set(checked) if 0 <= i < len(check_list))}


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

def _pf(flag: bool) -> Paragraph:
    color, text = ("#19b478", "PASS") if flag else ("#dc3c3c", "FAIL")
    return Paragraph(f'<font color="{color}"><b>{text}</b></font>',
                     getSampleStyleSheet()["Normal"])


def _signoff_table(rows) -> Table:
    """The DETAIL sign-off table: Position / Signature / Comments / Date,
    one row per configured signee in signing order."""
    styles = getSampleStyleSheet()
    body = [["Position", "Signature", "Comments", "Sign-off date/time"]]
    for r in rows:
        e = r["entry"] or {}
        body.append([
            Paragraph(r["name"], styles["Normal"]),
            Paragraph(e.get("signature") or "—", styles["Normal"]),
            Paragraph(e.get("comments") or "—", styles["Normal"]),
            Paragraph(e.get("timestamp") or "—", styles["Normal"]),
        ])
    table = Table(body, colWidths=[110, 140, 190, 110])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8e8e8")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]))
    return table


def build_detail_pdf(part_id: str, form: dict) -> bytes:
    """The Dashboard's DETAIL summary, minus plots: title, type name,
    generated timestamp, description, todos checklist, sign-off table, the
    three status fields, references page, sub-components page."""
    buf = io.BytesIO()
    styles = getSampleStyleSheet()
    story = [
        Paragraph(f"Executive Summary — {part_id}", styles["Title"]),
        Paragraph("Selected Item Numbers", styles["Heading3"]),
        Paragraph(part_id, styles["Normal"]),
    ]
    if form.get("type_name"):
        story.append(Paragraph(f'<para align="center">{form["type_name"]}</para>',
                               styles["Heading2"]))
    story.append(Paragraph(
        f'<para align="center">Generated: {datetime.now():{TIMESTAMP_FMT}}</para>',
        styles["Normal"]))
    if form.get("description"):
        story += [Paragraph("Test Description", styles["Heading3"]),
                  Paragraph(form["description"], styles["Normal"])]
    todos = form.get("todos") or {}
    if todos.get("check_list"):
        story.append(Paragraph(todos.get("title") or "QC Checks", styles["Heading3"]))
        checked = set(todos.get("checked") or [])
        for i, item in enumerate(todos["check_list"]):
            mark = "[x]" if i in checked else "[ ]"
            story.append(Paragraph(f"{mark} {item}", styles["Normal"]))
    story += [Spacer(1, 10), Paragraph("Sign-off", styles["Heading3"]),
              _signoff_table(form["signee_rows"]), Spacer(1, 12)]
    story += [
        Paragraph("Component Status", styles["Heading3"]),
        Paragraph(form.get("status_label") or "Unknown", styles["Normal"]),
        Paragraph("Consortium Certified QA/QC", styles["Heading3"]),
        _pf(bool(form.get("certified_flag"))),
        Paragraph("All QA/QC Uploaded", styles["Heading3"]),
        _pf(bool(form.get("uploaded_flag"))),
    ]
    refs = form.get("references") or []
    if refs:
        story.append(PageBreak())
        story.append(Paragraph("Reference URLs", styles["Heading2"]))
        for r in refs:
            story.append(Paragraph(
                f'• <link href="{r["url"]}" color="blue">{r["url"]}</link>',
                styles["Normal"]))
            if r.get("comments"):
                story.append(Paragraph(
                    f'<font color="#777777">{r["comments"]}</font>', styles["Normal"]))
    if form.get("subcomponents"):
        story.append(PageBreak())
        story.append(Paragraph("Sub-components", styles["Heading2"]))
        story.append(Preformatted("\n".join(form["subcomponents"]), styles["Code"]))
    SimpleDocTemplate(buf, pagesize=letter).build(story)
    return buf.getvalue()


def build_default_pdf(part_id: str, signinfo: dict, subcomponents: list[str]) -> bytes:
    """The Dashboard's DEFAULT summary: the three status fields and a single
    sign-off row — no config, no checklist, no references."""
    buf = io.BytesIO()
    styles = getSampleStyleSheet()
    story = [
        Paragraph(f"Executive Summary — {part_id}", styles["Title"]),
        Paragraph("Selected Item Numbers", styles["Heading3"]),
        Paragraph(part_id, styles["Normal"]),
        Paragraph("Component Status", styles["Heading3"]),
        Paragraph(signinfo.get("status_label") or "Unknown", styles["Normal"]),
        Paragraph("Consortium Certified QA/QC", styles["Heading3"]),
        _pf(bool(signinfo.get("certified_flag"))),
        Paragraph("All QA/QC Uploaded", styles["Heading3"]),
        _pf(bool(signinfo.get("uploaded_flag"))),
        Spacer(1, 10), Paragraph("Sign-off", styles["Heading3"]),
    ]
    table = Table(
        [["Signature", "Comments", "Sign-off date/time"],
         [signinfo.get("signature") or "—", signinfo.get("comments") or "—",
          signinfo.get("timestamp") or "—"]],
        colWidths=[140, 280, 120])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8e8e8")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]))
    story.append(table)
    if subcomponents:
        story.append(PageBreak())
        story.append(Paragraph("Sub-components", styles["Heading2"]))
        story.append(Preformatted("\n".join(subcomponents), styles["Code"]))
    SimpleDocTemplate(buf, pagesize=letter).build(story)
    return buf.getvalue()


def subcomponent_lines(manifest) -> list[str]:
    """One-level ASCII contents tree for the PDF's last page (the Dashboard
    renders the full recursive subtree; one level is enough for a box)."""
    return [f"{m['part_id'] or '—'}  ({m.get('type_name') or '?'})  @ {m.get('functional_position') or '—'}"
            for m in manifest]
