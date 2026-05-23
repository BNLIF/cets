"""Scan the new RTS batch layout and upsert LArASIC rows.

Layout under RTS_DIR:
    B###T####/Time_YYYYMMDDHHMMSS[_DUT_...]/
        RT_FE_<sn1>_..._<snN>/      -> warm-test evidence (1..8 chips)
        LN_FE_<sn1>_..._<snN>/      -> cold-test evidence (paired with RT_*)

Rules (per ~/tmp/rts/docs/adr/):
  - ADR-0003: timestamps parsed as UTC.
  - ADR-0004: a session is valid only if it contains at least one RT_* subfolder.
    Sessions with only LN_* are aborted debris; their SNs are ignored.
  - Per-chip (not batch-level) date attribution: warm_tested_at = latest Time_ts
    where this SN appears in an RT_FE_; cold_tested_at = latest Time_ts where
    this SN appears in an LN_FE_ of a valid session.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from decouple import config
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Max

from core.models import LArASIC

BATCH_RE = re.compile(r"^B\d{3,4}T\d{3,4}$")
TIME_RE = re.compile(r"^Time_(\d{14})")
SN_RE = re.compile(r"^\d{9}$")

# Batches with warm date before this cutoff are rig-qualification "test chips"
# (see ADR-0005 in the rts report tool); skip them on import and delete any
# matching rows already in the DB. On-femb chips are exempt from the delete.
START_MONTH = datetime(2025, 7, 1, tzinfo=timezone.utc)


def normalize_sn(raw: str) -> str:
    # "002004605" -> "002-04605" (raw suffix is 6 digits, stored as 5 digits).
    prefix = raw[:3]
    suffix = str(int(raw[3:])).zfill(5)
    return f"{prefix}-{suffix}"


def parse_time_folder(name: str) -> datetime | None:
    m = TIME_RE.match(name)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def parse_sn_folder(name: str, prefix: str) -> list[str]:
    """Parse SNs from an RT_FE_/LN_FE_ folder name.

    Accepts 1..8 9-digit parts after the prefix. Returns normalized SNs
    ("002-04605"). Returns [] if the folder yields zero valid SNs (caller
    treats this as a skipped folder).
    """
    if not name.startswith(prefix):
        return []
    rest = name[len(prefix):]
    parts = rest.split("_") if rest else []
    return [normalize_sn(p) for p in parts if SN_RE.match(p)]


@dataclass
class ChipScan:
    serial_number: str
    warm_ts: datetime | None = None
    cold_ts: datetime | None = None
    warm_batch_id: str = ""

    def credit_warm(self, ts: datetime, batch_id: str) -> None:
        if self.warm_ts is None or ts > self.warm_ts:
            self.warm_ts = ts
            self.warm_batch_id = batch_id

    def credit_cold(self, ts: datetime) -> None:
        if self.cold_ts is None or ts > self.cold_ts:
            self.cold_ts = ts


@dataclass
class BatchScan:
    batch_id: str
    warm_date: datetime | None = None
    cold_date: datetime | None = None
    chips: dict[str, ChipScan] = field(default_factory=dict)
    skipped_folders: list[str] = field(default_factory=list)
    valid_session_count: int = 0


def scan_batch(batch_dir: Path, cutoff: datetime | None = None) -> BatchScan:
    batch = BatchScan(batch_id=batch_dir.name)
    for session in batch_dir.iterdir():
        if not session.is_dir():
            continue
        ts = parse_time_folder(session.name)
        if ts is None:
            continue
        if cutoff is not None and ts <= cutoff:
            continue
        try:
            sub_names = [s.name for s in session.iterdir() if s.is_dir()]
        except OSError:
            continue
        has_rt = any(n.startswith("RT_") for n in sub_names)
        if not has_rt:
            continue  # ADR-0004: aborted session
        batch.valid_session_count += 1
        if batch.warm_date is None or ts > batch.warm_date:
            batch.warm_date = ts
        for sub_name in sub_names:
            if sub_name.startswith("RT_FE_"):
                sns = parse_sn_folder(sub_name, "RT_FE_")
                if not sns:
                    batch.skipped_folders.append(str(session / sub_name))
                    continue
                for sn in sns:
                    chip = batch.chips.setdefault(sn, ChipScan(sn))
                    chip.credit_warm(ts, batch.batch_id)
            elif sub_name.startswith("LN_FE_"):
                sns = parse_sn_folder(sub_name, "LN_FE_")
                if not sns:
                    batch.skipped_folders.append(str(session / sub_name))
                    continue
                if batch.cold_date is None or ts > batch.cold_date:
                    batch.cold_date = ts
                for sn in sns:
                    chip = batch.chips.setdefault(sn, ChipScan(sn))
                    chip.credit_cold(ts)
    return batch


def merge_chip(into: ChipScan, other: ChipScan) -> None:
    if other.warm_ts is not None:
        into.credit_warm(other.warm_ts, other.warm_batch_id)
    if other.cold_ts is not None:
        into.credit_cold(other.cold_ts)


class Command(BaseCommand):
    help = "Scan RTS_DIR (new batch layout) and upsert LArASIC rows for every chip found."

    def add_arguments(self, parser):
        parser.add_argument(
            "--data-dir",
            type=Path,
            default=None,
            help="Override RTS_DIR. Defaults to the RTS_DIR env value.",
        )
        parser.add_argument(
            "--batch",
            type=str,
            default=None,
            help="Restrict scan to a single batch (e.g. B005T0017).",
        )
        parser.add_argument(
            "--commit",
            action="store_true",
            help="Skip the interactive prompt and write directly.",
        )
        parser.add_argument(
            "--since-db",
            action="store_true",
            help=(
                "Incremental mode: skip batch folders whose mtime is not newer "
                "than max(warm_tested_at, cold_tested_at) in the DB, and skip "
                "sessions whose Time_ name is not newer than that cutoff. "
                "Intended for the daily cron."
            ),
        )

    def handle(self, *args, **options):
        data_dir: Path = options["data_dir"] or Path(self._rts_dir())
        if not data_dir.is_dir():
            raise CommandError(f"data dir not found or not a directory: {data_dir}")

        batch_filter = options["batch"]
        commit_flag: bool = options["commit"]
        since_db: bool = options["since_db"]

        cutoff_dt: datetime | None = None
        if since_db:
            agg = LArASIC.objects.aggregate(
                w=Max("warm_tested_at"), c=Max("cold_tested_at")
            )
            candidates = [v for v in (agg["w"], agg["c"]) if v is not None]
            if candidates:
                cutoff_dt = max(candidates)
                self.stdout.write(
                    f"Incremental mode: cutoff = {cutoff_dt.isoformat()}"
                )
            else:
                self.stdout.write("Incremental mode: DB has no timestamps; full scan.")
        cutoff_epoch = cutoff_dt.timestamp() if cutoff_dt else None

        batch_dirs: list[Path] = []
        skipped_by_mtime = 0
        with os.scandir(data_dir) as it:
            for entry in it:
                if not entry.is_dir() or not BATCH_RE.match(entry.name):
                    continue
                if batch_filter is not None and entry.name != batch_filter:
                    continue
                if cutoff_epoch is not None and entry.stat().st_mtime <= cutoff_epoch:
                    skipped_by_mtime += 1
                    continue
                batch_dirs.append(Path(entry.path))
        batch_dirs.sort()
        if cutoff_epoch is not None:
            self.stdout.write(
                f"Incremental mode: {skipped_by_mtime} batch folder(s) "
                f"unchanged since cutoff; {len(batch_dirs)} to scan."
            )
        if batch_filter and not batch_dirs:
            raise CommandError(f"batch {batch_filter} not found under {data_dir}")

        all_chips: dict[str, ChipScan] = {}
        per_batch_summary: list[dict] = []
        total_skipped_folders: list[str] = []
        batches_with_no_valid_session: list[str] = []
        batches_pre_cutoff: list[str] = []

        total = len(batch_dirs)
        for i, batch_dir in enumerate(batch_dirs, start=1):
            batch = scan_batch(batch_dir, cutoff=cutoff_dt)
            warm_str = batch.warm_date.strftime("%Y-%m-%d") if batch.warm_date else "-"
            cold_str = batch.cold_date.strftime("%Y-%m-%d") if batch.cold_date else "-"
            tag = ""
            if batch.warm_date is not None and batch.warm_date < START_MONTH:
                tag = "  [pre-cutoff, skipped]"
            self.stdout.write(
                f"[{i:03d}/{total:03d}] {batch.batch_id}  "
                f"{len(batch.chips):3d} chips  warm={warm_str} cold={cold_str}{tag}"
            )
            if batch.valid_session_count == 0:
                batches_with_no_valid_session.append(batch.batch_id)
                continue
            if batch.warm_date is not None and batch.warm_date < START_MONTH:
                batches_pre_cutoff.append(batch.batch_id)
                continue
            for sn, chip in batch.chips.items():
                merged = all_chips.setdefault(sn, ChipScan(sn))
                merge_chip(merged, chip)
            total_skipped_folders.extend(batch.skipped_folders)
            per_batch_summary.append({
                "batch_id": batch.batch_id,
                "warm": warm_str,
                "cold": cold_str,
                "chips": len(batch.chips),
                "skipped": len(batch.skipped_folders),
            })

        # Pre-cutoff rows already in the DB (e.g. from earlier runs of this
        # command before the cutoff was added) — delete them on commit unless
        # they're on a FEMB (lifecycle fact we must not erase).
        to_delete_qs = LArASIC.objects.filter(
            warm_tested_at__lt=START_MONTH
        ).exclude(status="on-femb")
        to_delete_count = to_delete_qs.count()

        if not all_chips and to_delete_count == 0:
            self.stdout.write(self.style.WARNING("No valid chip SNs found. Nothing to do."))
            return

        existing = LArASIC.objects.filter(
            serial_number__in=list(all_chips.keys())
        ).in_bulk(field_name="serial_number")

        new_count = 0
        updated_count = 0
        per_batch_new: dict[str, int] = {}
        per_batch_updated: dict[str, int] = {}

        to_create: list[LArASIC] = []
        to_update: list[LArASIC] = []

        for sn, chip in all_chips.items():
            warm_bid = chip.warm_batch_id
            if sn in existing:
                obj = existing[sn]
                obj.tray_id = warm_bid
                obj.warm_tested_at = chip.warm_ts
                obj.cold_tested_at = chip.cold_ts
                if obj.status != "on-femb":
                    obj.status = "rts-tested"
                to_update.append(obj)
                updated_count += 1
                per_batch_updated[warm_bid] = per_batch_updated.get(warm_bid, 0) + 1
            else:
                to_create.append(LArASIC(
                    serial_number=sn,
                    status="rts-tested",
                    tray_id=warm_bid,
                    warm_tested_at=chip.warm_ts,
                    cold_tested_at=chip.cold_ts,
                ))
                new_count += 1
                per_batch_new[warm_bid] = per_batch_new.get(warm_bid, 0) + 1

        self.stdout.write("")
        self.stdout.write("--- Summary ---")
        header = f"{'batch_id':<12} {'warm':<11} {'cold':<11} {'chips':>6} {'new':>6} {'updated':>8} {'skipped':>8}"
        self.stdout.write(header)
        self.stdout.write("-" * len(header))
        for row in per_batch_summary:
            bid = row["batch_id"]
            self.stdout.write(
                f"{bid:<12} {row['warm']:<11} {row['cold']:<11} "
                f"{row['chips']:>6d} {per_batch_new.get(bid, 0):>6d} "
                f"{per_batch_updated.get(bid, 0):>8d} {row['skipped']:>8d}"
            )
        self.stdout.write("-" * len(header))
        self.stdout.write(
            f"Totals: {len(per_batch_summary)} batches, "
            f"{len(all_chips)} chips ({new_count} new, {updated_count} updated, "
            f"{to_delete_count} to delete as pre-{START_MONTH.strftime('%Y-%m')})"
        )
        if batches_pre_cutoff:
            self.stdout.write(
                f"\nSkipped {len(batches_pre_cutoff)} batches with warm date before "
                f"{START_MONTH.strftime('%Y-%m')} (rig-qualification test chips): "
                + ", ".join(batches_pre_cutoff)
            )
        if to_delete_count:
            self.stdout.write(
                f"\nWill delete {to_delete_count} pre-cutoff LArASIC rows already in DB:"
            )
            for c in to_delete_qs.order_by("serial_number"):
                self.stdout.write(f"  - {c.serial_number}  (warm={c.warm_tested_at.date()})")
        if batches_with_no_valid_session:
            self.stdout.write(
                f"\nSkipped {len(batches_with_no_valid_session)} batches with no valid RT_ sessions: "
                + ", ".join(batches_with_no_valid_session)
            )
        if total_skipped_folders:
            self.stdout.write(f"\nSkipped {len(total_skipped_folders)} malformed RT_FE_/LN_FE_ folders:")
            for p in total_skipped_folders:
                self.stdout.write(f"  - {p}")

        if not commit_flag:
            ans = input("\ncommit? (yes/no): ").strip().lower()
            if ans != "yes":
                self.stdout.write("Aborted; no DB writes.")
                return

        with transaction.atomic():
            if to_create:
                LArASIC.objects.bulk_create(to_create)
            if to_update:
                LArASIC.objects.bulk_update(
                    to_update,
                    ["tray_id", "warm_tested_at", "cold_tested_at", "status"],
                )
            deleted = 0
            if to_delete_count:
                deleted, _ = to_delete_qs.delete()
        self.stdout.write(self.style.SUCCESS(
            f"Wrote {new_count} new and {updated_count} updated LArASIC rows; "
            f"deleted {deleted} pre-cutoff rows."
        ))

    @staticmethod
    def _rts_dir() -> str:
        try:
            return config("RTS_DIR")
        except Exception as e:
            raise CommandError(f"RTS_DIR not configured: {e}")
