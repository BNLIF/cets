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


SHIPPING_SCENES = [
    (1, "Shipping1", "Contents confirm"),
    (2, "Shipping2", "Shipping documents"),
    (3, "Shipping3", "Approval email"),
    (4, "Shipping4", "Final approval"),
    (5, "Shipping5", "Mark in transit"),
    (6, "Shipping6", "Wrap up"),
]
N_SHIPPING_SCENES = len(SHIPPING_SCENES)


RECEIVING_SCENES = [
    (1, "Receiving1", "Contents confirm"),
    (2, "Receiving2", "Location update"),
    (3, "Receiving3", "Arrival email"),
]
N_RECEIVING_SCENES = len(RECEIVING_SCENES)


def scene_key(scene: int) -> str:
    return PRESHIPPING_SCENES[scene - 1][1]


def scene_title(scene: int) -> str:
    return PRESHIPPING_SCENES[scene - 1][2]


def shipping_scene_key(scene: int) -> str:
    return SHIPPING_SCENES[scene - 1][1]


def shipping_scene_title(scene: int) -> str:
    return SHIPPING_SCENES[scene - 1][2]


def receiving_scene_key(scene: int) -> str:
    return RECEIVING_SCENES[scene - 1][1]


def receiving_scene_title(scene: int) -> str:
    return RECEIVING_SCENES[scene - 1][2]


def artifact_filename(part_id: str, stem: str, original: str) -> str:
    """The Dashboard's shipping-artifact naming:
    ``{pid}-{stem}-{YYYY-MM-DD-HH-MM}{ext}``."""
    ext = ("." + original.rsplit(".", 1)[-1]) if "." in original else ""
    return f"{part_id}-{stem}-{datetime.now():%Y-%m-%d-%H-%M}{ext}"


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


def clean_shipping_scene(scene: int, is_surf: bool, shipping_type: str,
                         post, merged: dict) -> tuple[dict, str | None]:
    """Validate one shipping scene (the Dashboard's rules). ``merged`` is the
    scene's state AFTER this request's uploads/fields were folded in — file
    requirements check it, since documents may have arrived on an earlier
    submit."""
    g = lambda k: (post.get(k) or "").strip().replace("T", " ")

    if scene == 1:
        if not post.get("confirm_list"):
            return {}, "Please confirm the component list before continuing."
        return {"confirm_list": True}, None

    if scene == 2:
        if is_surf:
            if not (merged.get("bol_info") or {}).get("image_id"):
                return {}, "Please select a Bill of Lading image/PDF file before continuing."
            if shipping_type == "International" and not (merged.get("proforma_info") or {}).get("image_id"):
                return {}, "Please select a Proforma Invoice image/PDF file for this international shipment."
        return {}, None

    if scene == 3:
        d = {"confirm_email_contents": bool(post.get("confirm_email_contents"))}
        if is_surf and not d["confirm_email_contents"]:
            return d, "Please confirm that you have sent the email before continuing."
        return d, None

    if scene == 4:
        d = {
            "received_approval": bool(post.get("received_approval")),
            "approved_by": g("approved_by"),
            "approved_time": g("approved_time"),
            "confirm_attached_sheet": bool(post.get("confirm_attached_sheet")),
            "confirm_insured": bool(post.get("confirm_insured")),
        }
        if is_surf:
            if not d["received_approval"]:
                return d, "Please wait for and confirm final approval from the FD Logistics team."
            if not d["approved_by"] or not d["approved_time"]:
                return d, "Please provide the final approver name and approval time."
            if not ({**merged, **d}.get("approval_info") or {}).get("image_id"):
                return d, "Please upload the final approval message image or PDF."
            if not d["confirm_attached_sheet"] or not d["confirm_insured"]:
                return d, "Please confirm that the shipping sheet is attached and the cargo is insured."
        return d, None

    if scene == 5:
        d = {"shipment_time": g("shipment_time"), "comments": g("comments"),
             "affirm_shipment": bool(post.get("affirm_shipment"))}
        if not d["shipment_time"]:
            return d, "Please provide the shipment date/time before continuing."
        if not d["affirm_shipment"]:
            return d, "Please confirm that you have shipped the cargo."
        return d, None

    if scene == 6:
        return {}, None

    return {}, "Unsupported scene."


def clean_receiving_scene(scene: int, post) -> tuple[dict, str | None]:
    """Validate one receiving scene (the Dashboard's rules: everything on
    scene 2 must be present before the writes fire)."""
    g = lambda k: (post.get(k) or "").strip().replace("T", " ")

    if scene == 1:
        if not post.get("confirm_list"):
            return {}, "Please confirm the component list before continuing."
        return {"confirm_list": True}, None

    if scene == 2:
        d = {"location_id": g("location_id"), "arrived": g("arrived"),
             "comments": g("comments"),
             "affirm_update": bool(post.get("affirm_update"))}
        if not d["location_id"]:
            return d, "Please pick the arrival location."
        if not d["arrived"]:
            return d, "Please provide the arrival date/time."
        if not d["affirm_update"]:
            return d, "Please confirm that you wish to update the location now."
        return d, None

    if scene == 3:
        if not post.get("confirm_email_contents"):
            return {}, "Please confirm that you have sent the email before continuing."
        return {"confirm_email_contents": True}, None

    return {}, "Unsupported scene."


def shipping_service_type(spec_data: dict | None) -> str:
    """The Dashboard's rule: an HTS code in the box's Pre-Shipping Checklist
    spec means International, else Domestic."""
    entries = (spec_data or {}).get("Pre-Shipping Checklist")
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, dict) and "HTS code" in entry:
                return "International" if (entry.get("HTS code") or "") else "Domestic"
    return "Domestic"


def poc_from(preship_state: dict | None, spec_data: dict | None) -> tuple[str, str]:
    """(POC name, POC email string) — from the Explorer's pre-shipping run
    when it exists, else off the box's Pre-Shipping Checklist spec (so a
    Dashboard-run pre-shipping still feeds our shipping checklist)."""
    p3 = (preship_state or {}).get("PreShipping3") or {}
    if p3.get("approver_name") or p3.get("approver_email"):
        return p3.get("approver_name", ""), p3.get("approver_email", "")
    name = email = ""
    entries = (spec_data or {}).get("Pre-Shipping Checklist")
    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if "POC name" in entry:
                name = entry.get("POC name") or ""
            if "POC Email" in entry:
                v = entry.get("POC Email")
                email = ", ".join(v) if isinstance(v, list) else (v or "")
    return name, email


def shipping_email_html(part_id: str, poc_name: str, poc_email: str,
                        sender_name: str, sender_email: str) -> str:
    """The Dashboard's final-approval request email, verbatim."""
    from_html = f"{sender_name} &lt;{sender_email}&gt;" if sender_email else sender_name
    return (
        "<table>"
        f"<tr><td width='100'>From:</td><td>{from_html}</td></tr>"
        "<tr><td>To:</td><td>FD Logistics Team &lt;sdshipments@fnal.gov&gt;</td></tr>"
        f"<tr><td>Subject:</td><td>Request for the final approval for shipment PID = {part_id}</td></tr>"
        "<tr><td colspan='2'>&nbsp;</td></tr>"
        "<tr><td colspan='2'>"
        "Dear FD Logistics team,<br/><br/>"
        "I would like to request a new shipment.<br/><br/>"
        "Should there be any issue with this shipment, email to:"
        f"<ul><li>{poc_name} &lt;{poc_email}&gt;</li></ul>"
        "Sincerely,<br/><br/>"
        f"{sender_name}<br/>{sender_email}<br/>"
        "</td></tr></table>"
    )


def build_shipping_checklist_dict(checklist, info: dict,
                                  poc_name: str, poc_email: str) -> dict:
    """The ``Shipping Checklist`` spec dict, Dashboard keys verbatim — base
    keys always, artifact/approval extras on the SURF route only."""
    ws = checklist.state
    s2, s4 = ws.get("Shipping2", {}), ws.get("Shipping4", {})
    d = {
        "POC name": poc_name,
        "POC Email": _emails(poc_email),
        "System Name (ID)": f"{info.get('system_name')} ({info.get('system_id')})",
        "Subsystem Name (ID)": f"{info.get('subsystem_name')} ({info.get('subsystem_id')})",
        "Component Type Name (ID)": f"{info.get('part_type_name')} ({info.get('part_type_id')})",
        "DUNE PID": checklist.part_id,
    }
    if checklist.is_surf:
        d.update({
            "Image ID for BoL": (s2.get("bol_info") or {}).get("image_id"),
            "Image ID for Proforma Invoice": (s2.get("proforma_info") or {}).get("image_id"),
            "Image ID for the final approval message": (s4.get("approval_info") or {}).get("image_id"),
            "FD Logistics team final approval (name)": s4.get("approved_by"),
            "FD Logistics team final approval (date in CST)": s4.get("approved_time"),
            "DUNE Shipping Sheet has been attached": s4.get("confirm_attached_sheet"),
            "This shipment has been adequately insured for transit": s4.get("confirm_insured"),
        })
    return d


def build_shipping_csv(checklist, info: dict, poc_name: str, poc_email: str) -> tuple[str, str]:
    """(filename, csv text) — the Dashboard's shipping wrap-up CSV, verbatim
    (including its one-cell SubPID rows)."""
    ws = checklist.state
    filename = f"{checklist.part_id}-shipping-{datetime.now():%Y-%m-%d-%H-%M}.csv"
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=",")
    rows = [
        ["POC name", poc_name],
        ["POC Email", poc_email],
        ["System Name (ID)", f"{info.get('system_name', '')} ({info.get('system_id', '')})"],
        ["Subsystem Name (ID)", f"{info.get('subsystem_name', '')} ({info.get('subsystem_id', '')})"],
        ["Component Type Name (ID)", f"{info.get('part_type_name', '')} ({info.get('part_type_id', '')})"],
        ["DUNE PID", checklist.part_id],
    ]
    if checklist.is_surf:
        s2, s4 = ws.get("Shipping2", {}), ws.get("Shipping4", {})
        rows.extend([
            ["Image ID for BoL", (s2.get("bol_info") or {}).get("image_id", "")],
            ["Image ID for Proforma Invoice", (s2.get("proforma_info") or {}).get("image_id", "")],
            ["Image ID for the final approval message", (s4.get("approval_info") or {}).get("image_id", "")],
            ["FD Logistics team final approval (name)", s4.get("approved_by", "")],
            ["FD Logistics team final approval (date in CT)", s4.get("approved_time", "")],
            ["DUNE Shipping Sheet has been attached", s4.get("confirm_attached_sheet", False)],
            ["This shipment has been adequately insured for transit", s4.get("confirm_insured", False)],
        ])
    rows.append(["SubPIDs:"])
    for sc in info.get("subcomponents", {}).values():
        rows.append([f"{sc.get('Component Type Name', '')} ({sc.get('Functional Position Name', '')}),{sc.get('Sub-component PID', '')}"])
    w.writerows(rows)
    return filename, buf.getvalue()


def patch_shipping(api, checklist, info: dict, poc_name: str, poc_email: str) -> str | None:
    """Scene 4's write: fold the Shipping Checklist into the item's latest
    specs block and PATCH — same envelope as pre-shipping. Error or None."""
    item = api.get_component(checklist.part_id).get("data") or {}
    specs_list = item.get("specifications") or [{}]
    specs = specs_list[-1] if isinstance(specs_list[-1], dict) else {}
    if not isinstance(specs.get("DATA"), dict):
        specs["DATA"] = {}
    specs["DATA"]["Shipping Checklist"] = [
        {k: v} for k, v in
        build_shipping_checklist_dict(checklist, info, poc_name, poc_email).items()]
    manufacturer = item.get("manufacturer")
    body = api.patch_component(checklist.part_id, {
        "part_id": checklist.part_id,
        "comments": item.get("comments"),
        "manufacturer": {"id": manufacturer["id"]} if manufacturer else None,
        "serial_number": item.get("serial_number"),
        "specifications": specs,
    })
    return None if body.get("status") == "OK" else str(body.get("data") or body)


def receiving_email_html(part_id: str, poc_name: str, poc_email: str,
                         sender_name: str, sender_email: str,
                         location_name: str, arrived: str) -> str:
    """The Dashboard's arrival notification to the POC, verbatim — its
    "Reciving" subject typo included (the pid is interpolated, though: the
    Dashboard drops it via a missing f-prefix, plainly a bug)."""
    try:
        formatted = datetime.fromisoformat(arrived).strftime(
            "<b>%B %d, %Y</b> at <b>%I:%M %p</b> (Central Time)")
    except ValueError:
        formatted = arrived
    from_html = f"{sender_name} &lt;{sender_email}&gt;" if sender_email else sender_name
    return (
        "<table>"
        f"<tr><td width='100'>From:</td><td>{from_html}</td></tr>"
        f"<tr><td>To:</td><td>{poc_name} &lt;{poc_email}&gt;</td></tr>"
        f"<tr><td>Subject:</td><td>Final Reciving checklist for shipment {part_id}</td></tr>"
        "<tr><td colspan='2'>&nbsp;</td></tr>"
        "<tr><td colspan='2'>"
        f"Dear {poc_name},<br/><br/>"
        f"Your shipment, {part_id}, has arrived at <b>{location_name}</b> at "
        f"{formatted}.<br/><br/>"
        "Sincerely,<br/><br/>"
        f"{sender_name}<br/>{sender_email}<br/>"
        "</td></tr></table>"
    )


def receive_box(api, checklist, manifest: list[dict]) -> str | None:
    """Scene 2's writes — the Dashboard's ``update_locations_and_detach``:
    post the arrival location on the box, then on every subcomponent, then
    PATCH all occupied functional positions to ``None`` (the structural
    write that "opens the box"). The transshipping route posts the box's
    location only and keeps the contents linked. Error or None."""
    r2 = checklist.state.get("Receiving2", {})
    payload = {
        "location": {"id": (r2.get("location") or {}).get("institution_id")},
        "arrived": r2.get("arrived"),
        "comments": r2.get("comments", ""),
    }
    body = api.post_location(checklist.part_id, payload)
    if body.get("status") != "OK":
        return f"location post for {checklist.part_id} failed: {body.get('data') or body}"
    if checklist.route == "confirm_transshipping":
        return None
    for m in manifest:
        body = api.post_location(m["part_id"], payload)
        if body.get("status") != "OK":
            return f"location post for {m['part_id']} failed: {body.get('data') or body}"
    if manifest:
        body = api.patch_subcomponents(checklist.part_id, {
            "component": {"part_id": checklist.part_id},
            "subcomponents": {m["functional_position"]: None for m in manifest},
        })
        if body.get("status") != "OK":
            return f"detach patch failed: {body.get('data') or body}"
    return None


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
