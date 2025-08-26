import os
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from decouple import config
from core.models import FE

class Command(BaseCommand):
    help = 'Scans the RTS_DIR to find and add new FE serial numbers to the database.'

    def handle(self, *args, **options):
        try:
            rts_dir = config('RTS_DIR')
        except Exception as e:
            raise CommandError(f"Configuration for RTS_DIR not found. Error: {e}")

        if not os.path.isdir(rts_dir):
            raise CommandError(f"RTS_DIR '{rts_dir}' does not exist or is not a directory.")

        self.stdout.write(f"Scanning directory: {rts_dir}")

        try:
            tray_dirs = [d for d in os.listdir(rts_dir) if os.path.isdir(os.path.join(rts_dir, d))]
        except OSError as e:
            raise CommandError(f"Could not read directories in '{rts_dir}'. Error: {e}")

        new_fes_to_create = []
        existing_sns = set(FE.objects.values_list('serial_number', flat=True))

        for tray_id in tray_dirs:
            results_path = os.path.join(rts_dir, tray_id, 'results')
            if not os.path.isdir(results_path):
                self.stdout.write(self.style.WARNING(f"  - No 'results' sub-directory in '{tray_id}', skipping."))
                continue

            try:
                filenames = os.listdir(results_path)
            except OSError as e:
                self.stdout.write(self.style.ERROR(f"Could not read files in '{results_path}'. Error: {e}"))
                continue

            for filename in filenames:
                if not filename.endswith('.csv'):
                    continue
                
                try:
                    # Assuming serial number is everything before the first long number (timestamp)
                    parts = filename.split('_')
                    timestamp_part_index = -1
                    for i, part in enumerate(parts):
                        if len(part) == 14 and part.isdigit():
                            timestamp_part_index = i
                            break
                    
                    if timestamp_part_index != -1:
                        serial_number = '_'.join(parts[:timestamp_part_index])
                        if serial_number and serial_number not in existing_sns:
                            # Avoid adding duplicates from the same run
                            if not any(fe['serial_number'] == serial_number for fe in new_fes_to_create):
                                new_fes_to_create.append({
                                    'serial_number': serial_number,
                                    'tray_id': tray_id,
                                    'status': 'new' # Default status
                                })
                except Exception:
                    # Ignore files with unexpected format
                    pass

        if not new_fes_to_create:
            self.stdout.write(self.style.SUCCESS("Database is already up-to-date. No new FEs found."))
            return

        self.stdout.write("\n--- Summary of Changes ---")
        self.stdout.write(f"Found {len(new_fes_to_create)} new FE objects to be added:")
        for fe_data in new_fes_to_create:
            self.stdout.write(f"  - Serial Number: {fe_data['serial_number']}, Tray ID: {fe_data['tray_id']}")

        confirmation = input("\nDo you want to proceed with adding these objects? (yes/no): ")

        if confirmation.lower() == 'yes':
            try:
                with transaction.atomic():
                    for fe_data in new_fes_to_create:
                        FE.objects.create(
                            serial_number=fe_data['serial_number'],
                            tray_id=fe_data['tray_id'],
                            status=fe_data['status']
                        )
                self.stdout.write(self.style.SUCCESS(f"\nSuccessfully added {len(new_fes_to_create)} new FE objects to the database."))
            except Exception as e:
                raise CommandError(f"An error occurred during database update: {e}")
        else:
            self.stdout.write("\nOperation cancelled by user.")
