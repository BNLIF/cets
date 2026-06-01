from django.db import models


class LarasicSyncState(models.Model):
    """Singleton holding last-LArASIC-sync results that can't live on a
    per-chip row — namely the count of chips present in the production HWDB
    with no local record ("in HWDB only"). Updated by the Sync action.
    """

    hwdb_only_count = models.PositiveIntegerField(default=0)
    synced_at = models.DateTimeField(null=True, blank=True)

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class TrayCsvCache(models.Model):
    """Persistent L2 cache for ``RTS_DIR/<tray_id>/results/`` scans.

    Survives server restarts and is shared across gunicorn workers (each tray
    pays at most one scan cost ever, until the analysis step modifies the
    results directory). Invalidated by the directory's mtime: a new file in
    ``results/`` bumps mtime, the next scan_tray_csvs() call sees the mismatch
    and rewrites the row. Rows are deleted if the results dir disappears.
    """

    tray_id = models.CharField(max_length=50, primary_key=True)
    dir_mtime = models.FloatField()
    # {"002-00797|RT": "002_00797_20250924165920_Tray31_SKT6_RT.csv", ...}
    # — filename only; the full path is rebuilt with RTS_DIR/<tray>/results/.
    csvs = models.JSONField(default=dict)
    scanned_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"TrayCsvCache({self.tray_id}, {len(self.csvs)} csvs)"


class HwdbChip(models.Model):
    """Snapshot of one chip as seen in the production HWDB.

    Kept separate from the BNL-tested chip models (``LArASIC``, ``ColdADC``,
    ``COLDATA``) on purpose — see ADR-0007. The chip tables represent BNL
    provenance; this table represents upstream visibility. The two can
    disagree (e.g. BNL has cold-tested a chip whose upload hasn't landed),
    and the ``/hwdb/dashboard/`` consistency check is exactly that gap.

    Skip-known-serials policy (ADR-0008): once a row exists for a serial,
    sync_family() never re-reads its tests. The Force-full re-sync escape
    hatch is the only way to refresh ``latest_*_test_at`` after the row is
    created. ``last_seen_at`` is the only field that updates on every sync.
    """

    FAMILY_CHOICES = [
        ("larasic", "LArASIC"),
        ("coldadc", "ColdADC"),
        ("coldata", "COLDATA"),
    ]

    family = models.CharField(max_length=10, choices=FAMILY_CHOICES, db_index=True)
    serial_number = models.CharField(max_length=50)
    part_id = models.CharField(max_length=50)
    part_type_id = models.CharField(max_length=20)
    latest_rt_test_at = models.DateTimeField(null=True, blank=True)
    latest_ln_test_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField()

    class Meta:
        unique_together = [("family", "serial_number")]
        indexes = [
            models.Index(fields=["family", "latest_rt_test_at"]),
            models.Index(fields=["family", "latest_ln_test_at"]),
        ]

    def __str__(self):
        return f"HwdbChip({self.family}, {self.serial_number})"


class HwdbSyncState(models.Model):
    """Per-family record of the last HwdbChip sync run.

    One row per family. Surfaces "Last sync · 4h ago" and the per-run counts
    (new chips this run, chips no longer in HWDB) on /hwdb/dashboard/.
    """

    family = models.CharField(max_length=10, primary_key=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    chips_total = models.PositiveIntegerField(default=0)
    chips_new = models.PositiveIntegerField(default=0)
    chips_disappeared = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")

    @classmethod
    def for_family(cls, family):
        obj, _ = cls.objects.get_or_create(family=family)
        return obj
