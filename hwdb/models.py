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
