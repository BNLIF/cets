"""Delete Upload-sheet jobs untouched for ``sheetupload.RETENTION_DAYS``.

The Upload pages prune on every visit, but a user whose upload succeeded
rarely comes back (Chao 2026-09-30), so the stated "kept N days" needs a
daily run too:

    0 4 * * * cd .../cets && venv/bin/python manage.py sheet_prune
"""
from django.core.management.base import BaseCommand

from explore import sheetupload
from explore.models import SheetJob


class Command(BaseCommand):
    help = f"Delete Upload-sheet jobs untouched for {sheetupload.RETENTION_DAYS} days."

    def handle(self, *args, **opts):
        n = SheetJob.prune(sheetupload.RETENTION_DAYS)
        self.stdout.write(f"deleted {n} job(s) untouched for {sheetupload.RETENTION_DAYS} days")
