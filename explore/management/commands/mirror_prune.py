"""Delete one type's mirrored test records (#180) — for a type nobody
plots whose curves cost space, e.g. HWDB's sandbox demo type "fribble"
(Z00100300029, 0.8 GB on twister). Items and hierarchy stay; the Plot page
loses the type's test source until someone fetches it again.

Prints what would go and stops unless ``--yes``. ``--vacuum`` hands the
space back to the OS afterwards (SQLite; needs free disk ≈ the file).

    python manage.py mirror_prune dev Z00100300029
    python manage.py mirror_prune dev Z00100300029 --yes --vacuum
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from explore.models import HwdbTestData, HwdbTestValue


class Command(BaseCommand):
    help = "Delete the mirrored test records (metadata + value rows) of one type on one instance."

    def add_arguments(self, parser):
        parser.add_argument("instance", choices=["dev", "prod"])
        parser.add_argument("part_type_id")
        parser.add_argument("--yes", action="store_true", help="delete (without it: report only)")
        parser.add_argument("--vacuum", action="store_true", help="VACUUM afterwards (SQLite)")

    def handle(self, *args, instance, part_type_id, yes, vacuum, **opts):
        ptid = part_type_id.strip().upper()
        recs = HwdbTestData.for_instance(instance).filter(part_type_id=ptid)
        vals = HwdbTestValue.for_instance(instance).filter(part_type_id=ptid)
        n_recs, n_vals = recs.count(), vals.count()
        if not n_recs and not n_vals:
            raise CommandError(f"{instance} {ptid}: no mirrored test records.")
        self.stdout.write(f"{instance} {ptid}: {n_recs} records, {n_vals} value rows")
        if not yes:
            self.stdout.write("dry run — add --yes to delete")
            return
        vals._raw_delete(vals.db)   # one DELETE, no per-row signals — these tables have none
        recs._raw_delete(recs.db)
        self.stdout.write(f"deleted {n_recs} records and {n_vals} value rows")
        if vacuum:
            if connection.vendor != "sqlite":
                self.stdout.write("--vacuum: SQLite only, skipped")
                return
            with connection.cursor() as cur:
                cur.execute("VACUUM")
            self.stdout.write("vacuumed")
