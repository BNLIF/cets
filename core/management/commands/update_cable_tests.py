import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

from decouple import config
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.models import CABLE, CABLE_TEST


class Command(BaseCommand):
    help = "Update CABLE tests from report files."

    def add_arguments(self, parser):
        parser.add_argument(
            "--silent",
            action="store_true",
            help="Update silently without asking for confirmation.",
        )

    def handle(self, *args, **options):
        cable_qc_dir = config("CABLE_QC_DIR", default=None)
        if not cable_qc_dir or not os.path.isdir(cable_qc_dir):
            self.stdout.write(
                self.style.ERROR(
                    f"CABLE_QC_DIR '{cable_qc_dir}' is not a valid directory. Please set it in your .env file."
                )
            )
            return

        touch_file = Path("tmp/TOUCH_CABLETEST_DB_UPDATE.txt")
        
        # Create tmp directory if it doesn't exist
        touch_file.parent.mkdir(parents=True, exist_ok=True)
        if not touch_file.exists():
            touch_file.touch()

        cmd = [
            "find",
            cable_qc_dir,
            "-type",
            "f",
            "-newer",
            str(touch_file),
            "-name",
            "report*.html",
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            self.stdout.write(self.style.ERROR(f"Error finding files: {result.stderr}"))
            return

        files = result.stdout.strip().split("\n")
        if not files or not files[0]:
            self.stdout.write(self.style.SUCCESS("No new test reports found."))
            return

        self.stdout.write(f"Found {len(files)} new report files.")

        new_tests = []
        for file_path in files:
            test_data = None
            relative_path = os.path.relpath(file_path, cable_qc_dir)
            if file_path.endswith(".html"):
                test_data = self._parse_html_path(relative_path)

            if test_data:
                cable, created = CABLE.objects.get_or_create(
                    serial_number=test_data["serial_number"],
                    defaults={"batch_number": test_data["batch_number"]},
                )
                
                # If cable exists but batch number is different (or default 0), update it?
                # For now, we trust the report or keep existing. 
                # If created=False and batch_number is 0, maybe update it?
                if not created and cable.batch_number == 0 and test_data["batch_number"] != 0:
                     cable.batch_number = test_data["batch_number"]
                     cable.save()

                if created:
                    self.stdout.write(f"Created new CABLE: {cable}")

                if not CABLE_TEST.objects.filter(
                    cable=cable,
                    timestamp=test_data["timestamp"]
                ).exists():
                    new_tests.append(
                        CABLE_TEST(
                            cable=cable,
                            timestamp=test_data["timestamp"],
                            test_type=test_data["test_type"],
                            test_env=test_data["test_env"],
                            report_filename=relative_path,
                            site=test_data["site"],
                            status=test_data.get("status", ""),
                        )
                    )

        if not new_tests:
            self.stdout.write(self.style.SUCCESS("No new unique tests to add."))
            touch_file.touch()
            return

        self.stdout.write(
            self.style.WARNING(f"\nFound {len(new_tests)} new tests to be added:")
        )
        for test in new_tests:
            self.stdout.write(
                f"  - {test.cable}, {test.timestamp}, {test.test_type}, {test.test_env}, status: {test.status}"
            )

        if not options["silent"]:
            confirm = input("\nDo you want to update the database? (yes/no) [yes]: ")
            if confirm.lower() not in ["yes", "y", ""]:
                self.stdout.write(self.style.ERROR("Database update cancelled."))
                return

        with transaction.atomic():
            CABLE_TEST.objects.bulk_create(new_tests)

        touch_file.touch()
        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully updated database with {len(new_tests)} new tests."
            )
        )

    def _parse_html_path(self, relative_path):
        # Path format:
        # {site}/VD_batch{batch}/{serial}/Report_Time_{YYYY}_{MMDD}_{HH}_{MM}_{SS}_CTS_{env}_{type}/report_Cable_{serial}_Slot{slot}_{status}_{env}.html
        
        pattern = re.compile(
            r"(?P<site>\w+)/"
            r"VD_batch_?(?P<batch_number>\d+)/"
            r"(?P<serial_number>[\w-]+)/"
            r"Report_Time_(?P<year>\d{4})_(?P<month>\d{2})(?P<day>\d{2})_"
            r"(?P<hour>\d{2})_(?P<minute>\d{2})_(?P<second>\d{2})_"
            r"CTS_(?P<test_env>LN|RT)_(?P<test_type>QC|CHK)/"
            r"report_Cable_(?P<serial_number_file>[\w-]+)_Slot\d+_(?P<status>[PF]).*\.html",
            re.IGNORECASE
        )

        match = pattern.search(relative_path)
        if not match:
            self.stdout.write(
                self.style.NOTICE(f"Could not parse path: {relative_path}")
            )
            return None

        data = match.groupdict()
        sn = data["serial_number"]
        sn_file = data["serial_number_file"]

        # Verify serial numbers match (allowing for common 'H' typos in filename)
        is_match = (sn == sn_file)
        if not is_match:
            # Check for missing 'H' or extra 'H' typo in the filename
            if (sn.startswith("H") and sn_file == sn[1:]) or (sn_file == "H" + sn):
                is_match = True

        if not is_match:
            self.stdout.write(
                self.style.NOTICE(f"Serial number mismatch in path: {sn} vs {sn_file}")
            )
            return None

        try:
            dt = datetime(
                int(data["year"]),
                int(data["month"]),
                int(data["day"]),
                int(data["hour"]),
                int(data["minute"]),
                int(data["second"]),
            )
            timestamp = timezone.make_aware(dt)
        except (ValueError, KeyError):
            return None

        status_map = {"P": "pass", "F": "fail"}

        return {
            "timestamp": timestamp,
            "site": data["site"],
            "test_env": data["test_env"],
            "test_type": data["test_type"],
            "batch_number": int(data["batch_number"]),
            "serial_number": data["serial_number"],
            "status": status_map.get(data["status"].upper(), ""),
        }
