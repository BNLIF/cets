"""#180: the two mirror housekeeping commands — ``dbsize`` (read-only
breakdown) and ``mirror_prune`` (one type's mirrored tests, dry run
unless --yes)."""
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TransactionTestCase

from explore import plotting
from explore.models import HierarchyNode as H, HwdbTestData, HwdbTestValue


def _td(inst, ptid, pid, ttid, data):
    HwdbTestData.objects.create(instance=inst, part_type_id=ptid, part_id=pid, test_type_id=ttid, test_type_name="T")
    HwdbTestValue.objects.bulk_create(plotting.value_rows(inst, ptid, pid, ttid, data))


class MirrorCommandsTest(TransactionTestCase):   # VACUUM can't run inside a test transaction
    def setUp(self):
        H.objects.create(instance="dev", level=H.LEVEL_TYPE, system_id=1, system_name="S",
                         subsystem_id=1, subsystem_name="s", name="fribble", part_type_id="Z00100300029")
        _td("dev", "Z00100300029", "Z00100300029-00001", 5, {"I": list(range(100))})
        _td("dev", "Z00100300029", "Z00100300029-00002", 5, {"I": [1]})
        _td("prod", "D00400100003", "D00400100003-00001", 7, {"V": [1, 2]})

    def test_dbsize_lists_tables_and_types(self):
        out = StringIO()
        call_command("dbsize", stdout=out)
        text = out.getvalue()
        self.assertIn("tables and indexes:", text)   # a tiny test db: the big table needn't make the top rows
        self.assertIn("dev  Z00100300029       2 items         2 rows  fribble", text)
        self.assertIn("prod D00400100003", text)

    def test_prune_dry_run_then_delete(self):
        out = StringIO()
        call_command("mirror_prune", "dev", "z00100300029", stdout=out)
        self.assertIn("dev Z00100300029: 2 records, 2 value rows", out.getvalue())
        self.assertIn("dry run", out.getvalue())
        self.assertEqual(HwdbTestValue.objects.count(), 3)
        out = StringIO()
        call_command("mirror_prune", "dev", "Z00100300029", "--yes", "--vacuum", stdout=out)
        self.assertIn("deleted 2 records and 2 value rows", out.getvalue())
        self.assertIn("vacuumed", out.getvalue())
        self.assertEqual(list(HwdbTestValue.objects.values_list("part_type_id", flat=True)), ["D00400100003"])
        self.assertEqual(HwdbTestData.objects.count(), 1)
        with self.assertRaises(CommandError):
            call_command("mirror_prune", "dev", "Z00100300029")
