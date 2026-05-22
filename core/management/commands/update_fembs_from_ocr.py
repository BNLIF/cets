import os
import re
from datetime import datetime, timezone
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from decouple import config
from core.models import FEMB, FE, ADC, COLDATA, FEMB_REPAIR


COMPONENT_MODELS = {"FE": FE, "ADC": ADC, "COLDATA": COLDATA}


def parse_parts_file(filepath):
    """
    Parse a femb_parts_*.txt file.
    Returns (femb_version, femb_sn, components) where components is a list of
    {"type": str, "serial_number": str, "position": str}.
    Returns (None, None, []) on failure.
    """
    femb_version = ""
    femb_sn = ""
    components = []

    try:
        with open(filepath, "r") as f:
            lines = f.readlines()
    except OSError:
        return None, None, []

    for line in lines:
        line_parts = [p.strip().replace('"', "") for p in line.strip().split(",")]
        if not line_parts or len(line_parts) < 2:
            continue

        raw_type = line_parts[0]
        serial_number = line_parts[1]

        if "FEMB" in raw_type:
            path_parts = serial_number.split("/")
            femb_version = path_parts[-2]
            femb_sn = path_parts[-1]
        else:
            comp_type = ""
            if "LArASIC" in raw_type or "FE" in raw_type:
                comp_type = "FE"
            elif "ColdADC" in raw_type or "ADC" in raw_type:
                comp_type = "ADC"
            elif "COLDATA" in raw_type:
                comp_type = "COLDATA"

            pos_match = re.search(r"\(([FB])\) .* (\d+)", raw_type)
            position = ""
            if pos_match:
                position = pos_match.group(1) + pos_match.group(2)

            if comp_type:
                components.append(
                    {"type": comp_type, "serial_number": serial_number, "position": position}
                )

    if not femb_version or not femb_sn:
        return None, None, []

    return femb_version, femb_sn, components


def parse_inspection_note(filepath):
    """
    Parse an inspection_note.txt file.
    Returns a dict with keys: femb_sn, batch_id, inspection_type, iteration_number,
    date, operator, what_was_fixed, comments.
    """
    result = {
        "femb_sn": "",
        "batch_id": "",
        "inspection_type": "",
        "iteration_number": None,
        "date": None,
        "operator": "",
        "what_was_fixed": "",
        "comments": "",
    }
    try:
        with open(filepath, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("FEMB SN:"):
                    result["femb_sn"] = line.split(":", 1)[1].strip()
                elif line.startswith("Batch ID:"):
                    result["batch_id"] = line.split(":", 1)[1].strip()
                elif line.startswith("Inspection Type:"):
                    result["inspection_type"] = line.split(":", 1)[1].strip()
                elif line.startswith("Inspection/Repair Iteration Number:"):
                    val = line.split(":", 1)[1].strip()
                    if val.isdigit():
                        result["iteration_number"] = int(val)
                elif line.startswith("Date:"):
                    val = line.split(":", 1)[1].strip()
                    try:
                        result["date"] = datetime.strptime(val, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                    except ValueError:
                        pass
                elif line.startswith("Operator Name:"):
                    result["operator"] = line.split(":", 1)[1].strip()
                elif line.startswith("What was fixed:"):
                    result["what_was_fixed"] = line.split(":", 1)[1].strip()
                elif line.startswith("Comments:"):
                    result["comments"] = line.split(":", 1)[1].strip()
    except OSError:
        pass
    return result


def components_to_state(components):
    """
    Convert a list of component dicts (from parse_parts_file) to a state dict
    keyed by (type, position) → serial_number.
    This avoids collisions between chip types that share the same position label.
    """
    return {
        (c["type"], c["position"]): c["serial_number"]
        for c in components
        if c["position"]
    }


def compute_repair_diff(before_components, after_components):
    """
    Diff two component lists (each as returned by parse_parts_file) keyed by
    (type, position). Returns (removed_chips, added_chips); each chip is a dict
    with keys "type", "serial_number", "position".

    A chip swapped at the same position appears in BOTH lists (removed old SN +
    added new SN). A position appearing only in `before` yields a removal; only
    in `after` yields an addition.
    """
    before = components_to_state(before_components)
    after = components_to_state(after_components)

    removed_chips = []
    added_chips = []

    for key in set(before.keys()) | set(after.keys()):
        comp_type, pos = key
        before_sn = before.get(key)
        after_sn = after.get(key)

        if before_sn and after_sn:
            if before_sn != after_sn:
                removed_chips.append({"type": comp_type, "serial_number": before_sn, "position": pos})
                added_chips.append({"type": comp_type, "serial_number": after_sn, "position": pos})
        elif before_sn:
            removed_chips.append({"type": comp_type, "serial_number": before_sn, "position": pos})
        elif after_sn:
            added_chips.append({"type": comp_type, "serial_number": after_sn, "position": pos})

    return removed_chips, added_chips


class Command(BaseCommand):
    help = (
        "Scans the FEMB_OCR_DIR to find and add new FEMB serial numbers to the database. "
        "Also processes repair_N/ subdirectories to record chip-replacement history."
    )

    def handle(self, *args, **options):
        try:
            femb_ocr_dir = config("FEMB_OCR_DIR")
        except Exception as e:
            raise CommandError(f"Configuration for FEMB_OCR_DIR not found. Error: {e}")

        if not os.path.isdir(femb_ocr_dir):
            raise CommandError(
                f"FEMB_OCR_DIR '{femb_ocr_dir}' does not exist or is not a directory."
            )

        self.stdout.write(f"Scanning directory: {femb_ocr_dir}")

        # Separate regular femb_parts files from repair-directory ones
        regular_files = []   # filepaths not inside a repair_N/ dir
        repair_files = []    # (filepath, repair_dir_path, iteration_number)

        for root, dirs, files in os.walk(femb_ocr_dir):
            # Sort dirs so repair_1 < repair_2 < ... are processed in order
            dirs.sort()
            for file in files:
                if not (file.startswith("femb_parts_") and file.endswith(".txt")):
                    continue
                filepath = os.path.join(root, file)
                dirname = os.path.basename(root)
                repair_match = re.fullmatch(r"repair_(\d+)", dirname)
                if repair_match:
                    repair_files.append((filepath, root, int(repair_match.group(1))))
                else:
                    regular_files.append(filepath)

        # ------------------------------------------------------------------ #
        # Phase 1: collect pending regular (non-repair) changes               #
        # ------------------------------------------------------------------ #
        new_fembs_to_create = []
        components_to_update = []

        for filepath in regular_files:
            filename = os.path.basename(filepath)
            self.stdout.write(f"Processing file: {filepath}")

            femb_version, femb_sn, components = parse_parts_file(filepath)
            if not femb_version:
                self.stdout.write(
                    self.style.WARNING(
                        f"  - Could not parse FEMB version/SN from {filename}. Skipping."
                    )
                )
                continue

            parts = filename.replace(".txt", "").split("_")
            filename_sn = parts[-1]
            if filename_sn != femb_sn:
                self.stdout.write(
                    self.style.WARNING(
                        f"  - SN in filename ({filename_sn}) does not match file ({femb_sn}). Skipping."
                    )
                )
                continue

            femb_obj = FEMB.objects.filter(serial_number=femb_sn, version=femb_version).first()

            if not femb_obj:
                new_fembs_to_create.append(
                    {"serial_number": femb_sn, "version": femb_version, "status": "new"}
                )

            for comp in components:
                model = COMPONENT_MODELS.get(comp["type"])
                if not model:
                    continue
                is_already_correct = False
                if femb_obj:
                    is_already_correct = model.objects.filter(
                        serial_number=comp["serial_number"],
                        femb=femb_obj,
                        femb_pos=comp["position"],
                    ).exists()
                if not is_already_correct:
                    components_to_update.append(
                        {
                            "femb_serial_number": femb_sn,
                            "femb_version": femb_version,
                            "type": comp["type"],
                            "serial_number": comp["serial_number"],
                            "position": comp["position"],
                        }
                    )

        # ------------------------------------------------------------------ #
        # Phase 2: collect pending repair changes                             #
        # ------------------------------------------------------------------ #

        # Build a lookup from (femb_version, femb_sn) → regular file path so
        # repair_1 can diff against the original assembly file instead of DB state.
        regular_file_by_femb = {}
        for fp in regular_files:
            v, sn, _ = parse_parts_file(fp)
            if v and sn:
                regular_file_by_femb[(v, sn)] = fp

        # Build a lookup from (femb_dir_abs, iteration) → repair file path so
        # repair_N can diff against repair_{N-1} when N > 1.
        repair_file_by_femb_iter = {}
        for fp, repair_dir, iteration in repair_files:
            femb_dir = os.path.dirname(repair_dir)
            repair_file_by_femb_iter[(femb_dir, iteration)] = fp

        repairs_to_record = []   # list of dicts describing a full repair action

        for filepath, repair_dir, iteration_number in sorted(repair_files, key=lambda x: x[2]):
            filename = os.path.basename(filepath)
            self.stdout.write(f"Processing repair file: {filepath}")

            note_path = os.path.join(repair_dir, "inspection_note.txt")
            if not os.path.isfile(note_path):
                self.stdout.write(
                    self.style.WARNING(
                        f"  - No inspection_note.txt in {repair_dir}. Skipping repair."
                    )
                )
                continue

            note = parse_inspection_note(note_path)

            femb_version, femb_sn, after_components = parse_parts_file(filepath)
            if not femb_version:
                self.stdout.write(
                    self.style.WARNING(
                        f"  - Could not parse FEMB version/SN from {filename}. Skipping."
                    )
                )
                continue

            femb_obj = FEMB.objects.filter(serial_number=femb_sn, version=femb_version).first()
            if not femb_obj:
                self.stdout.write(
                    self.style.WARNING(
                        f"  - FEMB {femb_version}/{femb_sn} not found in DB. Skipping repair."
                    )
                )
                continue

            # Skip if this repair is already recorded
            if FEMB_REPAIR.objects.filter(femb=femb_obj, iteration_number=iteration_number).exists():
                self.stdout.write(
                    f"  - Repair #{iteration_number} for FEMB {femb_sn} already recorded. Skipping."
                )
                continue

            # Determine the predecessor file to diff against:
            #   repair_1 → original assembly file for this FEMB (may be in a different batch dir)
            #   repair_N → repair_{N-1} file in the same FEMB directory
            femb_dir = os.path.dirname(repair_dir)
            if iteration_number == 1:
                predecessor_path = regular_file_by_femb.get((femb_version, femb_sn))
            else:
                predecessor_path = repair_file_by_femb_iter.get((femb_dir, iteration_number - 1))

            if not predecessor_path:
                self.stdout.write(
                    self.style.WARNING(
                        f"  - No predecessor file found for repair #{iteration_number} of "
                        f"{femb_version}/{femb_sn}. Skipping."
                    )
                )
                continue

            _, _, before_components = parse_parts_file(predecessor_path)
            removed_chips, added_chips = compute_repair_diff(before_components, after_components)

            repairs_to_record.append(
                {
                    "femb_obj": femb_obj,
                    "femb_sn": femb_sn,
                    "femb_version": femb_version,
                    "iteration_number": iteration_number,
                    "note": note,
                    "removed_chips": removed_chips,
                    "added_chips": added_chips,
                }
            )

        # ------------------------------------------------------------------ #
        # Phase 3: print summary and confirm                                  #
        # ------------------------------------------------------------------ #
        nothing_to_do = (
            not new_fembs_to_create
            and not components_to_update
            and not repairs_to_record
        )
        if nothing_to_do:
            self.stdout.write(
                self.style.SUCCESS(
                    "\nDatabase is already up-to-date. No new FEMBs, components, or repairs found."
                )
            )
            return

        self.stdout.write("\n--- Summary of Changes ---")

        if new_fembs_to_create:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\nFound {len(new_fembs_to_create)} new FEMB(s) to add:"
                )
            )
            for femb_data in new_fembs_to_create:
                self.stdout.write(
                    f"  - {femb_data['version']}/{femb_data['serial_number']}"
                )

        if components_to_update:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\nFound {len(components_to_update)} component(s) to update:"
                )
            )
            summary = {}
            for c in components_to_update:
                summary[c["type"]] = summary.get(c["type"], 0) + 1
            for comp_type, count in summary.items():
                self.stdout.write(f"  - {count} {comp_type} object(s)")

        if repairs_to_record:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\nFound {len(repairs_to_record)} repair(s) to record:"
                )
            )
            for r in repairs_to_record:
                note = r["note"]
                self.stdout.write(
                    f"  - FEMB {r['femb_version']}/{r['femb_sn']} "
                    f"repair #{r['iteration_number']} "
                    f"({note['date'] or 'no date'}, operator: {note['operator'] or 'unknown'})"
                )
                for chip in r["removed_chips"]:
                    self.stdout.write(
                        f"      REMOVE {chip['type']} {chip['serial_number']} @ pos {chip['position']}"
                    )
                for chip in r["added_chips"]:
                    self.stdout.write(
                        f"      ADD    {chip['type']} {chip['serial_number']} @ pos {chip['position']}"
                    )

        confirmation = input("\nDo you want to proceed with these changes? (yes/no): ")

        if confirmation.lower() != "yes":
            self.stdout.write("\nOperation cancelled by user.")
            return

        # ------------------------------------------------------------------ #
        # Phase 4: apply all changes in one transaction                       #
        # ------------------------------------------------------------------ #
        try:
            with transaction.atomic():
                # --- regular FEMB + component updates ---
                for femb_data in new_fembs_to_create:
                    FEMB.objects.create(
                        serial_number=femb_data["serial_number"],
                        version=femb_data["version"],
                        status=femb_data["status"],
                    )

                for comp_data in components_to_update:
                    model = COMPONENT_MODELS.get(comp_data["type"])
                    if not model:
                        continue

                    obj, created = model.objects.get_or_create(
                        serial_number=comp_data["serial_number"],
                        defaults={"status": "new"},
                    )

                    if obj.status == "on-femb" and not created:
                        self.stdout.write(
                            self.style.WARNING(
                                f"  - Skipping {comp_data['type']} {comp_data['serial_number']}"
                                f" as it is already on a FEMB."
                            )
                        )
                        continue

                    femb = FEMB.objects.get(
                        serial_number=comp_data["femb_serial_number"],
                        version=comp_data["femb_version"],
                    )
                    obj.status = "on-femb"
                    obj.femb = femb
                    obj.femb_pos = comp_data["position"]
                    obj.save()

                # --- repair records ---
                for r in repairs_to_record:
                    note = r["note"]
                    repair_obj = FEMB_REPAIR.objects.create(
                        femb=r["femb_obj"],
                        iteration_number=r["iteration_number"],
                        date=note["date"] or datetime.now(tz=timezone.utc),
                        operator=note["operator"],
                        what_was_fixed=note["what_was_fixed"],
                        comments=note["comments"],
                        batch_id=note["batch_id"],
                    )

                    for chip in r["removed_chips"]:
                        model = COMPONENT_MODELS.get(chip["type"])
                        if not model:
                            continue
                        try:
                            obj = model.objects.get(serial_number=chip["serial_number"])
                            obj.removed_at_repair = repair_obj
                            obj.femb = None
                            obj.femb_pos = ""
                            obj.status = "removed"
                            obj.save()
                        except model.DoesNotExist:
                            self.stdout.write(
                                self.style.WARNING(
                                    f"  - Removed chip {chip['type']} {chip['serial_number']}"
                                    f" not found in DB; skipping."
                                )
                            )

                    for chip in r["added_chips"]:
                        model = COMPONENT_MODELS.get(chip["type"])
                        if not model:
                            continue
                        obj, _ = model.objects.get_or_create(
                            serial_number=chip["serial_number"],
                            defaults={"status": "new"},
                        )
                        obj.femb = r["femb_obj"]
                        obj.femb_pos = chip["position"]
                        obj.installed_at_repair = repair_obj
                        obj.status = "on-femb"
                        obj.save()

            self.stdout.write(self.style.SUCCESS("\nSuccessfully updated the database."))
        except Exception as e:
            raise CommandError(f"An error occurred during database update: {e}")
