"""Where the database's bytes go (#180): the biggest tables and, for the
test mirror, the value rows per instance and type — the SiPM curves are
the cost, and a sandbox type mirrored by mistake shows up here too.

Read-only, SQLite only (``dbstat``); other backends get the row counts.

    python manage.py dbsize
    python manage.py dbsize --top 20
"""
import os

from django.core.management.base import BaseCommand
from django.db import connection
from django.db.models import Count

from explore.models import HierarchyNode, HwdbTestValue


class Command(BaseCommand):
    help = "Database size by table, and the test mirror's value rows by instance and type."

    def add_arguments(self, parser):
        parser.add_argument("--top", type=int, default=10, help="rows per section (default 10)")

    def handle(self, *args, top, **opts):
        sqlite = connection.vendor == "sqlite"
        if sqlite:
            path = str(connection.settings_dict["NAME"])
            if os.path.exists(path):
                self.stdout.write(f"{path}: {os.path.getsize(path) / 2**30:.2f} GB")
            with connection.cursor() as cur:
                cur.execute("PRAGMA freelist_count")
                free = cur.fetchone()[0]
                cur.execute("PRAGMA page_size")
                self.stdout.write(f"free pages: {free * cur.fetchone()[0] / 2**20:.0f} MB (VACUUM returns them)")
                cur.execute("SELECT name, SUM(pgsize) FROM dbstat GROUP BY name ORDER BY 2 DESC LIMIT %s", [top])
                self.stdout.write("\ntables and indexes:")
                for name, size in cur.fetchall():
                    self.stdout.write(f"{size / 2**20:9.0f} MB  {name}")
        names = {(n.instance, n.part_type_id): n.name
                 for n in HierarchyNode.objects.filter(level=HierarchyNode.LEVEL_TYPE)}
        self.stdout.write("\ntest mirror value rows by instance and type:")
        with connection.cursor() as cur:
            table = HwdbTestValue._meta.db_table
            cur.execute(f'SELECT instance, part_type_id, SUM(LENGTH("values")), COUNT(*), COUNT(DISTINCT part_id) '
                        f"FROM {table} GROUP BY 1, 2 ORDER BY 3 DESC LIMIT %s", [top])
            rows = cur.fetchall()
        for inst, ptid, size, n, items in rows:
            self.stdout.write(f"{(size or 0) / 2**20:9.0f} MB  {inst:4} {ptid}  {items:6} items  {n:8} rows  "
                              f"{names.get((inst, ptid), '')}")
        if not rows:
            self.stdout.write("  (none)")
