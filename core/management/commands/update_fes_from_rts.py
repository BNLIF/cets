import os
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from decouple import config
from core.models import FE


class Command(BaseCommand):
    help = "Scans the RTS_DIR to find and add new FE serial numbers to the database."

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

        # --- Step 1: Parse all files and collect FE data without DB queries ---
        all_found_fes = {}
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
                        all_found_fes[serial_number] = tray_id
                except Exception:
                    # Ignore files with unexpected format
                    pass

        # --- Step 2: Query database for existing FEs ---
        all_serial_numbers = list(all_found_fes.keys())
        if not all_serial_numbers:
            self.stdout.write(self.style.SUCCESS("No valid FE files found to process."))
            return

        existing_fes_dict = FE.objects.filter(
            serial_number__in=all_serial_numbers
        ).in_bulk(field_name="serial_number")

        # --- Step 3: Determine new FEs to create and existing FEs to update ---
        fes_to_create_data = []
        fes_to_update_objects = []

        for serial_number, tray_id in all_found_fes.items():
            if serial_number not in existing_fes_dict:
                fes_to_create_data.append(
                    {
                        "serial_number": serial_number,
                        "tray_id": tray_id,
                        "status": "rts-tested",  # Default status
                    }
                )
            else:
                fe = existing_fes_dict[serial_number]
                if fe.status == "on-femb" and fe.tray_id != tray_id:
                    fe.tray_id = tray_id
                    fes_to_update_objects.append(fe)

        if not fes_to_create_data and not fes_to_update_objects:
            self.stdout.write(
                self.style.SUCCESS(
                    "\nDatabase is already up-to-date. No new or updatable FEs found."
                )
            )
            return

        # --- Step 4: Display summary and ask for confirmation ---
        self.stdout.write("\n--- Summary of Changes ---")
        if fes_to_create_data:
            self.stdout.write(
                f"\nFound {len(fes_to_create_data)} new FE objects to be added:"
            )
            for fe_data in fes_to_create_data:
                self.stdout.write(
                    f"  - Serial Number: {fe_data['serial_number']}, Tray ID: {fe_data['tray_id']}"
                )
        if fes_to_update_objects:
            self.stdout.write(
                f"\nFound {len(fes_to_update_objects)} FE objects to be updated:"
            )
            for fe in fes_to_update_objects:
                self.stdout.write(
                    f"  - Serial Number: {fe.serial_number}, New Tray ID: {fe.tray_id}"
                )

        confirmation = input("\nDo you want to proceed with these changes? (yes/no): ")

        # --- Step 5: Perform database updates ---
        if confirmation.lower() == "yes":
            try:
                with transaction.atomic():
                    if fes_to_create_data:
                        FE.objects.bulk_create(
                            [FE(**data) for data in fes_to_create_data],
                            ignore_conflicts=True,
                        )

                    if fes_to_update_objects:
                        FE.objects.bulk_update(fes_to_update_objects, ["tray_id"])

                self.stdout.write(
                    self.style.SUCCESS(f"\nSuccessfully updated the database.")
                )
            except Exception as e:
                raise CommandError(f"An error occurred during database update: {e}")
        else:
            self.stdout.write("\nOperation cancelled by user.")
