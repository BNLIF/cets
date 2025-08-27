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

        fes_to_create = []
        fes_to_update = []

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
                        serial_number = "_".join(parts[:timestamp_part_index]).replace("_", "-")
                        
                        try:
                            fe = FE.objects.get(serial_number=serial_number)
                            if fe.status == "on-femb" and tray_id:
                                if fe.tray_id != tray_id:
                                    fes_to_update.append({
                                        'serial_number': serial_number,
                                        'tray_id': tray_id
                                    })
                        except FE.DoesNotExist:
                            if not any(
                                f['serial_number'] == serial_number
                                for f in fes_to_create
                            ):
                                fes_to_create.append(
                                    {
                                        "serial_number": serial_number,
                                        "tray_id": tray_id,
                                        "status": "testing",  # Default status
                                    }
                                )
                except Exception:
                    # Ignore files with unexpected format
                    pass

        if not fes_to_create and not fes_to_update:
            self.stdout.write(
                self.style.SUCCESS("Database is already up-to-date. No new or updatable FEs found.")
            )
            return

        self.stdout.write("\n--- Summary of Changes ---")
        if fes_to_create:
            self.stdout.write(f"Found {len(fes_to_create)} new FE objects to be added:")
            for fe_data in fes_to_create:
                self.stdout.write(
                    f"  - Serial Number: {fe_data['serial_number']}, Tray ID: {fe_data['tray_id']}"
                )
        if fes_to_update:
            self.stdout.write(f"Found {len(fes_to_update)} FE objects to be updated:")
            for fe_data in fes_to_update:
                self.stdout.write(
                    f"  - Serial Number: {fe_data['serial_number']}, New Tray ID: {fe_data['tray_id']}"
                )

        confirmation = input(
            "\nDo you want to proceed with these changes? (yes/no): "
        )

        if confirmation.lower() == "yes":
            try:
                with transaction.atomic():
                    for fe_data in fes_to_create:
                        FE.objects.create(
                            serial_number=fe_data["serial_number"],
                            tray_id=fe_data["tray_id"],
                            status=fe_data["status"],
                        )
                    for fe_data in fes_to_update:
                        fe = FE.objects.get(serial_number=fe_data['serial_number'])
                        fe.tray_id = fe_data['tray_id']
                        fe.save()

                self.stdout.write(
                    self.style.SUCCESS(
                        f"\nSuccessfully updated the database."
                    )
                )
            except Exception as e:
                raise CommandError(f"An error occurred during database update: {e}")
        else:
            self.stdout.write("\nOperation cancelled by user.")
