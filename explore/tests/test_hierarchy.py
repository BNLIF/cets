"""Tests for the structure-mirror sync + explorer view (issue #29/#37,
ADR-0010/0012). HWDB fetch is mocked — no network.

    python manage.py test explore
"""

from __future__ import annotations

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from explore import hierarchy
from explore.models import HierarchyNode as H
from explore.models import HierarchySyncState
from hwdb.fnal.bearer import FnalLinkRequired


def _chain(ptid, sid=57, sname="FD-VD TDE", ssid=2, ssname="Digital electronics",
           tname="AMC", **leaf):
    """Create (or reuse) the system+subsystem nodes and a component-type leaf."""
    sys, _ = H.objects.get_or_create(
        level=H.LEVEL_SYSTEM, system_id=sid, subsystem_id=None, part_type_id="",
        defaults={"system_name": sname, "name": sname})
    sub, _ = H.objects.get_or_create(
        level=H.LEVEL_SUBSYSTEM, system_id=sid, subsystem_id=ssid, part_type_id="",
        defaults={"parent": sys, "system_name": sname,
                  "subsystem_name": ssname, "name": ssname})
    return H.objects.create(
        level=H.LEVEL_TYPE, parent=sub, system_id=sid, system_name=sname,
        subsystem_id=ssid, subsystem_name=ssname, name=tname, part_type_id=ptid, **leaf)


def _fake_api(systems, subsystems, part_types, counts):
    api = mock.MagicMock()
    api.get_systems.return_value = {"data": systems}
    api.get_subsystems.side_effect = lambda p1, p2: {"data": subsystems.get(int(p2), [])}
    api.get_part_types_for_subsystem.side_effect = (
        lambda p1, p2, ssid: {"data": part_types.get((int(p2), ssid), [])}
    )

    def _make_request(method, endpoint, data=None, params=None):
        ptid = endpoint.split("/")[1]  # component-types/<ptid>/components
        return {"pagination": {"total": counts.get(ptid, 0)}, "data": []}

    api._make_request.side_effect = _make_request
    return api


class WhitelistTest(TestCase):
    def test_fdvd_systems_included_others_excluded(self):
        self.assertTrue(hierarchy.is_fdvd_system("FD-VD TDE"))
        self.assertTrue(hierarchy.is_fdvd_system("FD CE"))
        self.assertFalse(hierarchy.is_fdvd_system("FD-HD APA"))
        self.assertFalse(hierarchy.is_fdvd_system("ND: TMS"))
        self.assertFalse(hierarchy.is_fdvd_system(""))


class SyncHierarchyTest(TestCase):
    def _api(self):
        return _fake_api(
            systems=[
                {"id": 57, "name": "FD-VD TDE"},
                {"id": 60, "name": "FD-VD Empty"},   # whitelisted but no part types
                {"id": 99, "name": "ND: TMS"},        # excluded by whitelist
            ],
            subsystems={
                57: [{"subsystem_id": 2, "subsystem_name": "Digital electronics"}],
                60: [{"subsystem_id": 1, "subsystem_name": "Placeholder"}],
            },
            part_types={
                (57, 2): [
                    {"part_type_id": "D05700200001", "full_name": "D.FD-VD TDE.Digital electronics.AMC"},
                    {"part_type_id": "D05700200002", "full_name": "D.FD-VD TDE.Digital electronics.WR MCH"},
                ],
                (60, 1): [],
            },
            counts={"D05700200001": 3956, "D05700200002": 0},
        )

    def test_populates_levels_with_true_counts_and_leaf_names(self):
        list(hierarchy.sync_hierarchy(self._api()))
        self.assertEqual(H.objects.filter(level=H.LEVEL_TYPE).count(), 2)
        amc = H.objects.get(level=H.LEVEL_TYPE, part_type_id="D05700200001")
        self.assertEqual(amc.name, "AMC")              # last full_name segment
        self.assertEqual(amc.system_name, "FD-VD TDE")
        self.assertEqual(amc.subsystem_name, "Digital electronics")
        self.assertEqual(amc.n_components, 3956)        # pagination.total, not page len
        # parent chain is wired up
        self.assertEqual(amc.parent.level, H.LEVEL_SUBSYSTEM)
        self.assertEqual(amc.parent.parent.level, H.LEVEL_SYSTEM)

    def test_empty_system_is_navigable(self):
        # The #37 fix: a whitelisted system with no component types still gets a
        # node (and its empty subsystem), so it shows up in the tree.
        list(hierarchy.sync_hierarchy(self._api()))
        empty = H.objects.get(level=H.LEVEL_SYSTEM, system_id=60)
        self.assertEqual(empty.name, "FD-VD Empty")
        self.assertEqual(empty.children.filter(level=H.LEVEL_SUBSYSTEM).count(), 1)
        self.assertEqual(H.objects.filter(level=H.LEVEL_TYPE, system_id=60).count(), 0)

    def test_excluded_systems_never_walked(self):
        api = self._api()
        list(hierarchy.sync_hierarchy(api))
        called = [c.args for c in api.get_subsystems.call_args_list]
        self.assertEqual(called, [("D", "057"), ("D", "060")])  # not 099

    def test_updates_sync_state(self):
        list(hierarchy.sync_hierarchy(self._api()))
        st = HierarchySyncState.get()
        self.assertEqual(st.nodes_count, 2)     # component types
        self.assertEqual(st.systems_count, 2)   # 057 + 060
        self.assertIsNotNone(st.finished_at)
        self.assertEqual(st.last_error, "")

    def test_second_run_prunes_disappeared_nodes(self):
        list(hierarchy.sync_hierarchy(self._api()))
        _chain("D05700200099", tname="GHOST")  # a leftover not in the walk
        self.assertEqual(H.objects.filter(level=H.LEVEL_TYPE).count(), 3)
        list(hierarchy.sync_hierarchy(self._api()))
        self.assertEqual(H.objects.filter(level=H.LEVEL_TYPE).count(), 2)
        self.assertFalse(H.objects.filter(part_type_id="D05700200099").exists())


class ExploreViewTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("explorer", "e@e.io", "pw")
        _chain("D05700200001", tname="AMC", n_components=3956)

    def test_requires_login(self):
        resp = self.client.get(reverse("explore:home"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("explore:login"), resp["Location"])

    def test_renders_tree_from_mirror(self):
        self.client.force_login(self.user)
        html = self.client.get(reverse("explore:home")).content.decode()
        self.assertEqual(self.client.get(reverse("explore:home")).status_code, 200)
        self.assertIn("FD-VD TDE", html)
        self.assertIn("Digital electronics", html)
        self.assertIn("AMC", html)
        self.assertIn("3956", html)
        self.assertIn("Refresh hierarchy", html)

    def test_empty_system_shows_in_tree(self):
        H.objects.create(level=H.LEVEL_SYSTEM, system_id=54, system_name="FD-VD PDS",
                         name="FD-VD PDS")
        self.client.force_login(self.user)
        html = self.client.get(reverse("explore:home")).content.decode()
        self.assertIn("FD-VD PDS", html)   # empty system still navigable

    def test_selected_node_panel(self):
        self.client.force_login(self.user)
        html = self.client.get(reverse("explore:home") + "?node=D05700200001").content.decode()
        self.assertIn("FD-VD TDE", html)
        self.assertIn("Digital electronics", html)
        self.assertIn("node-sync-btn", html)


class ExploreSyncViewTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("syncer", "s@s.io", "pw")
        self.client.force_login(self.user)

    def test_get_not_allowed(self):
        self.assertEqual(self.client.get(reverse("explore:sync")).status_code, 405)

    def test_unlinked_redirects_to_link(self):
        with mock.patch("explore.views.mint_for", side_effect=FnalLinkRequired("no link")):
            resp = self.client.post(reverse("explore:sync"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("hwdb:link"), resp["Location"])

    def test_streams_sync_output_when_linked(self):
        with mock.patch("explore.views.mint_for", return_value="bearer"), \
             mock.patch("explore.views.FnalDbApiClient"), \
             mock.patch("explore.views.sync_hierarchy", return_value=iter(["line one\n", "done\n"])):
            resp = self.client.post(reverse("explore:sync"))
            body = b"".join(resp.streaming_content).decode()
        self.assertEqual(resp.status_code, 200)
        self.assertIn("done", body)
