import os
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from decouple import config
from core.models import LArASIC


class Command(BaseCommand):
    help = "Scans the RTS_DIR to find and add new LArASIC serial numbers to the database."

    def handle(self, *args, **options):
        try:
            rts_dir = config("RTS_DIR")
        except Exception as e:
            raise CommandError(f"Configuration for RTS_DIR not found. Error: {e}")

        if not os.path.isdir(rts_dir):
            raise CommandError(
                f"RTS_DIR '{rts_dir}' does not exist or is not a directory."
            )

        self.stdout.write(f"Scanning directory: {rts_dir}")

        try:
            tray_dirs = [
                d
                for d in os.listdir(rts_dir)
                if os.path.isdir(os.path.join(rts_dir, d))
            ]
        except OSError as e:
            raise CommandError(f"Could not read directories in '{rts_dir}'. Error: {e}")

        # --- Step 1: Parse all files and collect chip data without DB queries ---
        all_found_chips = {}
        for tray_id in tray_dirs:
            results_path = os.path.join(rts_dir, tray_id, "results")
            if not os.path.isdir(results_path):
                self.stdout.write(
                    self.style.WARNING(
                        f"  - No 'results' sub-directory in '{tray_id}', skipping."
                    )
                )
                continue

            try:
                filenames = os.listdir(results_path)
            except OSError as e:
                self.stdout.write(
                    self.style.ERROR(
                        f"Could not read files in '{results_path}'. Error: {e}"
                    )
                )
                continue

            for filename in filenames:
                if not filename.endswith(".csv"):
                    continue

                try:
                    # Assuming serial number is everything before the first long number (timestamp)
                    parts = filename.split("_")
                    timestamp_part_index = -1
                    for i, part in enumerate(parts):
                        if len(part) == 14 and part.isdigit():
                            timestamp_part_index = i
                            break

                    if timestamp_part_index != -1:
                        serial_number = "_".join(parts[:timestamp_part_index]).replace(
                            "_", "-"
                        )
                        all_found_chips[serial_number] = tray_id
                except Exception:
                    # Ignore files with unexpected format
                    pass

        # --- Step 2: Query database for existing LArASICs ---
        all_serial_numbers = list(all_found_chips.keys())
        if not all_serial_numbers:
            self.stdout.write(self.style.SUCCESS("No valid LArASIC files found to process."))
            return

        existing_chips_dict = LArASIC.objects.filter(
            serial_number__in=all_serial_numbers
        ).in_bulk(field_name="serial_number")

        # --- Step 3: Determine new LArASICs to create and existing ones to update ---
        chips_to_create_data = []
        chips_to_update_objects = []

        for serial_number, tray_id in all_found_chips.items():
            if serial_number not in existing_chips_dict:
                chips_to_create_data.append(
                    {
                        "serial_number": serial_number,
                        "tray_id": tray_id,
                        "status": "rts-tested",  # Default status
                    }
                )
            else:
                chip = existing_chips_dict[serial_number]
                if chip.status == "on-femb" and chip.tray_id != tray_id:
                    chip.tray_id = tray_id
                    chips_to_update_objects.append(chip)

        if not chips_to_create_data and not chips_to_update_objects:
            self.stdout.write(
                self.style.SUCCESS(
                    "\nDatabase is already up-to-date. No new or updatable LArASICs found."
                )
            )
            return

        # --- Step 4: Display summary and ask for confirmation ---
        self.stdout.write("\n--- Summary of Changes ---")
        if chips_to_create_data:
            self.stdout.write(
                f"\nFound {len(chips_to_create_data)} new LArASIC objects to be added:"
            )
            for chip_data in chips_to_create_data:
                self.stdout.write(
                    f"  - Serial Number: {chip_data['serial_number']}, Tray ID: {chip_data['tray_id']}"
                )
        if chips_to_update_objects:
            self.stdout.write(
                f"\nFound {len(chips_to_update_objects)} LArASIC objects to be updated:"
            )
            for chip in chips_to_update_objects:
                self.stdout.write(
                    f"  - Serial Number: {chip.serial_number}, New Tray ID: {chip.tray_id}"
                )

        confirmation = input("\nDo you want to proceed with these changes? (yes/no): ")

        # --- Step 5: Perform database updates ---
        if confirmation.lower() == "yes":
            try:
                with transaction.atomic():
                    if chips_to_create_data:
                        LArASIC.objects.bulk_create(
                            [LArASIC(**data) for data in chips_to_create_data],
                            ignore_conflicts=True,
                        )

                    if chips_to_update_objects:
                        LArASIC.objects.bulk_update(chips_to_update_objects, ["tray_id"])

                self.stdout.write(
                    self.style.SUCCESS(f"\nSuccessfully updated the database.")
                )
            except Exception as e:
                raise CommandError(f"An error occurred during database update: {e}")
        else:
            self.stdout.write("\nOperation cancelled by user.")
