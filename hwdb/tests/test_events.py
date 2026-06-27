"""Tests for the per-component-type test-event sync + explorer plots
(issue #30, ADR-0010). HWDB fetch is mocked — no network.

    python manage.py test hwdb
"""

from __future__ import annotations

from datetime import datetime, timezone as dt_timezone
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.queries import component_type_progress
from hwdb import events
from hwdb.fnal.bearer import FnalLinkRequired
from hwdb.models import ComponentTypeNode, HwdbTestEvent


def _node(ptid="D05700200001", **kw):
    defaults = dict(
        part_type_id=ptid, system_id=57, system_name="FD-VD TDE",
        subsystem_id=2, subsystem_name="Digital electronics",
        component_type_name="AMC", full_name="D.FD-VD TDE.Digital electronics.AMC",
        n_components=2,
    )
    defaults.update(kw)
    return ComponentTypeNode.objects.create(**defaults)


def _fake_client(part_ids, tests_by_part):
    """A client whose listing returns one page of part_ids and whose
    get_tests returns the canned tests for each part_id.
    """
    client = mock.MagicMock()

    def _make_request(method, endpoint, data=None, params=None):
        # component listing
        return {"data": [{"part_id": p} for p in part_ids], "pagination": {"pages": 1}}

    client._make_request.side_effect = _make_request
    client.get_tests.side_effect = lambda pid: {"data": tests_by_part.get(pid, [])}
    return client


class SyncTestEventsTest(TestCase):
    def setUp(self):
        _node()

    def _run(self, part_ids, tests_by_part):
        client = _fake_client(part_ids, tests_by_part)
        with mock.patch("hwdb.events.FnalDbApiClient", return_value=client):
            return list(events.sync_test_events("https://x", "bearer", "D05700200001"))

    def test_stores_events_and_facets_by_test_type(self):
        tests_by_part = {
            "P1": [
                {"created": "2025-03-10T10:00:00+00:00", "test_type": {"name": "amc_bandwidth_test"}},
                {"created": "2025-03-11T10:00:00+00:00", "test_type": {"name": "amc_dataquality_test"}},
            ],
            "P2": [
                {"created": "2025-04-01T10:00:00+00:00", "test_type": {"name": "amc_bandwidth_test"}},
            ],
        }
        self._run(["P1", "P2"], tests_by_part)
        self.assertEqual(HwdbTestEvent.objects.filter(part_type_id="D05700200001").count(), 3)
        node = ComponentTypeNode.objects.get(part_type_id="D05700200001")
        self.assertEqual(node.n_tests, 3)
        self.assertIsNotNone(node.tests_synced_at)
        self.assertEqual(node.n_components, 2)

    def test_rewrites_wholesale_on_resync(self):
        self._run(["P1"], {"P1": [{"created": "2025-03-10T10:00:00+00:00", "test_type": {"name": "x"}}]})
        self.assertEqual(HwdbTestEvent.objects.count(), 1)
        # second run with different data fully replaces the first
        self._run(["P1"], {"P1": [
            {"created": "2025-05-10T10:00:00+00:00", "test_type": {"name": "y"}},
            {"created": "2025-05-11T10:00:00+00:00", "test_type": {"name": "y"}},
        ]})
        self.assertEqual(HwdbTestEvent.objects.count(), 2)
        self.assertFalse(HwdbTestEvent.objects.filter(test_type_name="x").exists())

    def test_skips_records_without_created(self):
        self._run(["P1"], {"P1": [
            {"created": None, "test_type": {"name": "x"}},
            {"created": "2025-03-10T10:00:00+00:00", "test_type": {"name": "x"}},
        ]})
        self.assertEqual(HwdbTestEvent.objects.count(), 1)


class ComponentTypeProgressTest(TestCase):
    def test_one_series_per_test_type(self):
        ptid = "D05700200001"
        for name, day in [("a", 10), ("a", 11), ("b", 12)]:
            HwdbTestEvent.objects.create(
                part_type_id=ptid, part_id="", test_type_name=name,
                created=datetime(2025, 3, day, tzinfo=dt_timezone.utc),
            )
        ranges = component_type_progress(ptid)
        self.assertEqual(set(ranges), {"month", "3month", "all"})  # no 1year projection
        names = [s["name"] for s in ranges["all"]["series"]]
        self.assertEqual(names, ["a", "b"])  # sorted
        self.assertEqual(sum(sum(s["counts"]) for s in ranges["all"]["series"]), 3)


class ExplorePlotViewTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("plotter", "p@p.io", "pw")
        self.client.force_login(self.user)

    def test_synced_node_renders_chart(self):
        node = _node(tests_synced_at=timezone.now(), n_tests=1)
        HwdbTestEvent.objects.create(
            part_type_id=node.part_type_id, part_id="", test_type_name="amc_bandwidth_test",
            created=datetime(2025, 3, 10, tzinfo=dt_timezone.utc),
        )
        html = self.client.get(reverse("hwdb:explore") + f"?node={node.part_type_id}").content.decode()
        self.assertIn("node-chart-config", html)
        self.assertIn(f"bar_{node.part_type_id}", html)
        self.assertIn("amc_bandwidth_test", html)

    def test_unsynced_node_shows_autosync_block(self):
        node = _node()  # tests_synced_at is NULL
        html = self.client.get(reverse("hwdb:explore") + f"?node={node.part_type_id}").content.decode()
        self.assertIn('id="node-unsynced"', html)

    def test_synced_but_empty_node(self):
        node = _node(tests_synced_at=timezone.now(), n_tests=0)
        html = self.client.get(reverse("hwdb:explore") + f"?node={node.part_type_id}").content.decode()
        self.assertIn("No tests recorded", html)


class ExploreNodeSyncViewTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("ns", "n@n.io", "pw")
        self.client.force_login(self.user)
        _node()

    def test_get_not_allowed(self):
        resp = self.client.get(reverse("hwdb:explore_node_sync", args=["D05700200001"]))
        self.assertEqual(resp.status_code, 405)

    def test_unlinked_redirects_with_node_next(self):
        with mock.patch("hwdb.views.mint_for", side_effect=FnalLinkRequired("no link")):
            resp = self.client.post(reverse("hwdb:explore_node_sync", args=["D05700200001"]))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("node%3DD05700200001", resp["Location"])  # ?next=...?node=...

    def test_streams_when_linked(self):
        with mock.patch("hwdb.views.mint_for", return_value="bearer"), \
             mock.patch("hwdb.views.sync_test_events", return_value=iter(["scanning\n", "done\n"])):
            resp = self.client.post(reverse("hwdb:explore_node_sync", args=["D05700200001"]))
            body = b"".join(resp.streaming_content).decode()
        self.assertEqual(resp.status_code, 200)
        self.assertIn("done", body)
