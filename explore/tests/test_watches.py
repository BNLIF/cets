"""Tests for watch/notify (#90): subscriptions on types, boxes and items,
the derived watched feed + unread badge, and the profile "Watching" section.
No notification storage — everything derives from ActivityEvent.

    python manage.py test explore
"""

from __future__ import annotations

from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from explore import activity, navigation, watches
from explore.models import ActivityEvent, WatchSubscription
from explore.tests.test_events import _node
from explore.tests.test_profile import _api as _profile_api
from explore.tests.test_profile import _mocked as _profile_mocked

PTID = "D05700200001"


def _event(kind=ActivityEvent.KIND_SYNC, summary="x", part_id="",
           part_type_id="", instance="prod", ago=None):
    e = ActivityEvent.objects.create(
        instance=instance, kind=kind, summary=summary,
        part_id=part_id, part_type_id=part_type_id)
    if ago is not None:
        ActivityEvent.objects.filter(pk=e.pk).update(
            created_at=timezone.now() - ago)
    return e


class WatchEngineTest(TestCase):
    def test_toggle_creates_then_removes(self):
        self.assertTrue(watches.toggle("prod", "chaoz", part_type_id=PTID,
                                       label="AMC"))
        self.assertTrue(watches.is_watched("prod", "chaoz", part_type_id=PTID))
        self.assertFalse(watches.toggle("prod", "chaoz", part_type_id=PTID))
        self.assertFalse(WatchSubscription.objects.exists())

    def test_part_watch_matches_only_that_part(self):
        watches.toggle("prod", "chaoz", part_id="P1", part_type_id=PTID)
        _event(summary="mine", part_id="P1", part_type_id=PTID)
        _event(summary="other part", part_id="P2", part_type_id=PTID)
        _event(summary="type only", part_type_id=PTID)
        self.assertEqual(
            [e.summary for e in watches.watched_events("prod", "chaoz")],
            ["mine"])

    def test_type_watch_matches_type_and_its_parts(self):
        watches.toggle("prod", "chaoz", part_type_id=PTID)
        _event(summary="type-level", part_type_id=PTID)
        _event(summary="part of type", part_id="P1", part_type_id=PTID)
        _event(summary="unrelated", part_type_id="D99999999999")
        self.assertEqual(
            {e.summary for e in watches.watched_events("prod", "chaoz")},
            {"type-level", "part of type"})

    def test_unread_counts_only_events_after_seen(self):
        watches.toggle("prod", "chaoz", part_type_id=PTID)
        _event(part_type_id=PTID, ago=timedelta(hours=1))  # before subscribing
        self.assertEqual(watches.unread_count("prod", "chaoz"), 0)
        _event(part_type_id=PTID)
        self.assertEqual(watches.unread_count("prod", "chaoz"), 1)
        watches.mark_seen("prod", "chaoz")
        self.assertEqual(watches.unread_count("prod", "chaoz"), 0)
        # still listed in the watched feed — unread ≠ visible
        self.assertEqual(watches.watched_events("prod", "chaoz").count(), 2)

    def test_no_watches_short_circuits(self):
        _event(part_type_id=PTID)
        self.assertEqual(watches.unread_count("prod", "chaoz"), 0)
        self.assertEqual(watches.watched_events("prod", "chaoz").count(), 0)

    def test_instance_scoped(self):
        watches.toggle("dev", "chaoz", part_type_id=PTID)
        _event(part_type_id=PTID, instance="dev")
        self.assertEqual(watches.unread_count("dev", "chaoz"), 1)
        self.assertEqual(watches.unread_count("prod", "chaoz"), 0)


class WatchToggleViewTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("wa", "w@a.io", "pw")
        self.client.force_login(self.user)
        self.url = reverse("explore:watch_toggle")

    def test_requires_login(self):
        self.client.logout()
        resp = self.client.post(self.url, {"part_type_id": PTID})
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("explore:login"), resp["Location"])

    def test_toggle_roundtrip_records_fnal_actor(self):
        from hwdb.fnal.session import LINK_KEY
        session = self.client.session
        session[LINK_KEY] = {"credkey": "chaoz", "vault_token": "x"}
        session.save()
        resp = self.client.post(self.url, {"part_type_id": PTID, "label": "AMC",
                                           "next": "/explore/"})
        self.assertRedirects(resp, "/explore/", fetch_redirect_response=False)
        sub = WatchSubscription.objects.get()
        self.assertEqual((sub.username, sub.part_type_id, sub.label),
                         ("chaoz", PTID, "AMC"))
        self.client.post(self.url, {"part_type_id": PTID})
        self.assertFalse(WatchSubscription.objects.exists())

    def test_empty_target_is_refused(self):
        self.assertEqual(self.client.post(self.url, {}).status_code, 400)

    def test_unsafe_next_falls_back_to_activities(self):
        resp = self.client.post(self.url, {"part_type_id": PTID,
                                           "next": "https://evil.example/"})
        self.assertEqual(resp["Location"], reverse("explore:activities"))


class BadgeAndWatchedTabTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("bt", "b@t.io", "pw")
        self.client.force_login(self.user)
        watches.toggle("prod", "bt", part_type_id=PTID, label="AMC")

    def test_avatar_badge_shows_unread_count(self):
        _event(part_type_id=PTID, summary="fresh")
        html = self.client.get(reverse("explore:activities")).content.decode()
        self.assertIn("eh-avatar-badge", html)

    def test_no_unread_no_badge(self):
        html = self.client.get(reverse("explore:activities")).content.decode()
        self.assertNotIn("eh-avatar-badge", html)

    def test_watching_tab_filters_without_marking_seen(self):
        _event(part_type_id=PTID, summary="watched thing")
        _event(part_type_id="D99999999999", summary="unwatched thing")
        html = self.client.get(reverse("explore:activities"),
                               {"watched": "1"}).content.decode()
        self.assertIn("watched thing", html)
        self.assertNotIn("unwatched thing", html)
        self.assertIn("act-row is-unread", html)          # highlighted
        self.assertIn("Mark all read", html)
        # a visit never marks read — only the explicit button does
        self.assertEqual(watches.unread_count("prod", "bt"), 1)

    def test_mark_all_read_button_clears_unread(self):
        _event(part_type_id=PTID)
        resp = self.client.post(reverse("explore:watch_seen"),
                                {"next": "/explore/?watched=1"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(watches.unread_count("prod", "bt"), 0)
        html = self.client.get(reverse("explore:activities"),
                               {"watched": "1"}).content.decode()
        self.assertNotIn("act-row is-unread", html)
        self.assertNotIn("Mark all read", html)           # nothing left to mark

    def test_all_tab_still_shows_everything(self):
        _event(part_type_id="D99999999999", summary="unwatched thing")
        html = self.client.get(reverse("explore:activities")).content.decode()
        self.assertIn("unwatched thing", html)
        self.assertEqual(watches.unread_count("prod", "bt"), 0)  # untouched

    def test_watched_pager_keeps_the_filter(self):
        for i in range(105):
            _event(part_type_id=PTID, summary=f"e{i}")
        html = self.client.get(reverse("explore:activities"),
                               {"watched": "1"}).content.decode()
        self.assertIn("watched=1&amp;page=2", html)

    def test_watched_empty_state_nudges_to_watch(self):
        WatchSubscription.objects.all().delete()
        html = self.client.get(reverse("explore:activities"),
                               {"watched": "1"}).content.decode()
        self.assertIn("not watching anything yet", html)


class LeafWatchButtonTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("lw", "l@w.io", "pw")
        self.client.force_login(self.user)
        self.leaf = _node()
        self.path = navigation.leaf_path_for("prod", PTID)

    def test_leaf_page_offers_watch(self):
        html = self.client.get(self.path).content.decode()
        self.assertIn("☆ Watch", html)
        self.assertIn(reverse("explore:watch_toggle"), html)

    def test_leaf_page_shows_watching_state(self):
        watches.toggle("prod", "lw", part_type_id=PTID)
        html = self.client.get(self.path).content.decode()
        self.assertIn("★ Watching", html)

    def test_leaf_page_has_no_hierarchy_refresh(self):
        # Watch takes the page-head slot — a leaf syncs via its own buttons;
        # the full hierarchy walk doesn't belong there.
        html = self.client.get(self.path).content.decode()
        self.assertNotIn("Refresh hierarchy", html)
        self.assertIn("node-sync-btn", html)     # the leaf's own sync stays

    def test_folder_page_keeps_hierarchy_refresh(self):
        html = self.client.get(reverse("explore:browse")).content.decode()
        self.assertIn("Refresh hierarchy", html)
        self.assertNotIn("☆ Watch", html)


class ProfileWatchSectionTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("s", "s@s.io", "pw")
        self.client.force_login(self.user)

    def test_lists_watches_with_links_and_unwatch(self):
        watches.toggle("dev", "s", part_id="P1", part_type_id=PTID, label="AMC")
        watches.toggle("dev", "s", part_type_id=PTID, label="AMC")
        m1, m2 = _profile_mocked(_profile_api())
        with m1, m2:
            html = self.client.get("/hw/dev/profile/").content.decode()
        self.assertIn("Watching (2)", html)
        self.assertIn("P1", html)
        self.assertIn("/hw/dev/watch/", html)                  # unwatch forms
        self.assertIn("/hw/dev/part/P1/", html)                # part link
        self.assertIn("watched=1", html)                       # feed link

    def test_empty_state(self):
        m1, m2 = _profile_mocked(_profile_api())
        with m1, m2:
            html = self.client.get("/hw/dev/profile/").content.decode()
        self.assertIn("Watching (0)", html)
        self.assertIn("Nothing yet", html)
        self.assertIn("No recent events", html)

    def test_feed_column_lists_events_without_marking_seen(self):
        watches.toggle("dev", "s", part_type_id=PTID, label="AMC")
        _event(part_id="P1", part_type_id=PTID, instance="dev",
               summary="P1 moved — In packing · CERN")
        m1, m2 = _profile_mocked(_profile_api())
        with m1, m2:
            html = self.client.get("/hw/dev/profile/").content.decode()
        self.assertIn("Watching activity", html)
        self.assertIn("1 new", html)
        self.assertIn("P1 moved", html)
        self.assertIn("/hw/dev/part/P1/", html)
        self.assertIn("pf-ev-row is-unread", html)        # highlighted
        self.assertIn("Mark all read", html)
        # profile only shows them; the button is what marks read
        self.assertEqual(watches.unread_count("dev", "s"), 1)

    def test_read_events_stay_listed_unhighlighted(self):
        watches.toggle("dev", "s", part_type_id=PTID, label="AMC")
        _event(part_type_id=PTID, instance="dev", summary="old news")
        watches.mark_seen("dev", "s")
        m1, m2 = _profile_mocked(_profile_api())
        with m1, m2:
            html = self.client.get("/hw/dev/profile/").content.decode()
        self.assertIn("old news", html)
        self.assertNotIn("pf-ev-row is-unread", html)
        self.assertNotIn("Mark all read", html)
