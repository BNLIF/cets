"""FEMB assembly → HWDB upload (issue #137). Pure functions, no Django views.

One idempotent action per FEMB, "sync HWDB to the local assembly":

1. Resolve the FEMB part type (HD/VD from the version string; dev has one
   generic type) and read its connectors — the 18 functional-position names
   and the chip part type each slot accepts. Reading them live is what lets
   dev (``femb_prep`` only accepts the preproduction chip types) and prod run
   the same code.
2. Find-or-create the FEMB item (serial ``BNL/FEMB/<version>/<sn>``).
3. Find-or-create every chip currently mounted per the local db. Freshly
   created chips are enabled (required before attaching; wipes comments, so
   never on existing items) and set to 110. Chips at 180 (Broken) are refused.
4. Diff HWDB's current slots against the local assembly:
   - empty slot → attach;
   - same chip → keep;
   - different chip that our db marks as removed at a repair → swap, and the
     old chip goes to 180 with a comment; the FEMB gets the repair note;
   - different chip our db has never heard of → refuse to touch the slot
     (the local record is probably stale — warn and leave it).
5. One ``PATCH …/subcomponents`` with the complete slot map.
6. Upload the FRONT/BACK assembly and repair photos not already attached.

Re-running yields no diff and no writes beyond the reads.

Karla's ``submit_femb.py`` / ``submit_repaired_femb.py`` are the reference for
the API sequencing; see the issue for what was verified against dev/prod.
"""

from __future__ import annotations

import logging
import mimetypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional

from django.conf import settings
from django.utils import timezone

from core.models import COLDATA, ColdADC, FembRepair, LArASIC

logger = logging.getLogger(__name__)

# HWDB status ids (from Karla's dune_ce_hwdb.py part_status table).
STATUS_UNKNOWN = 0
STATUS_IN_FABRICATION = 100
STATUS_WAITING_QC = 110
STATUS_BROKEN = 180

# Local model → the type word HWDB uses inside functional-position names.
CHIP_MODELS = {"LArASIC": LArASIC, "ColdADC": ColdADC, "COLDATA": COLDATA}


class UploadError(Exception):
    """Per-FEMB failure the orchestrator reports and moves past."""


# ---- Result shapes --------------------------------------------------------


@dataclass
class FembResult:
    femb_label: str                 # "IO-1865-1L/00002"
    part_id: str | None = None      # HWDB part_id of the FEMB
    created: bool = False           # FEMB item created this run
    chips_created: int = 0
    attached: list[str] = field(default_factory=list)   # slot labels newly filled
    swapped: list[str] = field(default_factory=list)    # slot labels whose chip changed
    refused: list[str] = field(default_factory=list)    # slot labels left alone (warnings)
    photos: int = 0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def changed(self) -> bool:
        return self.created or bool(self.attached or self.swapped or self.photos)


@dataclass(frozen=True)
class ChipRef:
    part_id: str
    created: bool
    status_id: int | None


# ---- Settings / naming helpers --------------------------------------------


def femb_defaults(instance: str) -> dict:
    """``HWDB_COMPONENT_DEFAULTS["femb"]`` with per-instance dicts resolved."""
    raw = settings.HWDB_COMPONENT_DEFAULTS["femb"]
    out = {}
    for k, v in raw.items():
        if isinstance(v, dict) and set(v) <= {"prod", "dev"}:
            if instance not in v:
                raise UploadError(f"femb default {k!r} has no value for instance {instance!r}")
            out[k] = v[instance]
        else:
            out[k] = v
    return out


def hwdb_serial(femb) -> str:
    """The serial HWDB stores for a FEMB — the full OCR path string."""
    return f"BNL/FEMB/{femb.version}/{femb.serial_number}"


def femb_part_type(profile: dict, femb) -> str:
    """Pick the FEMB part type from the HD/VD marker at the start of the version.

    OCR sometimes reads the letter O as a zero ("I0-1865-…"); tolerate that
    for the type choice only — the serial itself is never corrected.
    """
    version = femb.version.upper().replace("I0-", "IO-", 1)
    for marker, part_type_id in profile["femb_part_types"].items():
        if version.startswith(marker):
            return part_type_id
    raise UploadError(
        f"cannot tell HD from VD for version {femb.version!r} "
        f"(expected one of {sorted(profile['femb_part_types'])})"
    )


def position_label(chip_type: str, femb_pos: str) -> str:
    """``("LArASIC", "F1")`` → ``"(F) LArASIC 1"`` — HWDB's functional-position name."""
    return f"({femb_pos[0]}) {chip_type} {femb_pos[1:]}"


def femb_dirname(femb) -> str:
    """The OCR per-FEMB directory name: ``BNL_FEMB_IO_1865_1L_00002``."""
    return f"BNL_FEMB_{femb.version.replace('-', '_')}_{femb.serial_number}"


# ---- Local state ----------------------------------------------------------


def local_assembly(femb) -> dict[str, tuple[str, str]]:
    """Currently mounted chips: ``{label: (chip_type, serial)}``."""
    out = {}
    for chip_type, model in CHIP_MODELS.items():
        qs = model.objects.filter(femb=femb, removed_at_repair__isnull=True).exclude(femb_pos="")
        for chip in qs.exclude(femb_pos__isnull=True):
            out[position_label(chip_type, chip.femb_pos)] = (chip_type, chip.serial_number)
    return out


def removed_chips(femb) -> dict[str, FembRepair]:
    """Chips our db says were taken off this FEMB: ``{serial: repair}``."""
    out = {}
    for repair in femb.repairs.all():
        for rel in ("removed_larasics", "removed_coldadcs", "removed_coldatas"):
            for chip in getattr(repair, rel).all():
                out[chip.serial_number] = repair
    return out


def find_photos(ocr_root: Optional[Path], femb) -> list[Path]:
    """FRONT/BACK PNGs for the assembly and every repair_N of this FEMB.

    Layout under FEMB_OCR_DIR: ``batch_<id>/<femb dir>/femb_*.png`` and
    ``batch_<id>_rework/<femb dir>/repair_N/femb_*.png``. The batch dir is
    globbed rather than derived from ``femb.batch_id`` so reworks (which live
    in a different batch dir) are found too.
    """
    if ocr_root is None:
        return []
    name = femb_dirname(femb)
    photos = list(ocr_root.glob(f"batch_*/{name}/femb_*.png"))
    photos += ocr_root.glob(f"batch_*/{name}/repair_*/femb_*.png")
    return sorted(photos)


# ---- HWDB primitives ------------------------------------------------------


def load_connectors(api, femb_type_id: str) -> dict[str, str]:
    """``{functional position: chip part_type_id}`` from the FEMB type record."""
    body = api.get_component_type(femb_type_id)
    data = body.get("data") or body
    conns = data.get("connectors") or {}
    if not conns:
        raise UploadError(f"FEMB type {femb_type_id} declares no connectors")
    return dict(conns)


def _status_id(item: dict) -> int | None:
    st = item.get("status")
    if isinstance(st, dict):
        return st.get("id")
    return None


def _ok(body: dict, what: str) -> dict:
    if body.get("status") == "ERROR":
        raise UploadError(f"{what}: {body.get('data') or body}")
    return body


def _create(api, part_type_id: str, serial: str, *, d: dict, manufacturer_id: int,
            specs: dict, comments: str = "") -> str:
    payload = {
        "component_type": {"part_type_id": part_type_id},
        "serial_number": serial,
        "country_code": d["country_code"],
        "comments": comments,
        "institution": {"id": d["institution_id"]},
        "manufacturer": {"id": manufacturer_id},
        "specifications": {"DATA": specs},
        "status": {"id": d["initial_status_id"]},
    }
    body = _ok(api.create_component(part_type_id, payload), f"create {serial}")
    part_id = body.get("part_id")
    if not part_id:
        raise UploadError(f"create OK but no part_id for {serial}: {body}")
    api.post_location(part_id, {
        "arrived": timezone.now().strftime("%Y-%m-%d %H:%M:%S"),
        "comments": "",
        "location": {"id": d["institution_id"]},
    })
    return part_id


def ensure_chip(api, chip_type_id: str, serial: str, d: dict) -> ChipRef:
    """Find-or-create a chip so it can be attached. Applies Karla's rules:
    enable only when created; bump placeholder statuses to 110; leave any
    meaningful status alone. The caller checks ``status_id == STATUS_BROKEN``.
    """
    existing = api.find_component_by_serial(chip_type_id, serial)
    if existing is None:
        part_id = _create(api, chip_type_id, serial, d=d,
                          manufacturer_id=d["chip_manufacturer_id"], specs={})
        _ok(api.enable_component(part_id), f"enable {serial}")
        # enable resets status; the create payload's 110 does not survive it.
        api.patch_component(part_id, {"part_id": part_id, "status": {"id": STATUS_WAITING_QC}})
        return ChipRef(part_id=part_id, created=True, status_id=STATUS_WAITING_QC)

    part_id = existing["part_id"]
    status_id = _status_id(existing)
    if status_id is None:
        status_id = _status_id(api.get_component(part_id).get("data") or {})
    if status_id in (None, STATUS_UNKNOWN, STATUS_IN_FABRICATION):
        api.patch_component(part_id, {"part_id": part_id, "status": {"id": STATUS_WAITING_QC}})
        status_id = STATUS_WAITING_QC
    return ChipRef(part_id=part_id, created=False, status_id=status_id)


def ensure_femb(api, femb, femb_type_id: str, assembly: dict, d: dict) -> tuple[str, bool]:
    """Find-or-create the FEMB item. Returns ``(part_id, created)``."""
    serial = hwdb_serial(femb)
    existing = api.find_component_by_serial(femb_type_id, serial)
    if existing is not None:
        return existing["part_id"], False
    specs = {label: sn for label, (_t, sn) in sorted(assembly.items())}
    # Not enabled: Karla only enables the chips (enable is what makes an item
    # attachable as a sub-component; the FEMB is the container here).
    part_id = _create(api, femb_type_id, serial, d=d,
                      manufacturer_id=d["manufacturer_id"], specs=specs)
    return part_id, True


def current_slots(api, femb_pid: str) -> dict[str, str]:
    """``{functional position: part_id}`` of what HWDB has attached now."""
    body = api.get_subcomponents(femb_pid)
    return {
        row["functional_position"]: row["part_id"]
        for row in (body.get("data") or [])
        if row.get("functional_position") and row.get("part_id")
    }


def append_comment(api, part_id: str, note: str, *, status_id: int | None = None) -> None:
    """Append a timestamped line to an item's comments (HWDB has no
    comment log, only one free-text field). Optionally sets status in the
    same PATCH so a detached chip costs one call, not two.
    """
    data = api.get_component(part_id).get("data") or {}
    existing = data.get("comments") or ""
    stamp = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{stamp}] {note}"
    payload = {"part_id": part_id, "comments": f"{existing}\n{entry}" if existing else entry}
    if status_id is not None:
        payload["status"] = {"id": status_id}
    _ok(api.patch_component(part_id, payload), f"comment on {part_id}")


def upload_photos(api, part_id: str, photos: list[Path]) -> int:
    """Attach photos whose filename is not already on the item. Returns count."""
    if not photos:
        return 0
    have = {row.get("image_name") for row in (api.get_images(part_id).get("data") or [])}
    n = 0
    for p in photos:
        if p.name in have:
            continue
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        with open(p, "rb") as fp:
            api.post_component_image(part_id, fp, p.name, content_type=ctype)
        n += 1
    return n


# ---- Orchestrator ---------------------------------------------------------


def upload_femb(api, femb, *, profile: dict, instance: str,
                ocr_root: Optional[Path] = None,
                attach_photos: bool = True) -> Iterator[str | FembResult]:
    """Sync one FEMB to HWDB. Yields progress lines; the LAST item yielded is
    the ``FembResult`` (so a streaming view can print as it goes and still
    get a summary to act on).
    """
    label = f"{femb.version}/{femb.serial_number}"
    res = FembResult(femb_label=label)
    try:
        d = femb_defaults(instance)
        femb_type_id = femb_part_type(profile, femb)
        connectors = load_connectors(api, femb_type_id)
        assembly = local_assembly(femb)
        if not assembly:
            raise UploadError("no chips recorded locally for this FEMB; import the OCR batch first")
        unknown = sorted(set(assembly) - set(connectors))
        if unknown:
            raise UploadError(f"local slot(s) {unknown} are not connectors of {femb_type_id}")

        part_id, res.created = ensure_femb(api, femb, femb_type_id, assembly, d)
        res.part_id = part_id
        yield f"  FEMB {hwdb_serial(femb)} → {part_id}{' (created)' if res.created else ''}\n"

        # Chips: find-or-create, remember serial per part_id for the diff.
        desired: dict[str, str] = {}          # label → part_id
        serial_of: dict[str, str] = {}        # part_id → serial
        for slot, (chip_type, serial) in sorted(assembly.items()):
            try:
                ref = ensure_chip(api, connectors[slot], serial, d)
            except UploadError as e:
                res.refused.append(slot)
                yield f"  ! {slot} {serial}: {e}\n"
                continue
            if ref.created:
                res.chips_created += 1
            if ref.status_id == STATUS_BROKEN:
                res.refused.append(slot)
                yield f"  ! {slot} {serial} ({ref.part_id}) is marked Broken — not attaching\n"
                continue
            desired[slot] = ref.part_id
            serial_of[ref.part_id] = serial
        if res.chips_created:
            yield f"  {res.chips_created} chip item(s) created\n"

        # Diff against HWDB's current slot map.
        current = {} if res.created else current_slots(api, part_id)
        removed = removed_chips(femb)
        final: dict[str, Optional[str]] = {slot: current.get(slot) for slot in connectors}
        detached: list[tuple[str, str, str]] = []   # (slot, old part_id, old serial)
        for slot, new_pid in desired.items():
            cur_pid = current.get(slot)
            if cur_pid is None:
                final[slot] = new_pid
                res.attached.append(slot)
            elif cur_pid == new_pid:
                continue
            else:
                cur = api.get_component(cur_pid).get("data") or {}
                cur_serial = cur.get("serial_number") or cur_pid
                if cur_serial in removed:
                    final[slot] = new_pid
                    res.swapped.append(slot)
                    detached.append((slot, cur_pid, cur_serial))
                    yield f"  swap {slot}: {cur_serial} → {serial_of[new_pid]}\n"
                else:
                    res.refused.append(slot)
                    yield (f"  ! {slot} holds {cur_serial} in HWDB, which our db never saw on "
                           f"this FEMB — leaving it (local record may be stale)\n")

        if res.attached or res.swapped:
            _ok(api.patch_subcomponents(part_id, {"component": {"part_id": part_id},
                                                  "subcomponents": final}),
                "attach sub-components")
            yield f"  attached {len(res.attached)}, swapped {len(res.swapped)} slot(s)\n"
        else:
            yield "  slots already match\n"

        # Detached chips → Broken + note; FEMB gets one note per repair.
        repairs_noted: dict[int, list[str]] = {}
        for slot, old_pid, old_serial in detached:
            repair = removed[old_serial]
            append_comment(api, old_pid,
                           f"Removed from FEMB {hwdb_serial(femb)} ({slot}) during repair "
                           f"#{repair.iteration_number}.",
                           status_id=STATUS_BROKEN)
            repairs_noted.setdefault(repair.pk, []).append(slot)
        for repair_pk, slots in repairs_noted.items():
            repair = FembRepair.objects.get(pk=repair_pk)
            note = (f"Repaired (#{repair.iteration_number}, {repair.date:%Y-%m-%d}, "
                    f"operator {repair.operator or 'unknown'}): "
                    f"{repair.what_was_fixed or 'chip(s) replaced'}. "
                    f"Slot(s) replaced: {', '.join(slots)}.")
            append_comment(api, part_id, note)
            yield f"  noted repair #{repair.iteration_number} on the FEMB\n"

        if attach_photos:
            res.photos = upload_photos(api, part_id, find_photos(ocr_root, femb))
            if res.photos:
                yield f"  {res.photos} photo(s) uploaded\n"
    except UploadError as e:
        res.error = str(e)
        yield f"  *** {e} ***\n"
    except Exception as e:  # HTTP errors from the client, unexpected shapes
        logger.exception("upload_femb crashed for %s", label)
        res.error = f"crashed: {e}"
        yield f"  *** crashed: {e} ***\n"
    yield res
