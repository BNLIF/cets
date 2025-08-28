import os
import re
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from decouple import config
from core.models import FEMB, FE, ADC, COLDATA


class Command(BaseCommand):
    help = "Scans the FEMB_OCR_DIR to find and add new FEMB serial numbers to the database."

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

        filepaths = []
        for root, _, files in os.walk(femb_ocr_dir):
            for file in files:
                if file.startswith("femb_parts_") and file.endswith(".txt"):
                    filepaths.append(os.path.join(root, file))

        if not filepaths:
            self.stdout.write(self.style.SUCCESS("No 'femb_parts_*.txt' files found."))
            return

        new_fembs_to_create = []
        components_to_update = []

        for filepath in filepaths:
            try:
                filename = os.path.basename(filepath)
                self.stdout.write(f"Processing file: {filepath}")

                # Parse FEMB info from filename
                parts = filename.replace(".txt", "").split("_")
                femb_serial_number = parts[-1]

                with open(filepath, "r") as f:
                    lines = f.readlines()

                femb_version = ""
                components = []
                for line in lines:
                    line_parts = [
                        p.strip().replace('"', "") for p in line.strip().split(",")
                    ]
                    if not line_parts or len(line_parts) < 2:
                        continue

                    raw_type = line_parts[0]
                    serial_number = line_parts[1]

                    if "FEMB" in raw_type:
                        path_parts = serial_number.split("/")
                        femb_version = path_parts[-2]
                        sn = path_parts[-1]
                        if femb_serial_number != sn:
                            self.stdout.write(
                                self.style.WARNING(
                                    f"  - Serial number in filename ({femb_serial_number}) does not match serial number in file ({sn}). Skipping file."
                                )
                            )
                            continue
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
                                {
                                    "type": comp_type,
                                    "serial_number": serial_number,
                                    "position": position,
                                }
                            )

                if not femb_version:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  - Could not find FEMB version in {filename}. Skipping file."
                        )
                    )
                    continue

                # Check if FEMB already exists
                if not FEMB.objects.filter(
                    serial_number=femb_serial_number, version=femb_version
                ).exists():
                    new_fembs_to_create.append(
                        {
                            "serial_number": femb_serial_number,
                            "version": femb_version,
                            "status": "new",
                        }
                    )

                    for comp in components:
                        components_to_update.append(
                            {
                                "femb_serial_number": femb_serial_number,
                                "femb_version": femb_version,
                                "type": comp["type"],
                                "serial_number": comp["serial_number"],
                                "position": comp["position"],
                            }
                        )
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"  - Error processing file {filepath}: {e}")
                )

        if not new_fembs_to_create and not components_to_update:
            self.stdout.write(
                self.style.SUCCESS(
                    "\nDatabase is already up-to-date. No new FEMBs or components found."
                )
            )
            return

        self.stdout.write("\n--- Summary of Changes ---")
        if new_fembs_to_create:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\nFound {len(new_fembs_to_create)} new FEMB objects to be added:"
                )
            )
            for femb_data in new_fembs_to_create:
                self.stdout.write(
                    f"  - Serial Number: {femb_data['serial_number']}, Version: {femb_data['version']}"
                )

        if components_to_update:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\nFound {len(components_to_update)} components to be updated:"
                )
            )
            # Group components by type for summary
            summary = {}
            for comp_data in components_to_update:
                summary[comp_data["type"]] = summary.get(comp_data["type"], 0) + 1

            for comp_type, count in summary.items():
                self.stdout.write(f"  - {count} {comp_type} objects")

        confirmation = input("\nDo you want to proceed with these changes? (yes/no): ")

        if confirmation.lower() == "yes":
            try:
                with transaction.atomic():
                    for femb_data in new_fembs_to_create:
                        FEMB.objects.create(
                            serial_number=femb_data["serial_number"],
                            version=femb_data["version"],
                            status=femb_data["status"],
                        )

                    for comp_data in components_to_update:
                        model = None
                        if comp_data["type"] == "FE":
                            model = FE
                        elif comp_data["type"] == "ADC":
                            model = ADC
                        elif comp_data["type"] == "COLDATA":
                            model = COLDATA

                        if model:
                            obj, created = model.objects.get_or_create(
                                serial_number=comp_data["serial_number"],
                                defaults={"status": "new"},
                            )

                            if obj.status == "on-femb" and not created:
                                self.stdout.write(
                                    self.style.WARNING(
                                        f"  - Skipping {comp_data['type']} {comp_data['serial_number']} as it is already on a FEMB."
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

                self.stdout.write(
                    self.style.SUCCESS(f"\nSuccessfully updated the database.")
                )
            except Exception as e:
                raise CommandError(f"An error occurred during database update: {e}")
        else:
            self.stdout.write("\nOperation cancelled by user.")
