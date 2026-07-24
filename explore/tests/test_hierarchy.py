"""Tests for the structure-mirror sync + explorer view (issue #29/#37,
ADR-0010/0012). HWDB fetch is mocked — no network.

    python manage.py test explore
"""

from __future__ import annotations

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

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


def _fake_api(systems, subsystems, part_types, counts, projects=None, type_records=None):
    """``projects`` maps extra project letters to their ``systems/{P}`` lists
    (#71); unlisted projects return empty — ``systems`` is project D's.
    ``type_records`` maps ptid → the ``component-types/{ptid}`` record (#72),
    fetched by the walk for cable-category types."""
    api = mock.MagicMock()
    api.get_systems.side_effect = (
        lambda p1="D": {"data": systems if p1 == "D" else (projects or {}).get(p1, [])})
    api.get_subsystems.side_effect = lambda p1, p2: {"data": subsystems.get(int(p2), [])}
    api.get_part_types_for_subsystem.side_effect = (
        lambda p1, p2, ssid: {"data": part_types.get((int(p2), ssid), [])}
    )
    api.get_component_type.side_effect = (
        lambda ptid: {"data": (type_records or {}).get(ptid, {})})

    def _make_request(method, endpoint, data=None, params=None):
        ptid = endpoint.split("/")[1]  # component-types/<ptid>/components
        return {"pagination": {"total": counts.get(ptid, 0)}, "data": []}

    api._make_request.side_effect = _make_request
    return api


class CurationTest(TestCase):
    def test_curated_systems_from_yaml(self):
        # The real curation.yaml: FD, ND and Others all curated (2026-07-02).
        ids = curation.curated_system_ids("prod")
        self.assertIn(57, ids)   # FD-VD TDE
        self.assertIn(81, ids)   # FD CE
        self.assertIn(1, ids)    # FD-HD Complete Detector
        self.assertIn(82, ids)   # FD shared (FD DAQ)
        self.assertIn(100, ids)  # ND: Near detector complex
        self.assertIn(500, ids)  # Others › Computing
        self.assertIn(900, ids)  # Others › Prototypes (ProtoDUNE-II)
        self.assertNotIn(999, ids)  # not a DUNE system


class SyncHierarchyTest(TestCase):
    def setUp(self):
        # Drive the walk from a controlled curated set, not the real yaml.
        p = mock.patch("explore.hierarchy.curation.curated_system_ids",
                       return_value={57, 60})
        p.start()
        self.addCleanup(p.stop)

    def _run(self, api):
        # Threads build clients via FnalDbApiClient; patch it to reuse the mock.
        with mock.patch("explore.hierarchy.FnalDbApiClient", return_value=api):
            list(hierarchy.sync_hierarchy(api, "prod"))

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
        self._run(self._api())
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
        self._run(self._api())
        empty = H.objects.get(level=H.LEVEL_SYSTEM, system_id=60)
        self.assertEqual(empty.name, "FD-VD Empty")
        self.assertEqual(empty.children.filter(level=H.LEVEL_SUBSYSTEM).count(), 1)
        self.assertEqual(H.objects.filter(level=H.LEVEL_TYPE, system_id=60).count(), 0)

    def test_cable_type_mirrors_category_and_ends(self):
        api = self._api()
        api.get_part_types_for_subsystem.side_effect = lambda p1, p2, ssid: {"data": [
            {"part_type_id": "D05700200001", "category": "cable",
             "full_name": "D.FD-VD TDE.Digital electronics.HV bundle"},
            {"part_type_id": "D05700200002", "category": "generic",
             "full_name": "D.FD-VD TDE.Digital electronics.WR MCH"},
        ] if (int(p2), ssid) == (57, 2) else []}
        api.get_component_type.side_effect = lambda ptid: {"data": {
            "connectors": {"Flange:1": None, "Flange:2": None, "PS:1": None}}}
        self._run(api)
        cable = H.objects.get(part_type_id="D05700200001")
        self.assertEqual(cable.category, "cable")
        self.assertEqual(cable.cable_ends, [{"name": "Flange", "connectors": 2},
                                            {"name": "PS", "connectors": 1}])
        generic = H.objects.get(part_type_id="D05700200002")
        self.assertEqual(generic.category, "generic")
        self.assertIsNone(generic.cable_ends)
        # only the cable type cost an extra type-record call
        called = {c.args[0] for c in api.get_component_type.call_args_list}
        self.assertEqual(called, {"D05700200001"})

    def test_failed_ends_fetch_keeps_previous_value(self):
        api = self._api()
        api.get_part_types_for_subsystem.side_effect = lambda p1, p2, ssid: {"data": [
            {"part_type_id": "D05700200001", "category": "cable",
             "full_name": "D.FD-VD TDE.Digital electronics.HV bundle"},
        ] if (int(p2), ssid) == (57, 2) else []}
        api.get_component_type.side_effect = lambda ptid: {"data": {
            "connectors": {"Flange:1": None}}}
        self._run(api)
        api.get_component_type.side_effect = RuntimeError("502")
        self._run(api)  # re-sync with the type record failing
        cable = H.objects.get(part_type_id="D05700200001")
        self.assertEqual(cable.cable_ends, [{"name": "Flange", "connectors": 1}])

    def test_excluded_systems_never_walked(self):
        api = self._api()
        self._run(api)
        # Parallel walk → order isn't guaranteed; compare the set.
        called = {c.args for c in api.get_subsystems.call_args_list}
        self.assertEqual(called, {("D", "057"), ("D", "060")})  # not 099

    def test_updates_sync_state(self):
        self._run(self._api())
        st = HierarchySyncState.get("prod")
        self.assertEqual(st.nodes_count, 2)     # component types
        self.assertEqual(st.systems_count, 2)   # 057 + 060
        self.assertIsNotNone(st.finished_at)
        self.assertEqual(st.last_error, "")

    def test_persistent_fetch_failure_aborts_without_pruning(self):
        # Regression for the FD-CE wipe: a dropped fetch must NOT lead to pruning
        # good data. A persistently-failing subsystem fetch aborts the whole sync
        # (after retries), leaving existing nodes intact and recording the error.
        _chain("D05700200001", tname="AMC")  # pre-existing good data
        api = self._api()
        api.get_subsystems.side_effect = RuntimeError("HWDB 503")
        with mock.patch("explore.hierarchy.time.sleep"), \
             mock.patch("explore.hierarchy.FnalDbApiClient", return_value=api):
            with self.assertRaises(Exception):
                list(hierarchy.sync_hierarchy(api, "prod"))
        self.assertTrue(H.objects.filter(part_type_id="D05700200001").exists())  # not pruned
        self.assertNotEqual(HierarchySyncState.get("prod").last_error, "")

    def test_count_failure_keeps_leaf_and_previous_count(self):
        # Upstream bug seen on the dev HWDB (#47): a type whose /components
        # endpoint persistently 500s (its own response-validation rejects
        # category "box" rows) must NOT abort the walk. The leaf is kept with
        # its previous count, other counts land, and the sync finishes clean.
        _chain("D05700200001", tname="AMC", n_components=3956)
        api = self._api()

        def _mr(method, endpoint, data=None, params=None):
            ptid = endpoint.split("/")[1]
            if ptid == "D05700200001":
                raise RuntimeError("500 response validation error")
            return {"pagination": {"total": {"D05700200002": 7}.get(ptid, 0)}, "data": []}

        api._make_request.side_effect = _mr
        with mock.patch("explore.hierarchy.time.sleep"), \
             mock.patch("explore.hierarchy.FnalDbApiClient", return_value=api):
            lines = list(hierarchy.sync_hierarchy(api, "prod"))
        amc = H.objects.get(level=H.LEVEL_TYPE, part_type_id="D05700200001")
        self.assertEqual(amc.n_components, 3956)   # previous count retained
        other = H.objects.get(level=H.LEVEL_TYPE, part_type_id="D05700200002")
        self.assertEqual(other.n_components, 7)    # good counts still land
        self.assertEqual(HierarchySyncState.get("prod").last_error, "")
        self.assertTrue(any("count failed for D05700200001" in l for l in lines))

    def test_second_run_prunes_disappeared_nodes(self):
        self._run(self._api())
        _chain("D05700200099", tname="GHOST")  # a leftover not in the walk
        self.assertEqual(H.objects.filter(level=H.LEVEL_TYPE).count(), 3)
        self._run(self._api())
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

    def test_browse_root_shows_region_cards(self):
        html = self._html(reverse("explore:browse"))   # drill-in navigator (home is now the tree)
        self.assertIn("Far Detector", html)
        self.assertIn("Near Detector", html)   # curated 2026-07-02
        self.assertIn("Others", html)
        self.assertIn("Refresh hierarchy", html)

    def test_home_is_hierarchy_tree_with_leaf_links(self):
        html = self._html(reverse("explore:home"))
        self.assertIn("DUNE Hardware Overview", html)   # the tree page, not the card root
        self.assertIn("tr-data", html)                   # embedded tree json
        self.assertIn("Far Detector", html)
        self.assertIn("Others", html)                    # curated 2026-07-02
        leaf_url = navigation.node_path("prod", "FD", "FD-CE", subsystem_id=1,
                                        part_type_id="D08100100003")
        self.assertIn(leaf_url, html)                     # leaf row links to its page

    def test_curated_tree_flattens_and_locks(self):
        tree = navigation.curated_tree("prod")
        self.assertEqual(tree["kind"], "root")
        # D regions sit under a "DUNE (D)" project node (#71).
        dune = tree["children"][0]
        self.assertEqual((dune["kind"], dune["name"]), ("project", "DUNE (D)"))
        regions = {r["key"]: r for r in dune["children"]}
        self.assertFalse(regions["FD"]["locked"])
        self.assertFalse(regions["ND"]["locked"])        # curated 2026-07-02
        self.assertFalse(regions["OT"]["locked"])
        self.assertEqual(regions["OT"]["name"], "Others")
        fams = {f["key"]: f for f in regions["FD"]["children"]}
        # FD CE owns one system → children are subsystems directly (flattened)
        self.assertTrue(all(c["kind"] == "sub" for c in fams["FD-CE"]["children"]))
        # FD-VD is multi-system → children are systems
        self.assertTrue(any(c["kind"] == "system" for c in fams["FD-VD"]["children"]))
        leaf = fams["FD-CE"]["children"][0]["children"][0]
        self.assertEqual(leaf["kind"], "type")
        self.assertTrue(leaf["url"].endswith("/D08100100003/"))

    def test_curated_tree_folder_urls_match_sidebar_paths(self):
        # Folder urls double as the shared expansion key with the sidebar —
        # they must be exactly the node_path the sidebar uses.
        tree = navigation.curated_tree("prod")
        dune = tree["children"][0]
        fd = next(r for r in dune["children"] if r["key"] == "FD")
        self.assertEqual(fd["url"], navigation.node_path("prod", "FD"))
        fams = {f["key"]: f for f in fd["children"]}
        self.assertEqual(fams["FD-VD"]["url"], navigation.node_path("prod", "FD", "FD-VD"))
        sys57 = next(s for s in fams["FD-VD"]["children"] if s.get("id") == 57)
        self.assertEqual(sys57["url"],
                         navigation.node_path("prod", "FD", "FD-VD", system_id=57))
        sub = sys57["children"][0]
        self.assertEqual(sub["url"], navigation.node_path(
            "prod", "FD", "FD-VD", system_id=57, subsystem_id=sub["id"]))
        # Flat family: subsystem url skips the system tier, like the sidebar.
        flat_sub = fams["FD-CE"]["children"][0]
        self.assertEqual(flat_sub["url"], navigation.node_path(
            "prod", "FD", "FD-CE", subsystem_id=flat_sub["id"]))
        nd = next(r for r in dune["children"] if r["key"] == "ND")
        self.assertEqual(nd["url"], navigation.node_path("prod", "ND"))

    def test_curated_tree_empty_and_synced_flags(self):
        # setUp's AMC (57/2) has components but is unsynced. Add a fully-synced
        # subsystem and an all-empty one, both under FD-VD TDE (system 57).
        _chain("D05700200090", tname="SYNCEDLEAF", ssid=9, ssname="Synced sub",
               n_components=5, tests_synced_at=timezone.now())
        _chain("D05700200091", tname="EMPTYLEAF", ssid=10, ssname="Empty sub",
               n_components=0)
        tree = navigation.curated_tree("prod")
        fd = next(r for r in tree["children"][0]["children"] if r["key"] == "FD")
        sys57 = next(s for s in next(f for f in fd["children"] if f["key"] == "FD-VD")["children"]
                     if s.get("id") == 57)
        subs = {s["name"]: s for s in sys57["children"]}
        self.assertTrue(subs["Synced sub"]["synced"])       # its one leaf is synced → green
        self.assertFalse(subs["Synced sub"]["empty"])
        self.assertTrue(subs["Empty sub"]["empty"])          # 0 components → grey
        self.assertFalse(subs["Empty sub"]["synced"])
        self.assertFalse(sys57["synced"])   # mix of synced + unsynced leaves
        self.assertFalse(sys57["empty"])    # but it does have components

    def test_region_shows_family_cards(self):
        html = self._html(navigation.node_path("prod", "FD"))
        self.assertIn("FD-VD", html)
        self.assertIn("FD CE", html)

    def test_multi_system_family_shows_system_cards(self):
        html = self._html(navigation.node_path("prod", "FD", "FD-VD"))
        self.assertIn("FD-VD TDE", html)         # system tier present

    def test_single_system_family_flattens_to_subsystems(self):
        # FD CE owns one system → its subsystems render directly under the family.
        html = self._html(navigation.node_path("prod", "FD", "FD-CE"))
        self.assertIn("LArASIC", html)            # subsystem card directly under family
        self.assertNotIn(">System<", html)        # no System-tier card

    def test_drill_system_subsystem_leaf(self):
        sub = self._html(navigation.node_path("prod", "FD", "FD-VD", system_id=57))
        self.assertIn("Digital electronics", sub)
        leaves = self._html(navigation.node_path("prod", "FD", "FD-VD", system_id=57, subsystem_id=2))
        self.assertIn("AMC", leaves)
        leaf_url = navigation.node_path("prod", "FD", "FD-VD", system_id=57, subsystem_id=2,
                                        part_type_id="D05700200001")
        detail = self._html(leaf_url)
        self.assertIn("Part type ID", detail)        # leaf detail panel
        self.assertIn("node-sync-btn", detail)

    def test_leaf_links_the_es_config_editor(self):
        # Any leaf on a write instance links the ES-config editor — even types
        # without a config yet (saving one there marks the type as needing an ES).
        leaf_url = navigation.node_path("prod", "FD", "FD-VD", system_id=57,
                                        subsystem_id=2, part_type_id="D05700200001")
        self.assertIn("/hw/es-config/D05700200001/", self._html(leaf_url))

    @override_settings(HWDB_WRITE_INSTANCES=["dev"])
    def test_es_config_link_absent_off_write_instances(self):
        leaf_url = navigation.node_path("prod", "FD", "FD-VD", system_id=57,
                                        subsystem_id=2, part_type_id="D05700200001")
        self.assertNotIn("es-config", self._html(leaf_url))

    def test_legacy_node_query_redirects_to_path(self):
        resp = self.client.get(reverse("explore:home") + "?node=D05700200001")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"],
                         navigation.node_path("prod", "FD", "FD-VD", system_id=57,
                                               subsystem_id=2, part_type_id="D05700200001"))

    def test_unknown_path_404(self):
        self.assertEqual(self.client.get(navigation.node_path("prod", "NOPE")).status_code, 404)

    def test_nd_and_others_regions_browsable(self):
        # ND and Others curated 2026-07-02 — their nodes render family cards.
        html = self._html(navigation.node_path("prod", "ND"))
        self.assertIn("ND Detectors", html)
        self.assertIn("NS", html)
        self.assertIn("Prototypes", self._html(navigation.node_path("prod", "OT")))

    def test_non_curated_region_not_browsable(self):
        # A declared-but-uncurated region (none in prod today) stays a dimmed
        # placeholder: no url, 404 on direct access.
        locked = [{"name": "Mock Region", "key": "MOCK", "curated": False, "note": "n"}]
        with mock.patch("explore.curation.regions", return_value=locked):
            self.assertEqual(self.client.get("/hw/MOCK/").status_code, 404)

    def test_uncurated_system_not_reachable(self):
        H.objects.create(level=H.LEVEL_SYSTEM, system_id=999,
                         system_name="Phantom System", name="Phantom System")
        # 999 isn't in any curated family → not in the FD-VD systems grid.
        self.assertNotIn("Phantom System", self._html(navigation.node_path("prod", "FD", "FD-VD")))


class SidebarTest(TestCase):
    """Expandable, path-following sidebar tree (issue #41)."""

    def setUp(self):
        _chain("D05700200001", tname="AMC", n_components=42)  # FD-VD TDE / Digital electronics
        _chain("D08100100003", sid=81, sname="FD CE", ssid=1, ssname="LArASIC",
               tname="LArASIC P5B Prod", n_components=100)

    def _tree(self, trail):
        return navigation.sidebar_tree("prod", navigation.resolve("prod", trail)["ctx"])

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
        # Projects share the top level (#71): D regions group under DUNE;
        # no extra project is mirrored in this fixture, so DUNE stands alone.
        self.assertEqual([n["label"] for n in tree], ["DUNE (D)"])
        self.assertTrue(tree[0]["open"])
        regions = [n["label"] for n in tree[0]["children"]]
        self.assertEqual(regions, ["Far Detector", "Near Detector", "Others"])
        fd = self._find(tree, "Far Detector")
        fams = [f["label"] for f in fd["children"]]
        self.assertEqual(fams, ["FD-VD", "FD CE", "FD-HD", "FD Common", "FS"])
        nd = self._find(tree, "Near Detector")
        self.assertEqual([f["label"] for f in nd["children"]],
                         ["ND Detectors", "ND Common", "NS"])

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

    def test_node_state_empty_unsynced_synced(self):
        from django.utils import timezone
        _chain("D05700200090", tname="SYNCEDLEAF", n_components=5,
               tests_synced_at=timezone.now())
        _chain("D05700200091", tname="EMPTYLEAF", n_components=0)
        tree = self._tree("")
        amc = self._find(tree, "AMC")            # 42 components, never synced
        self.assertFalse(amc["empty"]); self.assertFalse(amc["synced"])
        syn = self._find(tree, "SYNCEDLEAF")     # has components, synced → green
        self.assertFalse(syn["empty"]); self.assertTrue(syn["synced"])
        emp = self._find(tree, "EMPTYLEAF")      # no components → greyed
        self.assertTrue(emp["empty"]); self.assertFalse(emp["synced"])
        # subsystem with a not-fully-synced mix is neither empty nor synced
        digi = self._find(tree, "Digital electronics")
        self.assertFalse(digi["empty"]); self.assertFalse(digi["synced"])

    def test_non_curated_is_dim_and_unlinked(self):
        # No live placeholders since ND/Others were curated (2026-07-02) —
        # keep the dimmed-placeholder rendering covered with a mocked region.
        locked = [{"name": "Mock Region", "key": "MOCK", "curated": False, "note": "n"}]
        with mock.patch("explore.curation.regions", return_value=locked):
            mock_region = self._find(self._tree(""), "Mock Region")
        self.assertTrue(mock_region["dim"])
        self.assertIsNone(mock_region["url"])

    def test_sidebar_rendered_with_chevrons(self):
        u = get_user_model().objects.create_user("sb", "s@s.io", "pw")
        self.client.force_login(u)
        html = self.client.get(navigation.node_path("prod", "FD", "FD-VD", system_id=57)).content.decode()
        self.assertIn('id="ex-side"', html)
        self.assertIn("extree-folder", html)   # collapsible folders
        self.assertIn("<details", html)
        self.assertIn("side-toggle", html)
        self.assertIn("FD-VD TDE (57)", html)          # HWDB id in the label (#50)
        self.assertIn("Digital electronics (57.2)", html)
        # Folders carry the shared expansion key (their explorer URL) so the
        # sidebar and Overview trees sync and persist across pages.
        self.assertIn(
            'data-key="%s"' % navigation.node_path("prod", "FD", "FD-VD", system_id=57),
            html)


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


class OverflowSyncTest(TestCase):
    """Overflow discovery during the full refresh (#49) — uses the real dev
    curation block (curated = {5}, overflow on)."""

    def _run(self, api):
        with mock.patch("explore.hierarchy.FnalDbApiClient", return_value=api):
            return list(hierarchy.sync_hierarchy(api, "dev"))

    def _api(self, include_stray=True):
        # System 21 ("DAQ") is a dev-only stray — uncurated since the
        # 2026-07-02 curation of ND/Others.
        systems = [{"id": 5, "name": "FD1-HD HVS"}]
        if include_stray:
            systems.append({"id": 21, "name": "DAQ"})
        return _fake_api(
            systems=systems,
            subsystems={5: [{"subsystem_id": 998, "subsystem_name": "HWDBUnitTest"}]},
            part_types={(5, 998): [{"part_type_id": "D00599800007",
                                    "full_name": "D.FD1-HD HVS.HWDBUnitTest.Test Type 007"}]},
            counts={"D00599800007": 147},
        )

    def test_records_uncurated_systems_without_walking(self):
        api = self._api()
        lines = self._run(api)
        row = H.objects.get(instance="dev", level=H.LEVEL_SYSTEM, system_id=21)
        self.assertIsNone(row.structure_synced_at)
        self.assertFalse(H.objects.filter(instance="dev", system_id=21)
                         .exclude(level=H.LEVEL_SYSTEM).exists())
        called = {c.args for c in api.get_subsystems.call_args_list}
        self.assertEqual(called, {("D", "005")})   # 021 listed, never walked
        self.assertTrue(any("overflow" in l for l in lines))

    def test_prune_spares_lazily_walked_overflow_subtree(self):
        self._run(self._api())
        sys21 = H.objects.get(instance="dev", level=H.LEVEL_SYSTEM, system_id=21)
        sub = H.objects.create(
            instance="dev", level=H.LEVEL_SUBSYSTEM, parent=sys21, system_id=21,
            subsystem_id=2, system_name=sys21.system_name, subsystem_name="Servers", name="Servers")
        H.objects.create(
            instance="dev", level=H.LEVEL_TYPE, parent=sub, system_id=21,
            subsystem_id=2, system_name=sys21.system_name, subsystem_name="Servers",
            name="Event Builder", part_type_id="D02100200001")
        self._run(self._api())   # a later global refresh
        self.assertTrue(H.objects.filter(instance="dev",
                                         part_type_id="D02100200001").exists())

    def test_vanished_overflow_system_pruned(self):
        self._run(self._api())
        self._run(self._api(include_stray=False))
        self.assertFalse(H.objects.filter(instance="dev", system_id=21).exists())

    def test_prod_records_no_overflow(self):
        # prod has no overflow knob: uncurated systems stay invisible.
        api = _fake_api(systems=[{"id": 57, "name": "FD-VD TDE"},
                                 {"id": 99, "name": "ND: TMS"}],
                        subsystems={57: []}, part_types={}, counts={})
        with mock.patch("explore.hierarchy.FnalDbApiClient", return_value=api):
            list(hierarchy.sync_hierarchy(api, "prod"))
        self.assertFalse(H.objects.filter(instance="prod", system_id=99).exists())


class SyncSystemTest(TestCase):
    """The one-system lazy walk behind the overflow section (#49)."""

    def setUp(self):
        self.sys51 = H.objects.create(
            instance="dev", level=H.LEVEL_SYSTEM, system_id=51,
            system_name="FD2-VD Complete Detector", name="FD2-VD Complete Detector")

    def _api(self):
        return _fake_api(
            systems=[],
            subsystems={51: [{"subsystem_id": 2, "subsystem_name": "CRP"}]},
            part_types={(51, 2): [{"part_type_id": "D05100200001",
                                   "full_name": "D.FD2-VD.CRP.Adapter Board"}]},
            counts={"D05100200001": 3},
        )

    def _run(self, api):
        with mock.patch("explore.hierarchy.FnalDbApiClient", return_value=api):
            return list(hierarchy.sync_system(api, "dev", 51))

    def test_walks_one_system_and_marks_it(self):
        # A stale leaf under 51 is pruned; other systems are untouched.
        stale = H.objects.create(
            instance="dev", level=H.LEVEL_TYPE, system_id=51, subsystem_id=9,
            system_name="FD2-VD Complete Detector", subsystem_name="Old",
            name="GHOST", part_type_id="D05100900099")
        other = H.objects.create(
            instance="dev", level=H.LEVEL_SYSTEM, system_id=52,
            system_name="Other", name="Other")
        self._run(self._api())
        leaf = H.objects.get(instance="dev", level=H.LEVEL_TYPE,
                             part_type_id="D05100200001")
        self.assertEqual(leaf.n_components, 3)
        self.assertEqual(leaf.name, "Adapter Board")
        self.assertFalse(H.objects.filter(pk=stale.pk).exists())
        self.assertTrue(H.objects.filter(pk=other.pk).exists())
        self.sys51.refresh_from_db()
        self.assertIsNotNone(self.sys51.structure_synced_at)
        self.assertEqual(self.sys51.tests_sync_error, "")

    def test_failure_records_error_and_raises(self):
        api = self._api()
        api.get_subsystems.side_effect = RuntimeError("HWDB 503")
        with mock.patch("explore.hierarchy.time.sleep"), \
             mock.patch("explore.hierarchy.FnalDbApiClient", return_value=api):
            with self.assertRaises(Exception):
                list(hierarchy.sync_system(api, "dev", 51))
        self.sys51.refresh_from_db()
        self.assertIsNone(self.sys51.structure_synced_at)
        self.assertNotEqual(self.sys51.tests_sync_error, "")

    def test_unknown_system_is_a_noop(self):
        lines = self._run_unknown()
        self.assertIn("unknown system", lines[0])

    def _run_unknown(self):
        api = self._api()
        with mock.patch("explore.hierarchy.FnalDbApiClient", return_value=api):
            return list(hierarchy.sync_system(api, "dev", 999))


class MultiProjectSyncTest(TestCase):
    """Extra HWDB projects (Z, L) recorded by the refresh and walked lazily,
    with per-project system-id scoping (#71)."""

    def setUp(self):
        p = mock.patch("explore.hierarchy.curation.curated_system_ids",
                       return_value={57})
        p.start()
        self.addCleanup(p.stop)
        q = mock.patch("explore.hierarchy.curation.extra_projects",
                       return_value=["Z"])
        q.start()
        self.addCleanup(q.stop)

    def _run(self, api):
        with mock.patch("explore.hierarchy.FnalDbApiClient", return_value=api):
            return list(hierarchy.sync_hierarchy(api, "prod"))

    def _api(self, z_systems=None):
        # Z's system 57 deliberately collides with D's — ids are per-project.
        return _fake_api(
            systems=[{"id": 57, "name": "FD-VD TDE"}],
            subsystems={57: [{"subsystem_id": 2, "subsystem_name": "Digital electronics"}]},
            part_types={(57, 2): [{"part_type_id": "D05700200001",
                                   "full_name": "D.FD-VD TDE.Digital electronics.AMC"}]},
            counts={"D05700200001": 5},
            projects={"Z": z_systems if z_systems is not None
                      else [{"id": 57, "name": "Z Machine"}]},
        )

    def test_records_extra_project_systems_without_walking(self):
        api = self._api()
        lines = self._run(api)
        zrow = H.objects.get(instance="prod", project="Z",
                             level=H.LEVEL_SYSTEM, system_id=57)
        self.assertIsNone(zrow.structure_synced_at)
        drow = H.objects.get(instance="prod", project="D",
                             level=H.LEVEL_SYSTEM, system_id=57)
        self.assertNotEqual(zrow.pk, drow.pk)        # no cross-project clobber
        self.assertEqual(drow.system_name, "FD-VD TDE")
        self.assertEqual(zrow.system_name, "Z Machine")
        called = {c.args for c in api.get_subsystems.call_args_list}
        self.assertEqual(called, {("D", "057")})     # Z listed, never walked
        self.assertTrue(any("project Z" in l for l in lines))

    def test_listing_failure_keeps_previous_rows(self):
        self._run(self._api())

        def _fail(p1="D"):
            if p1 == "D":
                return {"data": [{"id": 57, "name": "FD-VD TDE"}]}
            raise RuntimeError("HWDB 503")

        api = self._api()
        api.get_systems.side_effect = _fail
        with mock.patch("explore.hierarchy.time.sleep"):
            lines = self._run(api)
        self.assertTrue(H.objects.filter(instance="prod", project="Z",
                                         system_id=57).exists())
        self.assertTrue(any("WARNING: project Z" in l for l in lines))

    def test_vanished_extra_project_system_pruned_with_subtree(self):
        self._run(self._api())
        zsys = H.objects.get(instance="prod", project="Z",
                             level=H.LEVEL_SYSTEM, system_id=57)
        zsub = H.objects.create(
            instance="prod", project="Z", level=H.LEVEL_SUBSYSTEM, parent=zsys,
            system_id=57, subsystem_id=1, system_name="Z Machine",
            subsystem_name="Z Optics", name="Z Optics")
        H.objects.create(
            instance="prod", project="Z", level=H.LEVEL_TYPE, parent=zsub,
            system_id=57, subsystem_id=1, system_name="Z Machine",
            subsystem_name="Z Optics", name="Z Widget", part_type_id="Z05700100001")
        # Still listed → the lazily-walked subtree survives the refresh.
        self._run(self._api())
        self.assertTrue(H.objects.filter(part_type_id="Z05700100001").exists())
        # Gone from the listing → system + subtree pruned; D's 57 untouched.
        self._run(self._api(z_systems=[]))
        self.assertFalse(H.objects.filter(instance="prod", project="Z").exists())
        self.assertTrue(H.objects.filter(instance="prod", project="D",
                                         level=H.LEVEL_SYSTEM, system_id=57).exists())

    def test_sync_system_scopes_by_project(self):
        self._run(self._api())
        api = _fake_api(
            systems=[],
            subsystems={57: [{"subsystem_id": 1, "subsystem_name": "Z Optics"}]},
            part_types={(57, 1): [{"part_type_id": "Z05700100001",
                                   "full_name": "Z.Z Machine.Z Optics.Z Widget"}]},
            counts={"Z05700100001": 4},
        )
        with mock.patch("explore.hierarchy.FnalDbApiClient", return_value=api):
            list(hierarchy.sync_system(api, "prod", 57, project="Z"))
        leaf = H.objects.get(part_type_id="Z05700100001")
        self.assertEqual(leaf.project, "Z")
        self.assertEqual(leaf.n_components, 4)
        called = {c.args for c in api.get_subsystems.call_args_list}
        self.assertEqual(called, {("Z", "057")})
        # The Z walk's prune must not eat D's subtree under the same system id.
        self.assertTrue(H.objects.filter(part_type_id="D05700200001").exists())
        zsys = H.objects.get(instance="prod", project="Z",
                             level=H.LEVEL_SYSTEM, system_id=57)
        self.assertIsNotNone(zsys.structure_synced_at)


class ProjectRegionTest(TestCase):
    """Synthetic per-project regions and project-scoped navigation (#71).
    Pins a controlled ``extra_projects`` block (the real yaml shifts — prod
    now lists only LBNF), so the machinery is tested independent of curation
    edits."""

    def setUp(self):
        real_block = curation._block

        def fake_block(instance):
            b = dict(real_block(instance))
            b["extra_projects"] = [{"id": "Z", "name": "Test Project", "test": True},
                                   {"id": "L", "name": "LBNF"}]
            return b

        p = mock.patch.object(curation, "_block", side_effect=fake_block)
        p.start()
        self.addCleanup(p.stop)
        self.user = get_user_model().objects.create_user("explorer", "e@e.io", "pw")
        self.client.force_login(self.user)
        _chain("D05700200001", tname="AMC", n_components=10)   # D system 57
        # Z system 57: same numeric id as D's, already lazily walked.
        zsys = H.objects.create(
            level=H.LEVEL_SYSTEM, project="Z", system_id=57,
            system_name="Z Machine", name="Z Machine",
            structure_synced_at=timezone.now())
        zsub = H.objects.create(
            level=H.LEVEL_SUBSYSTEM, project="Z", parent=zsys, system_id=57,
            subsystem_id=2, system_name="Z Machine",
            subsystem_name="Z Optics", name="Z Optics")
        H.objects.create(
            level=H.LEVEL_TYPE, project="Z", parent=zsub, system_id=57,
            subsystem_id=2, system_name="Z Machine", subsystem_name="Z Optics",
            name="Z Widget", part_type_id="Z05700200042", n_components=7)

    def test_project_region_listed_when_mirrored(self):
        regions = {r["key"]: r for r in navigation.all_regions("prod")}
        self.assertIn("Z", regions)
        # Label = upstream project name from the yaml (prod's Z = Test Project).
        self.assertEqual(regions["Z"]["name"], "Test Project (Z)")
        self.assertEqual([f["key"] for f in regions["Z"]["families"]], ["57"])
        self.assertNotIn("L", regions)   # curated but nothing mirrored yet

    def test_drill_into_project_region(self):
        html = self.client.get(navigation.node_path("prod", "Z")).content.decode()
        self.assertIn("Z Machine", html)
        html = self.client.get(
            navigation.node_path("prod", "Z", "57", subsystem_id=2)).content.decode()
        self.assertIn("Z Widget", html)

    def test_leaf_path_for_resolves_project_leaf(self):
        path = navigation.leaf_path_for("prod", "Z05700200042")
        self.assertEqual(path, navigation.node_path(
            "prod", "Z", "57", subsystem_id=2, part_type_id="Z05700200042"))
        # D leaf still resolves into its curated FD region, not Project Z.
        self.assertIn("/FD/", navigation.leaf_path_for("prod", "D05700200001"))

    def test_counts_do_not_bleed_across_projects(self):
        tree = navigation.sidebar_tree("prod", {})
        # Top level = project peers (#71): DUNE folder + the mirrored Z.
        self.assertEqual([n["label"] for n in tree],
                         ["DUNE (D)", "Test Project (Z)"])
        dune = tree[0]
        fd = next(r for r in dune["children"] if r["label"] == "Far Detector")
        fdvd = next(f for f in fd["children"] if f["label"] == "FD-VD")
        sys57 = next(s for s in fdvd["children"] if s["label"] == "FD-VD TDE")
        self.assertEqual(sys57["count"], 10)     # D only, no Z bleed
        self.assertEqual(tree[1]["count"], 7)

    def test_project_region_order_follows_yaml(self):
        # List order in ``extra_projects`` is display order (dev puts LBNF
        # above the sandbox), not alphabetical.
        H.objects.create(level=H.LEVEL_SYSTEM, project="L", system_id=3,
                         system_name="FD Cryostat", name="FD Cryostat")
        keys = [r["key"] for r in navigation.project_regions("prod")]
        self.assertEqual(keys, ["Z", "L"])   # patched block lists Z first

    def test_sandbox_project_marked_test_for_overview_stats(self):
        # ``test: true`` in the yaml → the overview tree marks the subtree so
        # the stats tally skips it; DUNE (and non-test projects) carry no flag.
        tree = navigation.curated_tree("prod")
        z = next(r for r in tree["children"] if r.get("key") == "Z")
        self.assertTrue(z["test"])
        self.assertNotIn("test", tree["children"][0])   # DUNE (D)

    def test_dune_folder_closes_on_project_pages(self):
        ctx = navigation.resolve("prod", "Z/57")["ctx"]
        tree = navigation.sidebar_tree("prod", ctx)
        self.assertFalse(tree[0]["open"])                  # DUNE (D)
        self.assertTrue(tree[1]["open"])                   # Test Project (Z)

    def test_unwalked_project_system_auto_walks_with_project_param(self):
        H.objects.filter(project="Z", level=H.LEVEL_SYSTEM).update(
            structure_synced_at=None)
        html = self.client.get(navigation.node_path("prod", "Z", "57")).content.decode()
        self.assertIn("project=Z", html)

    def test_project_system_never_lands_in_uncurated_overflow(self):
        H.objects.create(instance="dev", level=H.LEVEL_SYSTEM, project="Z",
                         system_id=99, system_name="Z Stray", name="Z Stray")
        region = navigation.overflow_region("dev")
        keys = {f["key"] for f in (region or {}).get("families", [])}
        self.assertNotIn("99", keys)
        self.assertEqual([r["key"] for r in navigation.project_regions("dev")], ["Z"])
