"""Tests for the ops page (#194) and the usage middleware that feeds it.

    python manage.py test explore.tests.test_ops
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from explore import ops
from explore.models import ActivityEvent, HierarchyNode, HierarchySyncState, UsageDay

PAGE = "/hw/ops/"
HOME = "/hw/"


class OpsGateTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.chaoz = User.objects.create_user("fnal:chaoz", password="x")
        self.bob = User.objects.create_user("fnal:bob", password="x")

    @override_settings(OPS_USERS=["fnal:chaoz"])
    def test_listed_user_sees_the_page_with_every_user_on_it(self):
        self.client.force_login(self.chaoz)
        resp = self.client.get(PAGE)
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn("fnal:bob", html)
        self.assertIn(">Ops</a>", html)           # the nav item shows for them

    @override_settings(OPS_USERS=["fnal:chaoz"])
    def test_unlisted_user_gets_404_and_no_nav_item(self):
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(PAGE).status_code, 404)
        self.assertNotIn(">Ops</a>", self.client.get(HOME).content.decode())

    @override_settings(OPS_USERS=["fnal:chaoz"])
    def test_sync_errors_page_lists_the_full_error_behind_the_same_gate(self):
        HierarchyNode.objects.create(instance="dev", level=HierarchyNode.LEVEL_TYPE, system_id=1,
                                     system_name="S", name="whatchamacallit", part_type_id="Z00100300016",
                                     tests_sync_error="403 FORBIDDEN for https://x/api/v1/component-types/Z00100300016/components: {}")
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(PAGE + "sync-errors/").status_code, 404)
        self.client.force_login(self.chaoz)
        html = self.client.get(PAGE).content.decode()
        self.assertIn("1 with errors", html)
        self.assertNotIn("component-types/Z00100300016", html)     # the URL stays off the ops page
        html = self.client.get(PAGE + "sync-errors/").content.decode()
        self.assertIn("component-types/Z00100300016/components", html)
        self.assertIn("403 FORBIDDEN", html)

    @override_settings(OPS_USERS=[])
    def test_empty_list_means_nobody(self):
        self.client.force_login(self.chaoz)
        self.assertEqual(self.client.get(PAGE).status_code, 404)

    @override_settings(OPS_USERS=["fnal:chaoz"])
    def test_anonymous_is_sent_to_login(self):
        self.assertEqual(self.client.get(PAGE).status_code, 302)


class UsageMiddlewareTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("fnal:chaoz", password="x")

    def test_one_row_per_user_per_day_counts_requests(self):
        self.client.force_login(self.user)
        self.client.get(HOME)
        self.client.get(HOME)
        rows = list(UsageDay.objects.all())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].username, "fnal:chaoz")
        self.assertEqual(rows[0].day, timezone.now().date())
        self.assertEqual(rows[0].requests, 2)

    def test_head_and_anonymous_are_not_counted(self):
        self.client.head(HOME)                      # anonymous → not counted
        self.client.force_login(self.user)
        self.client.head(HOME)                      # HEAD → not counted
        self.assertEqual(UsageDay.objects.count(), 0)


class CollectorsTest(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def test_tail_of_missing_file_is_empty(self):
        self.assertEqual(ops.tail(Path(self.dir.name) / "nope.log"), [])

    def test_errors_groups_traceback_lines_and_counts_the_day(self):
        stamp = self.now.strftime("%Y-%m-%d %H:%M:%S")
        log = Path(self.dir.name) / "cets.log"
        log.write_text(
            "2020-01-01 00:00:00 WARNING hwdb.api_client HWDB GET x -> 502\n"
            f"{stamp} ERROR django.request Internal Server Error: /hw/\n"
            "Traceback (most recent call last):\n"
            "  File \"x.py\", line 1\n"
            "KeyError: 'limits'\n")
        with override_settings(LOG_FILE=log):
            e = ops.errors(self.now)
        self.assertEqual([x["level"] for x in e["entries"]], ["ERROR", "WARNING"])   # newest first
        self.assertEqual(len(e["entries"][0]["extra"]), 3)
        self.assertEqual(e["warn_24h"], 1)
        self.assertEqual(e["error_24h"], 1)

    def test_writes_bins_feed_rows_by_day(self):
        ActivityEvent.objects.create(instance="prod", kind="checklist", summary="a")
        ActivityEvent.objects.create(instance="dev", kind="checklist", summary="b")
        ActivityEvent.objects.create(instance="prod", kind="sync", summary="c")
        w = ops.writes(self.now)
        self.assertEqual(len(w["bars"]), ops.WRITES_DAYS)
        today = w["bars"][-1]
        self.assertEqual(today["total"], 3)
        self.assertEqual({s["kind"]: s["n"] for s in today["segs"]}, {"checklist": 2, "sync": 1})
        self.assertEqual(w["total"], 3)

    def test_sync_flags_an_instance_with_an_error(self):
        HierarchySyncState.objects.create(instance="prod", finished_at=self.now, last_error="")
        HierarchySyncState.objects.create(instance="dev", finished_at=self.now, last_error="read timeout")
        s = ops.sync(self.now)
        self.assertEqual([i["status"] for i in s["instances"]], ["ok", "bad"])

    def test_type_sync_errors_are_shortened_to_the_http_status(self):
        self.assertEqual(ops._short("403 FORBIDDEN for https://x/api/v1/component-types/Z1/components: { \"data\": \"V"),
                         "403 FORBIDDEN")
        self.assertEqual(ops._short("3 of 12 item(s) could not be fetched: D1-00001, D1-00002"),
                         "3 of 12 item(s) could not be fetched")

    def test_collect_survives_a_broken_section(self):
        with override_settings(LOG_FILE=Path(self.dir.name) / "none.log"):
            out = ops.collect()
        self.assertEqual(out["problems"], [])
        self.assertFalse(out["errors"]["exists"])
