"""Tests for the structure-mirror sync + explorer view (issue #29/#37,
ADR-0010/0012). HWDB fetch is mocked — no network.

    python manage.py test explore
"""

from __future__ import annotations

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from explore import curation, hierarchy, navigation
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


class CurationTest(TestCase):
    def test_curated_systems_from_yaml(self):
        # The real curation.yaml: FD-VD systems + FD CE curated; FD-HD/ND not.
        ids = curation.curated_system_ids()
        self.assertIn(57, ids)   # FD-VD TDE
        self.assertIn(81, ids)   # FD CE
        self.assertNotIn(1, ids)    # FD-HD Complete Detector
        self.assertNotIn(100, ids)  # ND


class SyncHierarchyTest(TestCase):
    def setUp(self):
        # Drive the walk from a controlled curated set, not the real yaml.
        p = mock.patch("explore.hierarchy.curation.curated_system_ids",
                       return_value={57, 60})
        p.start()
        self.addCleanup(p.stop)

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


class NavigationTest(TestCase):
    """Drill-in navigation + deep-link URLs (issue #40)."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("explorer", "e@e.io", "pw")
        self.client.force_login(self.user)
        # FD-VD TDE (multi-system family) and FD CE (flattened family).
        _chain("D05700200001", tname="AMC", n_components=3956)
        _chain("D08100100003", sid=81, sname="FD CE", ssid=1, ssname="LArASIC",
               tname="LArASIC P5B Prod", tests_synced_at=None, n_components=100)

    def _html(self, url):
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode()

    def test_requires_login(self):
        self.client.logout()
        resp = self.client.get(reverse("explore:home"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("explore:login"), resp["Location"])

    def test_root_shows_region_cards(self):
        html = self._html(reverse("explore:home"))
        self.assertIn("Far Detector", html)
        self.assertIn("Near Detector", html)   # declared region…
        self.assertIn("not curated", html)      # …dimmed, not browsable
        self.assertIn("Refresh hierarchy", html)

    def test_region_shows_family_cards(self):
        html = self._html(navigation.node_path("FD"))
        self.assertIn("FD-VD", html)
        self.assertIn("FD CE", html)

    def test_multi_system_family_shows_system_cards(self):
        html = self._html(navigation.node_path("FD", "FD-VD"))
        self.assertIn("FD-VD TDE", html)         # system tier present

    def test_single_system_family_flattens_to_subsystems(self):
        # FD CE owns one system → its subsystems render directly under the family.
        html = self._html(navigation.node_path("FD", "FD-CE"))
        self.assertIn("LArASIC", html)            # subsystem card directly under family
        self.assertNotIn(">System<", html)        # no System-tier card

    def test_drill_system_subsystem_leaf(self):
        sub = self._html(navigation.node_path("FD", "FD-VD", system_id=57))
        self.assertIn("Digital electronics", sub)
        leaves = self._html(navigation.node_path("FD", "FD-VD", system_id=57, subsystem_id=2))
        self.assertIn("AMC", leaves)
        leaf_url = navigation.node_path("FD", "FD-VD", system_id=57, subsystem_id=2,
                                        part_type_id="D05700200001")
        detail = self._html(leaf_url)
        self.assertIn("Part type ID", detail)        # leaf detail panel
        self.assertIn("node-sync-btn", detail)

    def test_legacy_node_query_redirects_to_path(self):
        resp = self.client.get(reverse("explore:home") + "?node=D05700200001")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"],
                         navigation.node_path("FD", "FD-VD", system_id=57,
                                               subsystem_id=2, part_type_id="D05700200001"))

    def test_unknown_path_404(self):
        self.assertEqual(self.client.get(navigation.node_path("NOPE")).status_code, 404)

    def test_non_curated_region_not_browsable(self):
        # Near Detector is declared but curated: false → its node 404s.
        self.assertEqual(self.client.get(navigation.node_path("ND")).status_code, 404)

    def test_uncurated_system_not_reachable(self):
        H.objects.create(level=H.LEVEL_SYSTEM, system_id=999,
                         system_name="Phantom System", name="Phantom System")
        # 999 isn't in any curated family → not in the FD-VD systems grid.
        self.assertNotIn("Phantom System", self._html(navigation.node_path("FD", "FD-VD")))


class SidebarTest(TestCase):
    """Expandable, path-following sidebar tree (issue #41)."""

    def setUp(self):
        _chain("D05700200001", tname="AMC", n_components=42)  # FD-VD TDE / Digital electronics
        _chain("D08100100003", sid=81, sname="FD CE", ssid=1, ssname="LArASIC",
               tname="LArASIC P5B Prod", n_components=100)

    def _tree(self, trail):
        return navigation.sidebar_tree(navigation.resolve(trail)["ctx"])

    def _find(self, nodes, label):
        for n in nodes:
            if n["label"] == label:
                return n
            hit = self._find(n["children"], label)
            if hit:
                return hit
        return None

    def test_full_tree_built_with_all_regions_and_families(self):
        tree = self._tree("")  # root
        regions = [n["label"] for n in tree]
        self.assertEqual(regions, ["Far Detector", "Near Detector", "Other"])
        fd = self._find(tree, "Far Detector")
        fams = [f["label"] for f in fd["children"]]
        self.assertEqual(fams, ["FD-VD", "FD CE", "FD-HD", "FD shared"])

    def test_path_open_and_current_highlighted(self):
        tree = self._tree("FD/FD-VD/57/2/D05700200001")  # a leaf
        self.assertTrue(self._find(tree, "Far Detector")["open"])
        self.assertTrue(self._find(tree, "FD-VD")["open"])
        self.assertTrue(self._find(tree, "FD-VD TDE")["open"])
        self.assertTrue(self._find(tree, "Digital electronics")["open"])
        self.assertTrue(self._find(tree, "AMC")["current"])
        # a sibling family on the path's region is present but NOT open
        self.assertFalse(self._find(tree, "FD CE")["open"])

    def test_counts_on_nodes(self):
        tree = self._tree("")
        self.assertGreater(self._find(tree, "FD-VD TDE")["count"], 0)

    def test_non_curated_is_dim_and_unlinked(self):
        nd = self._find(self._tree(""), "Near Detector")
        self.assertTrue(nd["dim"])
        self.assertIsNone(nd["url"])

    def test_sidebar_rendered_with_chevrons(self):
        u = get_user_model().objects.create_user("sb", "s@s.io", "pw")
        self.client.force_login(u)
        html = self.client.get(navigation.node_path("FD", "FD-VD", system_id=57)).content.decode()
        self.assertIn('id="ex-side"', html)
        self.assertIn("extree-folder", html)   # collapsible folders
        self.assertIn("<details", html)
        self.assertIn("side-toggle", html)


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
