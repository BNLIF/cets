"""Tests for the FD-VD hierarchy skeleton sync + explorer view (issue #29,
ADR-0010). HWDB fetch is mocked — no network.

    python manage.py test hwdb
"""

from __future__ import annotations

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from hwdb import hierarchy
from hwdb.fnal.bearer import FnalLinkRequired
from hwdb.models import ComponentTypeNode, HierarchySyncState


def _fake_api(systems, subsystems, part_types, counts):
    """systems: [{id,name}]; subsystems: {sysid_int: [{subsystem_id,subsystem_name}]};
    part_types: {(sysid_int, ssid): [{part_type_id, full_name}]};
    counts: {part_type_id: total}.
    """
    api = mock.MagicMock()
    api.get_systems.return_value = {"data": systems}
    api.get_subsystems.side_effect = lambda p1, p2: {"data": subsystems.get(int(p2), [])}
    api.get_part_types_for_subsystem.side_effect = (
        lambda p1, p2, ssid: {"data": part_types.get((int(p2), ssid), [])}
    )

    def _make_request(method, endpoint, data=None, params=None):
        # only used for component counts: component-types/<ptid>/components
        ptid = endpoint.split("/")[1]
        return {"pagination": {"total": counts.get(ptid, 0)}, "data": []}

    api._make_request.side_effect = _make_request
    return api


class WhitelistTest(TestCase):
    def test_fdvd_systems_included_others_excluded(self):
        self.assertTrue(hierarchy.is_fdvd_system("FD-VD TDE"))
        self.assertTrue(hierarchy.is_fdvd_system("FD-VD Complete Detector"))
        self.assertTrue(hierarchy.is_fdvd_system("FD CE"))
        self.assertFalse(hierarchy.is_fdvd_system("FD-HD APA"))
        self.assertFalse(hierarchy.is_fdvd_system("FD DAQ"))
        self.assertFalse(hierarchy.is_fdvd_system("ND: TMS"))
        self.assertFalse(hierarchy.is_fdvd_system(""))


class SyncHierarchyTest(TestCase):
    def _api(self):
        return _fake_api(
            systems=[
                {"id": 57, "name": "FD-VD TDE"},
                {"id": 99, "name": "ND: TMS"},  # excluded by whitelist
            ],
            subsystems={57: [{"subsystem_id": 2, "subsystem_name": "Digital electronics"}]},
            part_types={
                (57, 2): [
                    {"part_type_id": "D05700200001", "full_name": "D.FD-VD TDE.Digital electronics.AMC"},
                    {"part_type_id": "D05700200002", "full_name": "D.FD-VD TDE.Digital electronics.WR MCH"},
                ]
            },
            counts={"D05700200001": 3956, "D05700200002": 0},
        )

    def test_populates_nodes_with_true_counts_and_leaf_names(self):
        list(hierarchy.sync_hierarchy(self._api()))
        self.assertEqual(ComponentTypeNode.objects.count(), 2)
        amc = ComponentTypeNode.objects.get(part_type_id="D05700200001")
        self.assertEqual(amc.component_type_name, "AMC")  # last full_name segment
        self.assertEqual(amc.system_id, 57)
        self.assertEqual(amc.system_name, "FD-VD TDE")
        self.assertEqual(amc.subsystem_name, "Digital electronics")
        self.assertEqual(amc.n_components, 3956)  # from pagination.total, not page len

    def test_excluded_systems_never_walked(self):
        api = self._api()
        list(hierarchy.sync_hierarchy(api))
        # get_subsystems only called for the whitelisted system 057, never 099
        called = [c.args for c in api.get_subsystems.call_args_list]
        self.assertEqual(called, [("D", "057")])

    def test_updates_sync_state(self):
        list(hierarchy.sync_hierarchy(self._api()))
        st = HierarchySyncState.get()
        self.assertEqual(st.nodes_count, 2)
        self.assertEqual(st.systems_count, 1)
        self.assertIsNotNone(st.finished_at)
        self.assertEqual(st.last_error, "")

    def test_second_run_prunes_disappeared_nodes(self):
        list(hierarchy.sync_hierarchy(self._api()))
        # a leftover node from a previous shape that no longer exists upstream
        ComponentTypeNode.objects.create(
            part_type_id="D05700200099", system_id=57, system_name="FD-VD TDE",
            subsystem_id=2, subsystem_name="Digital electronics",
            component_type_name="GHOST", n_components=1,
        )
        self.assertEqual(ComponentTypeNode.objects.count(), 3)
        list(hierarchy.sync_hierarchy(self._api()))
        self.assertEqual(ComponentTypeNode.objects.count(), 2)
        self.assertFalse(ComponentTypeNode.objects.filter(part_type_id="D05700200099").exists())


class ExploreViewTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("explorer", "e@e.io", "pw")
        ComponentTypeNode.objects.create(
            part_type_id="D05700200001", system_id=57, system_name="FD-VD TDE",
            subsystem_id=2, subsystem_name="Digital electronics",
            component_type_name="AMC", full_name="D.FD-VD TDE.Digital electronics.AMC",
            n_components=3956,
        )

    def test_requires_login(self):
        resp = self.client.get(reverse("hwdb:explore"))
        self.assertEqual(resp.status_code, 302)

    def test_renders_tree_from_mirror(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("hwdb:explore"))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn("FD-VD TDE", html)
        self.assertIn("Digital electronics", html)
        self.assertIn("AMC", html)
        self.assertIn("3956", html)  # count badge
        self.assertIn("Refresh hierarchy", html)

    def test_selected_node_panel(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("hwdb:explore") + "?node=D05700200001")
        html = resp.content.decode()
        self.assertIn("D.FD-VD TDE.Digital electronics.AMC", html)
        # Unsynced node → the per-type test sync panel (see #30).
        self.assertIn("Sync now", html)


class ExploreSyncViewTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("syncer", "s@s.io", "pw")
        self.client.force_login(self.user)

    def test_get_not_allowed(self):
        resp = self.client.get(reverse("hwdb:explore_sync"))
        self.assertEqual(resp.status_code, 405)

    def test_unlinked_redirects_to_link(self):
        with mock.patch("hwdb.views.mint_for", side_effect=FnalLinkRequired("no link")):
            resp = self.client.post(reverse("hwdb:explore_sync"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("hwdb:link"), resp["Location"])

    def test_streams_sync_output_when_linked(self):
        with mock.patch("hwdb.views.mint_for", return_value="bearer"), \
             mock.patch("hwdb.views.FnalDbApiClient"), \
             mock.patch("hwdb.views.sync_hierarchy", return_value=iter(["line one\n", "done\n"])):
            resp = self.client.post(reverse("hwdb:explore_sync"))
            body = b"".join(resp.streaming_content).decode()
        self.assertEqual(resp.status_code, 200)
        self.assertIn("line one", body)
        self.assertIn("done", body)
