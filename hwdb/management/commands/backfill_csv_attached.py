"""Stamp warm_csv_attached_at / cold_csv_attached_at for LArASIC chips that
were uploaded to PROD before those fields existed.

Heuristic (local-only — never touches HWDB):
  - Only chips with qc_tests_uploaded=True are candidates (a prior PROD upload
    already landed for them).
  - For each candidate tray, read the TrayCsvCache to see which CSVs (RT / LN
    per chip) exist under RTS_DIR today.
  - If a CSV exists for the chip+env and the timestamp is NULL, stamp it.

Trade-off named in the design discussion: if a previous PROD upload flipped
qc_tests_uploaded=True but the CSV attach silently failed (the bug we fixed in
9a650d2), this backfill will optimistically mark it attached. That's accepted;
the alternative is to re-upload every chip-with-CSV across the 12k backlog.

Idempotent — only stamps NULL fields and never clears non-NULL ones. Default
mode prints what it WOULD do; pass --apply to actually write.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import LArASIC
from hwdb.models import TrayCsvCache


class Command(BaseCommand):
    help = "Backfill warm/cold_csv_attached_at for already-uploaded chips."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true",
            help="Actually write the timestamps; default is a dry run.",
        )

    def handle(self, *args, **opts):
        apply = opts["apply"]
        now = timezone.now()

        chips = list(
            LArASIC.objects
            .filter(qc_tests_uploaded=True)
            .exclude(tray_id__isnull=True).exclude(tray_id="")
            .values("pk", "tray_id", "serial_number",
                    "warm_csv_attached_at", "cold_csv_attached_at")
        )
        tray_ids = sorted({c["tray_id"] for c in chips})
        csvs_by_tray = {
            row.tray_id: row.csvs or {}
            for row in TrayCsvCache.objects.filter(tray_id__in=tray_ids)
        }
        trays_missing_cache = [t for t in tray_ids if t not in csvs_by_tray]

        warm_pks = []
        cold_pks = []
        for c in chips:
            csvs = csvs_by_tray.get(c["tray_id"], {})
            sn = c["serial_number"]
            if c["warm_csv_attached_at"] is None and f"{sn}|RT" in csvs:
                warm_pks.append(c["pk"])
            if c["cold_csv_attached_at"] is None and f"{sn}|LN" in csvs:
                cold_pks.append(c["pk"])

        self.stdout.write(
            f"Scanned {len(chips):>5} chips across {len(tray_ids)} trays "
            f"({len(trays_missing_cache)} trays have no TrayCsvCache row — "
            f"those chips skipped; run Refresh CSV cache first if needed)."
        )
        self.stdout.write(
            f"Would stamp warm_csv_attached_at on {len(warm_pks):>5} chip(s)."
        )
        self.stdout.write(
            f"Would stamp cold_csv_attached_at on {len(cold_pks):>5} chip(s)."
        )

        if not apply:
            self.stdout.write(self.style.WARNING(
                "Dry run — pass --apply to write."
            ))
            return

        if warm_pks:
            LArASIC.objects.filter(pk__in=warm_pks).update(warm_csv_attached_at=now)
        if cold_pks:
            LArASIC.objects.filter(pk__in=cold_pks).update(cold_csv_attached_at=now)
        self.stdout.write(self.style.SUCCESS(
            f"Stamped {len(warm_pks)} RT + {len(cold_pks)} LN row(s) at {now.isoformat()}."
        ))
