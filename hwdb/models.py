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
