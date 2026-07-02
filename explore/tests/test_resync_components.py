"""Tests for the resync_components sweep command (#51 backfill story).

The per-type sync engine is mocked — no network, no bearer needed.

    python manage.py test explore
"""

from __future__ import annotations

from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from explore.models import HierarchyNode as H

_SYNC = "explore.management.commands.resync_components.sync_test_events"


def _leaf(instance, ptid, synced=True):
    return H.objects.create(
        instance=instance, level=H.LEVEL_TYPE, system_id=57, system_name="S",
        subsystem_id=2, subsystem_name="SS", name=f"Type {ptid}",
        part_type_id=ptid,
        tests_synced_at=timezone.now() if synced else None,
    )


class ResyncComponentsTest(TestCase):
    def _run(self, *args, side_effect=None):
        out = StringIO()
        with mock.patch(_SYNC) as m:
            m.side_effect = side_effect or (lambda *a, **k: iter(["done\n"]))
            call_command("resync_components", "--bearer", "x", *args, stdout=out)
        return out.getvalue(), m

    def test_sweeps_only_previously_synced_types_on_the_instance(self):
        _leaf("prod", "D01"), _leaf("prod", "D02")
        _leaf("prod", "D03", synced=False)      # never synced → skipped
        _leaf("dev", "D04")                     # other instance → skipped
        out, m = self._run()
        self.assertEqual([c.args[2] for c in m.call_args_list], ["D01", "D02"])
        self.assertEqual(m.call_args_list[0].kwargs,
                         {"instance": "prod", "mode": "components"})
        self.assertIn("2 previously-synced component type(s)", out)
        self.assertIn("all 2 type(s) re-synced", out)

    def test_instance_and_mode_flags(self):
        _leaf("dev", "D04")
        out, m = self._run("--instance", "dev", "--mode", "full")
        self.assertEqual(m.call_args_list[0].kwargs,
                         {"instance": "dev", "mode": "full"})

    def test_failure_keeps_sweeping_then_errors(self):
        _leaf("prod", "D01"), _leaf("prod", "D02")

        def _sync(api, bearer, ptid, **kw):
            if ptid == "D01":
                raise RuntimeError("boom")
            return iter(["done\n"])

        with self.assertRaises(CommandError) as ctx:
            self._run(side_effect=_sync)
        self.assertIn("1/2 type(s) failed: D01", str(ctx.exception))
