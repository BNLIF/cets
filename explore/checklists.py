"""Pre-shipping checklist engine (issue #65), matching the Python Dashboard.

Scenes, field names, validation rules, the logistics CSV/email, and above
all the final HWDB patch are taken verbatim from the Dashboard's
``shippingworkflow`` module (mapped on #54): the spec keys — typos included
("acknoledgement") — must match byte-for-byte so both tools interoperate on
the same boxes. State lives in ``BoxChecklist.state`` under the Dashboard's
page keys (``PreShipping1``…``PreShipping7``).
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime

import PIL.Image
from reportlab.graphics.barcode import code128
from reportlab.lib import units
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as rl_canvas

logger = logging.getLogger(__name__)

# (scene number, state key, title) — the Dashboard's pre-shipping sequence.
PRESHIPPING_SCENES = [
    (1, "PreShipping1", "Gate check"),
    (2, "PreShipping2", "QA representative"),
    (3, "PreShipping3", "Point of contact"),
    (4, "PreShipping4a", "Shipment details"),
    (5, "PreShipping4b", "Transportation"),
    (6, "PreShipping5", "Logistics email"),
    (7, "PreShipping6", "Acknowledgement & inspection"),
    (8, "PreShipping7", "Update HWDB"),
]
N_SCENES = len(PRESHIPPING_SCENES)


def scene_key(scene: int) -> str:
    return PRESHIPPING_SCENES[scene - 1][1]


def scene_title(scene: int) -> str:
    return PRESHIPPING_SCENES[scene - 1][2]


# ---- Per-scene validation (the Dashboard's routes.py rules) ---------------

def clean_scene(scene: int, is_surf: bool, post) -> tuple[dict, str | None]:
    """Extract + validate one scene's fields from a POST. Returns
    ``(cleaned_state, error)`` — error None means the scene may advance."""
    g = lambda k: (post.get(k) or "").strip()

    if scene == 1:
        if not post.get("confirm_list"):
            return {}, "Confirm the gate checklist to continue."
        return {"confirm_list": True}, None

    if scene == 2:
        d = {k: g(k) for k in ("qa_rep_name", "qa_rep_email", "test_info")}
        if not all(d.values()):
            return d, "QA rep name, email and test info are all required."
        return d, None

    if scene == 3:
        d = {k: g(k) for k in ("approver_name", "approver_email")}
        if not all(d.values()):
            return d, "POC name and email are required."
        return d, None

    if scene == 4:
        d = {k: g(k) for k in ("shipping_service_type", "hts_code",
                               "shipment_origin", "shipment_destination",
                               "dimension", "weight")}
        if not d["shipment_origin"] or not d["shipment_destination"]:
            return d, "Origin and destination are required."
        if is_surf and (not d["dimension"] or not d["weight"]):
            return d, "Dimension and weight are required for SURF shipments."
        if d["shipping_service_type"] == "International" and not d["hts_code"]:
            return d, "International shipments need an HTS code."
        return d, None

    if scene == 5:
        d = {k: g(k) for k in ("freight_forwarder", "mode_of_transportation",
                               "expected_arrival_time")}
        if is_surf and not all(d.values()):
            return d, "Forwarder, transport mode and expected arrival are required for SURF."
        return d, None

    if scene == 6:
        if is_surf and not post.get("confirm_email_contents"):
            return {}, "Confirm the email contents to continue."
        return {"confirm_email_contents": bool(post.get("confirm_email_contents"))}, None

    if scene == 7:
        d = {k: g(k) for k in ("acknowledged_by", "acknowledged_time",
                               "damage_status", "damage_description")}
        d["received_acknowledgement"] = bool(post.get("received_acknowledgement"))
        if is_surf and not (d["received_acknowledgement"] and d["acknowledged_by"]
                            and d["acknowledged_time"]):
            return d, "The FD Logistics acknowledgement (name + time) is required for SURF."
        if d["damage_status"] == "damage" and not d["damage_description"]:
            return d, "Describe the damage found during visual inspection."
        return d, None

    if scene == 8:
        if not post.get("confirm_patch_hwdb"):
            return {}, "Confirm the HWDB update to continue."
        return {"confirm_patch_hwdb": True}, None

    return {}, "Unknown scene."


# ---- Box context (the Dashboard's part_info shape) -------------------------

def part_info(leaf, part_id: str, manifest) -> dict:
    """The Dashboard's ``part_info`` shape: hierarchy names/ids plus the
    current subcomponents keyed the way its CSV/patch builders expect."""
    subs = {}
    for i, m in enumerate(manifest):
        subs[str(i)] = {
            "Sub-component PID": m.get("part_id") or "",
            "Component Type Name": m.get("type_name") or "",
            "Functional Position Name": m.get("functional_position") or "",
        }
    return {
        "part_id": part_id,
        "system_name": leaf.system_name if leaf else "",
        "system_id": leaf.system_id if leaf else "",
        "subsystem_name": leaf.subsystem_name if leaf else "",
        "subsystem_id": leaf.subsystem_id if leaf else "",
        "part_type_name": leaf.name if leaf else "",
        "part_type_id": part_id.rsplit("-", 1)[0],
        "subcomponents": subs,
    }


# ---- Logistics CSV + email (scene 6) ---------------------------------------

def build_csv(checklist, info: dict) -> tuple[str, str]:
    """(filename, csv text) — the Dashboard's preshipping CSV, verbatim."""
    ws = checklist.state
    now = datetime.now().strftime("%Y-%m-%d-%H-%M")
    filename = f"{checklist.part_id}-preshipping-{now}.csv"
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=",")
    p4a, p4b = ws.get("PreShipping4a", {}), ws.get("PreShipping4b", {})
    rows = []
    if checklist.is_surf:
        rows.extend([
            ["Dimension", p4a.get("dimension", "")],
            ["Weight", p4a.get("weight", "")],
            ["Freight Forwarder name", p4b.get("freight_forwarder", "")],
            ["Mode of Transportation", p4b.get("mode_of_transportation", "")],
            ["Expected Arrival Date (CT)", p4b.get("expected_arrival_time", "")],
            ["Shipment's origin", p4a.get("shipment_origin", "")],
            ["HTS code", p4a.get("hts_code", "")],
            [],
        ])
    rows.extend([
        ["System Name (ID)", f"{info.get('system_name', '')} ({info.get('system_id', '')})"],
        ["Subsystem Name (ID)", f"{info.get('subsystem_name', '')} ({info.get('subsystem_id', '')})"],
        ["Component Type Name (ID)", f"{info.get('part_type_name', '')} ({info.get('part_type_id', '')})"],
        ["DUNE PID", checklist.part_id],
        [],
        ["Sub-component PID", "Component Type Name", "Func. Pos. Name"],
    ])
    for sc in info.get("subcomponents", {}).values():
        rows.append([sc.get("Sub-component PID", ""),
                     sc.get("Component Type Name", ""),
                     sc.get("Functional Position Name", "")])
    w.writerows(rows)
    return filename, buf.getvalue()


def email_html(checklist, csv_filename: str, sender_name: str, sender_email: str) -> str:
    """The Dashboard's logistics-email preview, verbatim (recipient
    included: FD Logistics <sdshipments@fnal.gov>)."""
    ws = checklist.state
    qarep_name = ws.get("PreShipping2", {}).get("qa_rep_name", "")
    qarep_email = ws.get("PreShipping2", {}).get("qa_rep_email", "")
    poc_name = ws.get("PreShipping3", {}).get("approver_name", "")
    poc_email = ws.get("PreShipping3", {}).get("approver_email", "")
    from_html = f"{sender_name} &lt;{sender_email}&gt;" if sender_email else sender_name
    return (
        "<table>"
        f"<tr><td width='100'>From:</td><td>{from_html}</td></tr>"
        "<tr><td>To:</td><td>FD Logistics Team &lt;sdshipments@fnal.gov&gt;</td></tr>"
        "<tr><td>Subject:</td><td>Request an acknowledgement for a new shipment</td></tr>"
        "<tr><td colspan='2'>&nbsp;</td></tr>"
        "<tr><td colspan='2'>"
        "Dear FD Logistics team,<br/><br/>"
        "I would like to request a new shipment.<br/>"
        f"This shipment has been approved by the Consortium QA Representative, {qarep_name} ({qarep_email}).<br/><br/>"
        f"Please find the attached csv file, {csv_filename}, that contains the required information for this shipment.<br/><br/>"
        "Should there be any issue with this shipment, email to:"
        f"<ul><li>{poc_name} &lt;{poc_email}&gt;</li></ul>"
        "Sincerely,<br/><br/>"
        f"{sender_name}<br/><br/>"
        f"Attachment: {csv_filename}"
        "</td></tr></table>"
    )


# ---- Shipping label (scene 8's "shipping sheet" PDF) ------------------------

def build_label_pdf(part_id: str, type_name: str, instance_label: str,
                    qr_png: bytes | None) -> bytes:
    """The Dashboard's shipping label, approximated: title, the item's HWDB
    QR code (left) + a Code128 barcode of the PID (right), centered
    instance / type / PID lines."""
    buf = io.BytesIO()
    cvs = rl_canvas.Canvas(buf, pagesize=letter)
    width, height = letter
    top = height - 0.75 * units.inch
    cvs.setFont("Helvetica-Bold", 24)
    cvs.drawCentredString(width / 2, top, "DUNE Shipping Sheet")
    top -= 0.6 * units.inch

    qr_size = 2.4 * units.inch
    x_left = 0.9 * units.inch
    if qr_png:
        try:
            img = PIL.Image.open(io.BytesIO(qr_png)).resize(
                (int(qr_size), int(qr_size)), PIL.Image.NEAREST)
            cvs.drawImage(ImageReader(img), x_left, top - qr_size, qr_size, qr_size)
        except Exception as e:
            logger.warning("label: QR draw failed: %s", e)
    barcode = code128.Code128(part_id, barHeight=0.55 * units.inch, barWidth=1.1)
    barcode.drawOn(cvs, x_left + qr_size + 0.5 * units.inch,
                   top - qr_size / 2 - 0.45 * units.inch)

    y = top - qr_size - 30
    cvs.setFont("Helvetica-Bold", 14)
    for line in (instance_label, type_name, part_id):
        if line:
            cvs.drawCentredString(width / 2, y, str(line))
            y -= 14
    cvs.showPage()
    cvs.save()
    return buf.getvalue()


# ---- The final HWDB patch (scene 8) -----------------------------------------

def _emails(v: str) -> list[str]:
    return [s.strip() for s in (v or "").split(",") if s.strip()]


def build_checklist_dict(checklist, info: dict, image_id) -> dict:
    """The ``Pre-Shipping Checklist`` spec dict — the Dashboard's keys
    byte-for-byte, SURF and non-SURF variants (typos included)."""
    ws = checklist.state
    p2, p3 = ws.get("PreShipping2", {}), ws.get("PreShipping3", {})
    p4a, p4b = ws.get("PreShipping4a", {}), ws.get("PreShipping4b", {})
    p6 = ws.get("PreShipping6", {})
    common_head = {
        "System Name (ID)": f"{info.get('system_name')} ({info.get('system_id')})",
        "Subsystem Name (ID)": f"{info.get('subsystem_name')} ({info.get('subsystem_id')})",
        "Component Type Name (ID)": f"{info.get('part_type_name')} ({info.get('part_type_id')})",
        "DUNE PID": checklist.part_id,
    }
    common_tail = {
        "Visual Inspection (YES = no damage)":
            "YES" if p6.get("damage_status") == "no damage" else "NO",
        "Visual Inspection Damage": p6.get("damage_description"),
        "Image ID for this Shipping Sheet": image_id,
    }
    if checklist.is_surf:
        return {
            "QA Rep name": p2.get("qa_rep_name"),
            "QA Rep Email": _emails(p2.get("qa_rep_email", "")),
            "POC name": p3.get("approver_name"),
            "POC Email": _emails(p3.get("approver_email", "")),
            **common_head,
            "HTS code": (p4a.get("hts_code")
                         if p4a.get("shipping_service_type") != "Domestic" else None),
            "Origin of this shipment": p4a.get("shipment_origin"),
            "Destination of this shipment": p4a.get("shipment_destination"),
            "Dimension of this shipment": p4a.get("dimension"),
            "Weight of this shipment": p4a.get("weight"),
            "Freight Forwarder name": p4b.get("freight_forwarder"),
            "Mode of Transportation": p4b.get("mode_of_transportation"),
            "Expected Arrival Date (CT)": p4b.get("expected_arrival_time"),
            "FD Logistics team acknoledgement (name)": p6.get("acknowledged_by"),
            "FD Logistics team acknoledgement (date in CT)": p6.get("acknowledged_time"),
            **common_tail,
        }
    return {
        "POC name": p3.get("approver_name"),
        "POC Email": _emails(p3.get("approver_email", "")),
        **common_head,
        "Origin of this shipment": p4a.get("shipment_origin"),
        "Destination of this shipment": p4a.get("shipment_destination"),
        **common_tail,
    }


def sub_pids(info: dict) -> list[dict]:
    """The ``SubPIDs`` spec list, Dashboard shape:
    ``[{"<type name> (<position>)": <pid>}, …]``."""
    return [{f"{v.get('Component Type Name')} ({v.get('Functional Position Name')})":
             v.get("Sub-component PID")}
            for v in info.get("subcomponents", {}).values()]


def execute_final_patch(api, checklist, info: dict, label_pdf: bytes) -> tuple[str | None, str | None]:
    """Scene 8's writes, in the Dashboard's order: upload the shipping sheet
    (comment "shipping sheet"), then PATCH the item with the checklist +
    SubPIDs folded into its latest specifications block. Returns
    ``(image_id, error)``."""
    filename = f"{checklist.part_id}-shipping-label.pdf"
    body = api.post_component_image(checklist.part_id, io.BytesIO(label_pdf),
                                    filename, comments="shipping sheet")
    if body.get("status") != "OK":
        return None, f"shipping sheet upload failed: {body.get('data') or body}"
    image_id = body.get("image_id")

    item = api.get_component(checklist.part_id).get("data") or {}
    specs_list = item.get("specifications") or [{}]
    specs = specs_list[-1] if isinstance(specs_list[-1], dict) else {}
    if not isinstance(specs.get("DATA"), dict):
        specs["DATA"] = {}
    specs["DATA"]["Pre-Shipping Checklist"] = [
        {k: v} for k, v in build_checklist_dict(checklist, info, image_id).items()]
    specs["DATA"]["SubPIDs"] = sub_pids(info)

    manufacturer = item.get("manufacturer")
    update_data = {
        "part_id": checklist.part_id,
        "comments": item.get("comments"),
        "manufacturer": {"id": manufacturer["id"]} if manufacturer else None,
        "serial_number": item.get("serial_number"),
        "specifications": specs,
    }
    body = api.patch_component(checklist.part_id, update_data)
    if body.get("status") != "OK":
        return image_id, f"checklist patch failed: {body.get('data') or body}"
    return image_id, None
