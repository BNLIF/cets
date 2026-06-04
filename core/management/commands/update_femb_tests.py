import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

from decouple import config
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.models import FEMB, FembTest


# Local (gitignored) file listing known-bad report paths to skip. Lines
# ending in "/" are treated as prefixes; other lines are exact relative
# paths under FEMB_QC_DIR. Blank lines and "#" comments are ignored.
IGNORE_FILE = Path("tmp/femb_test_ignore.txt")

# Verdict header near the top of a QC Final_Report: green "PASS ... Quality
# Control", red "fail ... the Quality Control tests", or dark "Quality
# Control in Test" (run incomplete — no verdict, stays blank).
QC_VERDICT_RE = re.compile(r"(?P<passed>PASS\s+Quality Control)|faild?\s+the Quality Control")


def _qc_status_from_report(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            head = f.read(2048)
    except OSError:
        return ""
    match = QC_VERDICT_RE.search(head)
    if not match:
        return ""
    return "pass" if match.group("passed") else "fail"


def _load_ignore_file(path):
    prefixes = []
    exact = set()
    if not path.is_file():
        return tuple(prefixes), frozenset(exact)
    for raw in path.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.endswith("/"):
            prefixes.append(line)
        else:
            exact.add(line)
    return tuple(prefixes), frozenset(exact)


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

        ignored_prefixes, ignored_paths = _load_ignore_file(IGNORE_FILE)

        # Full scan: rsync preserves source mtimes, so newly-mirrored files
        # can have older mtimes than any local marker. Dedup happens below
        # via (femb, timestamp) DB lookup. Scan is local disk, ~0.15s.
        cmd = [
            "find",
            femb_qc_dir,
            "-type",
            "f",
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
            self.stdout.write(self.style.SUCCESS("No test reports found."))
            return

        self.stdout.write(f"Scanning {len(files)} report files.")

        new_tests = []
        updated_tests = []
        ignored_count = 0
        for file_path in files:
            test_data = None
            relative_path = os.path.relpath(file_path, femb_qc_dir)
            if relative_path.startswith(ignored_prefixes) or relative_path in ignored_paths:
                ignored_count += 1
                continue
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

                existing = FembTest.objects.filter(
                    femb=femb, timestamp=test_data["timestamp"]
                ).first()
                if existing is None:
                    new_tests.append(
                        FembTest(
                            femb=femb,
                            timestamp=test_data["timestamp"],
                            test_type=test_data["test_type"],
                            test_env=test_data["test_env"],
                            report_filename=relative_path,
                            site=test_data["site"],
                            status=test_data.get("status", ""),
                        )
                    )
                else:
                    # Backfill: status parsing was added after many rows were
                    # imported (QC verdicts come from the report header).
                    status = test_data.get("status", "")
                    if status and existing.status != status:
                        existing.status = status
                        updated_tests.append(existing)

        if ignored_count:
            self.stdout.write(
                f"Skipped {ignored_count} file(s) matching ignored path prefixes."
            )

        if not new_tests and not updated_tests:
            self.stdout.write(self.style.SUCCESS("No new unique tests to add."))
            return

        if new_tests:
            self.stdout.write(
                self.style.WARNING(f"\nFound {len(new_tests)} new tests to be added:")
            )
            for test in new_tests:
                self.stdout.write(
                    f"  - {test.femb}, {test.timestamp}, {test.test_type}, {test.test_env}, status: {test.status}"
                )
        if updated_tests:
            self.stdout.write(
                self.style.WARNING(
                    f"\nFound {len(updated_tests)} existing tests whose status will be backfilled."
                )
            )

        if not options["silent"]:
            confirm = input("\nDo you want to update the database? (yes/no) [yes]: ")
            if confirm.lower() not in ["yes", "y", ""]:
                self.stdout.write(self.style.ERROR("Database update cancelled."))
                return

        with transaction.atomic():
            FembTest.objects.bulk_create(new_tests)
            FembTest.objects.bulk_update(updated_tests, ["status"])

        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully updated database with {len(new_tests)} new tests"
                f" and {len(updated_tests)} status backfills."
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
            # Version is the BNL FEMB pattern (e.g. IO-1865-1J / I0-1865-1K).
            # Serial follows, optionally separated by "_" or "-", or with no
            # separator at all (uploads vary). 4-digit serials get zero-padded
            # to 5 by .zfill(5) below.
            r"Final_Report_FEMB_+BNL.*?_FEMB_(?P<version>I[O0]-\d{4}-\d[A-Z])[-_]?(?P<serial_number>\d{4,5})_.*\.md"
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
            "status": _qc_status_from_report(os.path.join(base_dir, file_path)),
        }

    def _parse_html_path(self, file_path, base_dir):
        relative_path = os.path.relpath(file_path, base_dir)

        pattern = re.compile(
            r"(?P<site>\w+)/"
            r"Time_(?P<year>\d{4})_(?P<month>\d{2})/"
            r"(?P<day>\d{2})_(?P<hour>\d{2})_(?P<minute>\d{2})_(?P<second>\d{2})_.*?"
            r"_(?P<test_env>LN|RT)_"
            r"(?:last_)?"  # optional "last_" marks a re-check of the same FEMB pair
            r"(?P<test_type>CHK)/"
            r"Report/.*?"
            # See note on version/serial format in _parse_md_path.
            r"report_FEMB_+BNL.*?_FEMB_(?P<version>I[O0]-\d{4}-\d[A-Z])[-_]?(?P<serial_number>\d{4,5})_.*?_(?P<status>[PF])\.html"
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
