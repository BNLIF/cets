import os
import re
import subprocess
from datetime import datetime

from decouple import config
from django.core.management.base import BaseCommand
from django.db import transaction
from pathlib import Path
from django.utils import timezone

from core.models import FEMB, FEMB_TEST


class Command(BaseCommand):
    help = "Update FEMB tests from report files."

    def add_arguments(self, parser):
        parser.add_argument(
            "--silent",
            action="store_true",
            help="Update silently without asking for confirmation.",
        )

    def handle(self, *args, **options):
        femb_qc_dir = config("FEMB_QC_DIR", default=None)
        if not femb_qc_dir or not os.path.isdir(femb_qc_dir):
            self.stdout.write(
                self.style.ERROR(
                    f"FEMB_QC_DIR '{femb_qc_dir}' is not a valid directory. Please set it in your .env file."
                )
            )
            return

        touch_file = Path("tmp/TOUCH_FEMBTEST_DB_UPDATE.txt")

        # self.stdout.write(
        #     f"Finding new report files in {femb_qc_dir} newer than {touch_file}..."
        # )

        cmd = [
            "find",
            femb_qc_dir,
            "-type",
            "f",
            "-newer",
            str(touch_file),
            "(",
            "-name",
            "Final*.md",
            "-o",
            "-name",
            "report*.html",
            ")",
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
            relative_path = os.path.relpath(file_path, femb_qc_dir)
            if file_path.endswith(".md"):
                test_data = self._parse_md_path(relative_path, femb_qc_dir)
            elif file_path.endswith(".html"):
                test_data = self._parse_html_path(relative_path, femb_qc_dir)

            if test_data:
                femb, created = FEMB.objects.get_or_create(
                    version=test_data["version"],
                    serial_number=test_data["serial_number"],
                )
                if created:
                    self.stdout.write(f"Created new FEMB: {femb}")

                if not FEMB_TEST.objects.filter(
                    femb=femb, timestamp=test_data["timestamp"]
                ).exists():
                    new_tests.append(
                        FEMB_TEST(
                            femb=femb,
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
                f"  - {test.femb}, {test.timestamp}, {test.test_type}, {test.test_env}, status: {test.status}"
            )

        if not options["silent"]:
            confirm = input("\nDo you want to update the database? (yes/no) [yes]: ")
            if confirm.lower() not in ["yes", "y", ""]:
                self.stdout.write(self.style.ERROR("Database update cancelled."))
                return

        with transaction.atomic():
            FEMB_TEST.objects.bulk_create(new_tests)

        touch_file.touch()
        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully updated database with {len(new_tests)} new tests."
            )
        )

    def _parse_md_path(self, file_path, base_dir):
        relative_path = os.path.relpath(file_path, base_dir)

        pattern = re.compile(
            r"(?P<site>\w+)/"
            r"Time_(?P<year>\d{4})_(?P<month>\d{2})/"
            r"(?P<day>\d{2})_(?P<hour>\d{2})_(?P<minute>\d{2})_(?P<second>\d{2})_.*?"
            r"_(?P<test_env>LN|RT)_"
            r"(?P<test_type>QC|CHK)/"
            r".*?"
            r"Final_Report_FEMB_BNL.*?_FEMB_(?P<version>[\w-]+)_(?P<serial_number>\d+)_.*\.md"
        )

        match = pattern.search(relative_path)
        if not match:
            self.stdout.write(
                self.style.NOTICE(f"Could not parse QC path: {file_path}")
            )
            return None

        data = match.groupdict()

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

        return {
            "timestamp": timestamp,
            "site": data["site"],
            "test_env": data["test_env"],
            "test_type": data["test_type"],
            "version": data["version"],
            "serial_number": data["serial_number"].zfill(5),
        }

    def _parse_html_path(self, file_path, base_dir):
        relative_path = os.path.relpath(file_path, base_dir)

        pattern = re.compile(
            r"(?P<site>\w+)/"
            r"Time_(?P<year>\d{4})_(?P<month>\d{2})/"
            r"(?P<day>\d{2})_(?P<hour>\d{2})_(?P<minute>\d{2})_(?P<second>\d{2})_.*?"
            r"_(?P<test_env>LN|RT)_"
            r"(?P<test_type>CHK)/"
            r"Report/.*?"
            r"report_FEMB_BNL.*?_FEMB_(?P<version>[\w-]+)_(?P<serial_number>\d+)_.*?_(?P<status>[PF])\.html"
        )

        match = pattern.search(relative_path)
        if not match:
            self.stdout.write(
                self.style.NOTICE(f"Could not parse CHK path: {file_path}")
            )
            return None

        data = match.groupdict()

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
            "version": data["version"],
            "serial_number": data["serial_number"].zfill(5),
            "status": status_map.get(data["status"], ""),
        }
