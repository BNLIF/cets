import csv
from datetime import datetime
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.timezone import make_aware
from core.models import FEMB, FEMB_TEST


class Command(BaseCommand):
    help = "Loads FEMB test records from a CSV file."

    def handle(self, *args, **options):
        csv_filepath = "tmp/femb_tests.csv"

        try:
            latest_test = FEMB_TEST.objects.latest("timestamp")
            self.stdout.write(f"Latest test in DB is from: {latest_test.timestamp}")
        except FEMB_TEST.DoesNotExist:
            latest_test = None
            self.stdout.write("No existing FEMB_TEST records found in the database.")

        new_tests_to_create = []
        new_fembs_to_create = {}  # Use a dict to avoid duplicates, key=(version, sn)

        with open(csv_filepath, "r", newline="") as f:
            lines = list(csv.reader(f))
        
        header = lines[0]
        for row_values in reversed(lines[1:]):
            row = dict(zip(header, row_values))

            # timestamp,test_type,test_env,femb_version,femb_sn,report_filename
            timestamp_str = row["timestamp"]
            # The timestamp format is '2025-08-26 14:41:31'
            naive_timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
            timestamp = make_aware(naive_timestamp)

            if latest_test and timestamp <= latest_test.timestamp:
                break # Stop, we've reached tests that are already in the DB

            femb_version = row["femb_version"]
            femb_sn = row["femb_sn"]

            # Check if FEMB exists, if not, add to creation list
            if not FEMB.objects.filter(
                version=femb_version, serial_number=femb_sn
            ).exists():
                if (femb_version, femb_sn) not in new_fembs_to_create:
                    new_fembs_to_create[(femb_version, femb_sn)] = {
                        "version": femb_version,
                        "serial_number": femb_sn,
                        "status": "testing",
                    }

            new_tests_to_create.append(
                {
                    "femb_version": femb_version,
                    "femb_sn": femb_sn,
                    "timestamp": timestamp,
                    "test_type": row["test_type"],
                    "test_env": row["test_env"],
                    "report_filename": row["report_filename"],
                }
            )
        
        # Reverse the list to insert oldest first
        new_tests_to_create.reverse()

        if not new_tests_to_create and not new_fembs_to_create:
            self.stdout.write(self.style.SUCCESS("Database is already up-to-date."))
            return

        self.stdout.write("\n--- Summary of Changes ---")
        if new_fembs_to_create:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\nFound {len(new_fembs_to_create)} new FEMB objects to be added:"
                )
            )
            for femb_data in new_fembs_to_create.values():
                self.stdout.write(
                    f"  - Version: {femb_data['version']}, Serial Number: {femb_data['serial_number']}"
                )

        if new_tests_to_create:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\nFound {len(new_tests_to_create)} new FEMB_TEST records to be added."
                )
            )

        confirmation = input("\nDo you want to proceed with these changes? (yes/no): ")

        if confirmation.lower() == "yes":
            try:
                with transaction.atomic():
                    # Create FEMBs
                    created_fembs = {}
                    for (version, sn), femb_data in new_fembs_to_create.items():
                        femb = FEMB.objects.create(**femb_data)
                        created_fembs[(version, sn)] = femb

                    # Prepare FEMB_TEST objects for bulk_create
                    tests_for_bulk_create = []
                    for test_data in new_tests_to_create:
                        femb_version = test_data.pop("femb_version")
                        femb_sn = test_data.pop("femb_sn")

                        femb = created_fembs.get((femb_version, femb_sn))
                        if not femb:
                            femb = FEMB.objects.get(
                                version=femb_version, serial_number=femb_sn
                            )

                        tests_for_bulk_create.append(FEMB_TEST(femb=femb, **test_data))

                    FEMB_TEST.objects.bulk_create(tests_for_bulk_create)

                self.stdout.write(
                    self.style.SUCCESS(f"\nSuccessfully updated the database.")
                )
            except Exception as e:
                raise CommandError(f"An error occurred during database update: {e}")
        else:
            self.stdout.write("\nOperation cancelled by user.")