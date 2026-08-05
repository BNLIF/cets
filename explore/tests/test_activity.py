"""Tests for the Activities feed (#88): the ActivityEvent model + logger,
the one-summary-row-per-sync rule, the in-app write hooks, and the
/activities/ page. HWDB fetch is mocked — no network.

    python manage.py test explore
"""

from __future__ import annotations

from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from explore import activity, events, shipments
from explore.models import ActivityEvent, ShipmentItem
from explore.tests.test_events import _fake_client as _events_client
from explore.tests.test_events import _node
from explore.tests.test_shipments import SHIP_PTID, _fake_client, _loc, _ship_leaf


def _age(event, days):
    """Backdate an auto_now_add timestamp."""
    ActivityEvent.objects.filter(pk=event.pk).update(
        created_at=timezone.now() - timedelta(days=days))


class ActivityLogTest(TestCase):
    def test_log_records_a_scoped_row(self):
        activity.log("dev", ActivityEvent.KIND_MINTED, "Box B1 minted",
                     part_id="B1", part_type_id="T1", actor="chao")
        e = ActivityEvent.for_instance("dev").get()
        self.assertEqual((e.kind, e.part_id, e.part_type_id, e.actor),
                         ("minted", "B1", "T1", "chao"))
        self.assertFalse(ActivityEvent.for_instance("prod").exists())

    def test_log_prunes_rows_older_than_retention(self):
        activity.log("prod", ActivityEvent.KIND_SYNC, "old")
        _age(ActivityEvent.objects.get(), activity.RETENTION_DAYS + 1)
        activity.log("prod", ActivityEvent.KIND_SYNC, "new")
        self.assertEqual(
            list(ActivityEvent.objects.values_list("summary", flat=True)), ["new"])

    def test_log_never_raises(self):
        with mock.patch.object(ActivityEvent.objects, "create",
                               side_effect=RuntimeError("db down")):
            activity.log("prod", ActivityEvent.KIND_SYNC, "x")  # must not raise
        self.assertFalse(ActivityEvent.objects.exists())

    def test_kind_label(self):
        activity.log("prod", ActivityEvent.KIND_ES, "x")
        self.assertEqual(ActivityEvent.objects.get().kind_label, "Exec summary")


class ActorOfTest(TestCase):
    """The recorded actor is the FNAL user, never the Django session user —
    someone also signed into CETS proper as ``admin`` must still show as
    their FNAL credkey; the ``fnal:`` namespace prefix never surfaces."""

    def setUp(self):
        from hwdb.fnal.session import LINK_KEY
        self.LINK_KEY = LINK_KEY
        self.user = get_user_model().objects.create_user("admin", "a@a.io", "pw")
        self.client.force_login(self.user)

    def _request(self, link=None):
        session = self.client.session
        if link is not None:
            session[self.LINK_KEY] = link
            session.save()
        request = mock.Mock()
        request.session = session
        request.user = self.user
        return request

    def test_session_link_credkey_wins_over_django_user(self):
        request = self._request(link={"credkey": "chaoz", "vault_token": "x"})
        self.assertEqual(activity.actor_of(request), "chaoz")

    def test_fallback_strips_fnal_prefix(self):
        request = self._request()
        request.user = mock.Mock()
        request.user.get_username.return_value = "fnal:chaoz"
        self.assertEqual(activity.actor_of(request), "chaoz")

    def test_fallback_plain_username_passes_through(self):
        request = self._request()
        self.assertEqual(activity.actor_of(request), "admin")


class ShipmentSyncSummaryTest(TestCase):
    """sync_shipments logs ONE summary row per run — only when new boxes
    appeared, never one row per box."""

    def setUp(self):
        self.leaf = _ship_leaf()

    def _run(self, items, locs, mode="full"):
        client = _fake_client(items, locs)
        with mock.patch("explore.shipments.FnalDbApiClient", return_value=client):
            return list(shipments.sync_shipments(
                "https://x", "bearer", SHIP_PTID, "prod", mode=mode))

    def test_new_boxes_make_one_summary_event(self):
        self._run([{"part_id": "B1"}, {"part_id": "B2"}],
                  {"B1": [_loc("BNL", 128, "2026-06-01T00:00:00-05:00")], "B2": []})
        e = ActivityEvent.for_instance("prod").get()   # exactly one row
        self.assertEqual(e.kind, ActivityEvent.KIND_SYNC)
        self.assertIn("2 new box(es)", e.summary)
        self.assertIn(self.leaf.name, e.summary)
        self.assertEqual(e.part_type_id, SHIP_PTID)

    def test_all_known_sync_logs_nothing(self):
        items = [{"part_id": "B1"}]
        locs = {"B1": [_loc("BNL", 128, "2026-06-01T00:00:00-05:00")]}
        self._run(items, locs)
        ActivityEvent.objects.all().delete()
        self._run(items, locs)                          # same boxes again
        self.assertFalse(ActivityEvent.objects.exists())

    def test_incremental_counts_only_the_new_box(self):
        self._run([{"part_id": "B1"}], {"B1": []})
        ActivityEvent.objects.all().delete()
        self._run([{"part_id": "B1"}, {"part_id": "B2"}], {"B2": []},
                  mode="incremental")
        self.assertIn("1 new box(es)", ActivityEvent.objects.get().summary)


class TestSyncSummaryTest(TestCase):
    """sync_test_events logs one summary row, and only on net-new mirrors."""

    def setUp(self):
        self.node = _node()

    def _run(self, part_ids, tests_by_part, mode="incremental"):
        client = _events_client(part_ids, tests_by_part)
        with mock.patch("explore.events.FnalDbApiClient", return_value=client):
            return list(events.sync_test_events(
                "https://x", "bearer", "D05700200001", mode=mode))

    def test_new_components_and_tests_make_one_event(self):
        self._run(["P1", "P2"], {"P1": [
            {"created": "2025-03-10T10:00:00+00:00",
             "test_type": {"name": "amc_bandwidth_test"}}]})
        e = ActivityEvent.for_instance("prod").get()
        self.assertEqual(e.kind, ActivityEvent.KIND_SYNC)
        self.assertIn("2 new component(s)", e.summary)
        self.assertIn("1 new test event(s)", e.summary)
        self.assertIn(self.node.name, e.summary)

    def test_resync_with_nothing_new_logs_nothing(self):
        canned = {"P1": [{"created": "2025-03-10T10:00:00+00:00",
                          "test_type": {"name": "amc_bandwidth_test"}}]}
        self._run(["P1"], canned)
        ActivityEvent.objects.all().delete()
        self._run(["P1"], canned, mode="full")          # rewrite, no delta
        self.assertFalse(ActivityEvent.objects.exists())


class RefreshRowEventTest(TestCase):
    """The per-row ⟳ logs a 'moved' event only when the box actually changed."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("rf", "r@f.io", "pw")
        self.client.force_login(self.user)
        _ship_leaf()
        ShipmentItem.objects.create(part_type_id=SHIP_PTID, part_id="B1",
                                    location_name="In Transit", location_id=0,
                                    n_contents=3)

    def _refresh(self, move_to=None):
        def _fake_refresh(api, instance, ptid, part_id):
            if move_to:
                ShipmentItem.objects.filter(part_id=part_id).update(
                    location_name=move_to, location_id=200)
        with mock.patch("explore.views.mint_for", return_value="bearer"), \
             mock.patch("explore.views.FnalDbApiClient"), \
             mock.patch("explore.views.refresh_box", side_effect=_fake_refresh):
            return self.client.post(
                reverse("explore:shipment_refresh", args=["B1"]))

    def test_moved_box_logs_event(self):
        # A session FNAL link makes the credkey the recorded actor, even
        # though the Django session user is "rf" (end-to-end actor_of check).
        from hwdb.fnal.session import LINK_KEY
        session = self.client.session
        session[LINK_KEY] = {"credkey": "chaoz", "vault_token": "x"}
        session.save()
        self._refresh(move_to="CERN")
        e = ActivityEvent.objects.get()
        self.assertEqual(e.kind, ActivityEvent.KIND_SYNC)
        self.assertIn("B1 moved", e.summary)
        self.assertIn("CERN", e.summary)
        self.assertEqual(e.actor, "chaoz")

    def test_unmoved_box_logs_nothing(self):
        self._refresh(move_to=None)
        self.assertFalse(ActivityEvent.objects.exists())


class PackFullEventTest(TestCase):
    """Packing logs no per-item events — only the moment a box becomes full."""

    def setUp(self):
        from explore.tests.test_box_pack import _mirror_items
        self.user = get_user_model().objects.create_user("pf", "p@f.io", "pw")
        self.client.force_login(self.user)
        _mirror_items()

    def _add_good(self, connectors):
        from explore.tests.test_box_pack import GOOD, PACK, _api, _mocked
        api = _api()
        api.get_component_type.return_value = {"status": "OK", "data": {
            "part_type_id": "D00599800007", "connectors": connectors}}
        m1, m2 = _mocked(api)
        with m1, m2:
            self.client.post(PACK, {"pid": [GOOD]})

    def test_last_slot_filled_logs_fully_packed(self):
        from explore.tests.test_box_pack import BOX, CHILD_TYPE
        self._add_good({"Slot 1": CHILD_TYPE, "Slot 2": CHILD_TYPE})
        e = ActivityEvent.for_instance("dev").get()
        self.assertEqual(e.kind, ActivityEvent.KIND_PACK)
        self.assertIn(f"{BOX} fully packed", e.summary)
        self.assertIn("2 position(s)", e.summary)
        self.assertEqual(e.actor, "pf")

    def test_add_leaving_free_slots_logs_nothing(self):
        from explore.tests.test_box_pack import CHILD_TYPE, DOC_TYPE
        # Doc slot stays empty after the add — the box isn't full yet.
        self._add_good({"Slot 1": CHILD_TYPE, "Slot 2": CHILD_TYPE,
                        "Doc": DOC_TYPE})
        self.assertFalse(ActivityEvent.objects.exists())


class EsFeedEventTest(TestCase):
    """ES comments, resets and config saves write to HWDB and are rare —
    each gets a feed row."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("es", "e@s.io", "pw")
        self.client.force_login(self.user)

    def test_comment_logs_an_event(self):
        from explore.tests.test_exec_summary import PAGE, _api, _mocked
        m1, m2 = _mocked(_api(es=[]))
        with m1, m2:
            self.client.post(PAGE, {"action": "comment",
                                    "comment_text": "mid-flow note"})
        e = ActivityEvent.for_instance("dev").get()
        self.assertEqual(e.kind, ActivityEvent.KIND_ES)
        self.assertIn("ES comment posted", e.summary)
        self.assertEqual(e.actor, "es")

    def test_reset_logs_an_event(self):
        from explore.tests.test_exec_summary import PAGE, _api, _entry, _mocked
        m1, m2 = _mocked(_api(es=[_entry("Chao Zhang", 2)]))
        with m1, m2:
            self.client.post(PAGE, {"action": "reset"})
        e = ActivityEvent.for_instance("dev").get()
        self.assertIn("ES reset — signatures cleared", e.summary)

    def test_config_save_logs_an_event(self):
        import json
        from explore.tests.test_exec_summary import CFG_PAGE, _api, _mocked
        m1, m2 = _mocked(_api())
        with m1, m2:
            self.client.post(CFG_PAGE, {
                "config_json": json.dumps({
                    "consortium_name": "CE",
                    "todos": {"title": "QC", "check_list": ["a"]}}),
                "next": ""})
        e = ActivityEvent.for_instance("dev").get()
        self.assertEqual(e.kind, ActivityEvent.KIND_ES)
        self.assertIn("ES config updated for type D00599800007", e.summary)
        self.assertEqual(e.part_type_id, "D00599800007")
        self.assertEqual(e.part_id, "")   # type-level, no part link


class ActivitiesPageTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("ap", "a@p.io", "pw")
        self.client.force_login(self.user)

    def test_requires_login(self):
        self.client.logout()
        resp = self.client.get(reverse("explore:activities"))
        self.assertEqual(resp.status_code, 302)

    def test_lists_events_newest_first_with_part_link(self):
        activity.log("prod", ActivityEvent.KIND_MINTED, "Box B1 minted",
                     part_id="B1", part_type_id="T1", actor="chao")
        activity.log("prod", ActivityEvent.KIND_SYNC, "Shipment sync: 2 new box(es)")
        html = self.client.get(reverse("explore:activities")).content.decode()
        self.assertLess(html.index("Shipment sync"), html.index("Box B1 minted"))
        self.assertIn(reverse("explore:part", args=["B1"]), html)
        self.assertIn("by chao", html)

    def test_instance_scoped(self):
        activity.log("dev", ActivityEvent.KIND_SYNC, "dev-only event")
        html = self.client.get(reverse("explore:activities")).content.decode()
        self.assertNotIn("dev-only event", html)

    def test_view_prunes_old_events(self):
        activity.log("prod", ActivityEvent.KIND_SYNC, "ancient")
        _age(ActivityEvent.objects.get(), activity.RETENTION_DAYS + 1)
        html = self.client.get(reverse("explore:activities")).content.decode()
        self.assertNotIn("ancient", html)
        self.assertFalse(ActivityEvent.objects.exists())

    def test_paginates_at_100_newest_first(self):
        for i in range(110):
            activity.log("prod", ActivityEvent.KIND_SYNC, f"event {i}")
        resp = self.client.get(reverse("explore:activities"))
        self.assertEqual(len(resp.context["page_obj"]), 100)
        self.assertEqual(resp.context["page_obj"][0].summary, "event 109")
        html = self.client.get(
            reverse("explore:activities"), {"page": 2}).content.decode()
        self.assertIn("Page 2 of 2", html)

    def test_nav_and_empty_state(self):
        html = self.client.get(reverse("explore:activities")).content.decode()
        self.assertIn("Activities", html)
        self.assertIn("Nothing yet", html)
