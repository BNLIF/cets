"""Tests for the per-component-type test-event sync + explorer plots
(issue #30, ADR-0010/0011). HWDB fetch is mocked — no network.

    python manage.py test explore
"""

from __future__ import annotations

from datetime import datetime, timezone as dt_timezone
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from explore import events, navigation
from explore.models import HierarchyNode as H
from explore.models import HwdbComponentEvent, HwdbTestEvent
from explore.queries import component_type_progress, component_update_progress
from hwdb.fnal.bearer import FnalLinkRequired


def _node(ptid="D05700200001", **kw):
    """Create the system+subsystem chain and a component-type leaf; return the leaf."""
    system_id = kw.pop("system_id", 57)
    system_name = kw.pop("system_name", "FD-VD TDE")
    subsystem_id = kw.pop("subsystem_id", 2)
    subsystem_name = kw.pop("subsystem_name", "Digital electronics")
    tname = kw.pop("component_type_name", "AMC")
    kw.setdefault("full_name", "D.FD-VD TDE.Digital electronics.AMC")
    kw.setdefault("n_components", 2)
    sys, _ = H.objects.get_or_create(
        level=H.LEVEL_SYSTEM, system_id=system_id, subsystem_id=None, part_type_id="",
        defaults={"system_name": system_name, "name": system_name})
    sub, _ = H.objects.get_or_create(
        level=H.LEVEL_SUBSYSTEM, system_id=system_id, subsystem_id=subsystem_id,
        part_type_id="", defaults={"parent": sys, "system_name": system_name,
                                   "subsystem_name": subsystem_name, "name": subsystem_name})
    return H.objects.create(
        level=H.LEVEL_TYPE, parent=sub, system_id=system_id, system_name=system_name,
        subsystem_id=subsystem_id, subsystem_name=subsystem_name, name=tname,
        part_type_id=ptid, **kw)


def _fake_client(part_ids, tests_by_part):
    """A client whose listing returns one page of part_ids and whose
    get_tests returns the canned tests for each part_id.
    """
    client = mock.MagicMock()

    def _make_request(method, endpoint, data=None, params=None):
        if endpoint.startswith("component-types/"):
            # component listing (part_ids only; created/updated come from detail)
            return {"data": [{"part_id": p} for p in part_ids], "pagination": {"pages": 1}}
        # component detail: components/{pid} → created + updated
        return {"data": {"created": "2025-02-01T00:00:00+00:00",
                         "updated": "2025-03-15T00:00:00+00:00"}}

    client._make_request.side_effect = _make_request
    client.get_tests.side_effect = lambda pid: {"data": tests_by_part.get(pid, [])}
    return client


class SyncTestEventsTest(TestCase):
    def setUp(self):
        _node()

    def _run(self, part_ids, tests_by_part, mode="incremental"):
        client = _fake_client(part_ids, tests_by_part)
        with mock.patch("explore.events.FnalDbApiClient", return_value=client):
            return list(events.sync_test_events("https://x", "bearer", "D05700200001", mode=mode))

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
        # registration events: one per listed component
        self.assertEqual(HwdbComponentEvent.objects.filter(part_type_id="D05700200001").count(), 2)
        node = H.objects.get(level=H.LEVEL_TYPE, part_type_id="D05700200001")
        self.assertEqual(node.n_tests, 3)
        self.assertIsNotNone(node.tests_synced_at)
        self.assertEqual(node.n_components, 2)

    def test_mirrors_status_manufacturer_institution_facets(self):
        # The categorical facets ride along on the detail record already fetched;
        # nested {id,name} refs are unwrapped, plain scalars pass through.
        client = mock.MagicMock()

        def _make_request(method, endpoint, data=None, params=None):
            if endpoint.startswith("component-types/"):
                return {"data": [{"part_id": "P1"}], "pagination": {"pages": 1}}
            return {"data": {"created": "2025-02-01T00:00:00+00:00",
                             "updated": "2025-03-15T00:00:00+00:00",
                             "status": {"id": 3, "name": "QA/QC Passed"},
                             "manufacturer": {"id": 5, "name": "BNL"},
                             "institution": "Yale"}}
        client._make_request.side_effect = _make_request
        client.get_tests.side_effect = lambda pid: {"data": []}
        with mock.patch("explore.events.FnalDbApiClient", return_value=client):
            list(events.sync_test_events("https://x", "bearer", "D05700200001", mode="full"))
        row = HwdbComponentEvent.objects.get(part_type_id="D05700200001", part_id="P1")
        self.assertEqual(row.status, "QA/QC Passed")   # nested ref → name
        self.assertEqual(row.manufacturer, "BNL")
        self.assertEqual(row.institution, "Yale")      # plain scalar

    def test_mirrors_qc_flags(self):
        # The binary QC flags are top-level booleans on the detail record (#51),
        # riding along with the facets — no extra fetch.
        client = mock.MagicMock()

        def _make_request(method, endpoint, data=None, params=None):
            if endpoint.startswith("component-types/"):
                return {"data": [{"part_id": "P1"}], "pagination": {"pages": 1}}
            return {"data": {"created": "2025-02-01T00:00:00+00:00",
                             "updated": "2025-03-15T00:00:00+00:00",
                             "is_installed": False,
                             "qaqc_uploaded": True,
                             "certified_qaqc": False}}
        client._make_request.side_effect = _make_request
        client.get_tests.side_effect = lambda pid: {"data": []}
        with mock.patch("explore.events.FnalDbApiClient", return_value=client):
            list(events.sync_test_events("https://x", "bearer", "D05700200001", mode="full"))
        row = HwdbComponentEvent.objects.get(part_type_id="D05700200001", part_id="P1")
        self.assertIs(row.is_installed, False)
        self.assertIs(row.qaqc_uploaded, True)
        self.assertIs(row.certified_qaqc, False)

    def test_qc_flags_null_when_absent_from_record(self):
        # A record without the flag fields stays NULL — distinct from False.
        self._run(["P1"], {})
        row = HwdbComponentEvent.objects.get(part_id="P1")
        self.assertIsNone(row.is_installed)
        self.assertIsNone(row.qaqc_uploaded)
        self.assertIsNone(row.certified_qaqc)

    def test_component_events_synced_even_with_no_tests(self):
        # 350-components-0-tests case (e.g. CRU Anode): registration plot
        # still has data while the test plot is empty.
        self._run(["P1", "P2", "P3"], {})
        self.assertEqual(HwdbTestEvent.objects.count(), 0)
        self.assertEqual(HwdbComponentEvent.objects.filter(part_type_id="D05700200001").count(), 3)

    def test_full_resync_rewrites_wholesale(self):
        self._run(["P1"], {"P1": [{"created": "2025-03-10T10:00:00+00:00", "test_type": {"name": "x"}}]})
        self.assertEqual(HwdbTestEvent.objects.count(), 1)
        # a FULL re-sync with different data fully replaces the first
        self._run(["P1"], {"P1": [
            {"created": "2025-05-10T10:00:00+00:00", "test_type": {"name": "y"}},
            {"created": "2025-05-11T10:00:00+00:00", "test_type": {"name": "y"}},
        ]}, mode="full")
        self.assertEqual(HwdbTestEvent.objects.count(), 2)
        self.assertFalse(HwdbTestEvent.objects.filter(test_type_name="x").exists())

    def test_incremental_skips_known_components(self):
        self._run(["P1"], {"P1": [{"created": "2025-03-10T10:00:00+00:00", "test_type": {"name": "x"}}]})
        self.assertEqual(HwdbComponentEvent.objects.count(), 1)
        # P1 now known; an incremental run with P1+P2 fetches only P2
        self._run(["P1", "P2"], {"P2": [{"created": "2025-04-01T10:00:00+00:00", "test_type": {"name": "x"}}]})
        self.assertEqual(HwdbComponentEvent.objects.count(), 2)        # P1 kept + P2 added
        self.assertEqual(HwdbTestEvent.objects.count(), 2)            # P1's kept + P2's added

    def test_components_mode_refreshes_detail_but_not_known_tests(self):
        self._run(["P1"], {"P1": [{"created": "2025-03-10T10:00:00+00:00", "test_type": {"name": "x"}}]})
        # components mode: detail for all (P1 refreshed + P2 added), tests for P2 only.
        self._run(["P1", "P2"], {
            "P1": [{"created": "2099-01-01T00:00:00+00:00", "test_type": {"name": "SHOULD_NOT_REFETCH"}}],
            "P2": [{"created": "2025-04-01T10:00:00+00:00", "test_type": {"name": "x"}}],
        }, mode="components")
        self.assertEqual(HwdbComponentEvent.objects.count(), 2)        # rewritten: P1 + P2
        self.assertEqual(HwdbTestEvent.objects.count(), 2)            # P1's original kept + P2's
        self.assertFalse(HwdbTestEvent.objects.filter(test_type_name="SHOULD_NOT_REFETCH").exists())

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
        ranges = component_type_progress("prod", ptid)
        self.assertEqual(set(ranges), {"month", "3month", "all"})  # no 1year projection
        names = [s["name"] for s in ranges["all"]["series"]]
        self.assertEqual(names, ["a", "b"])  # sorted
        self.assertEqual(sum(sum(s["counts"]) for s in ranges["all"]["series"]), 3)


class ComponentBreakdownTest(TestCase):
    def test_counts_per_facet_buckets_unset_and_skips_all_blank(self):
        from explore.queries import component_breakdowns
        ptid = "D05700299999"

        def mk(pid, status="", manu="", inst=""):
            HwdbComponentEvent.objects.create(part_type_id=ptid, part_id=pid,
                                              status=status, manufacturer=manu, institution=inst)
        mk("P1", status="Passed", manu="BNL")
        mk("P2", status="Passed", manu="BNL")
        mk("P3", status="Failed")               # no manufacturer → (unset)
        bd = {b["field"]: b for b in component_breakdowns("prod", ptid)}
        self.assertEqual(set(bd), {"status", "manufacturer"})   # institution all-blank → skipped
        self.assertEqual(bd["status"]["total"], 3)
        self.assertEqual({r["value"]: r["n"] for r in bd["status"]["rows"]},
                         {"Passed": 2, "Failed": 1})
        self.assertEqual({r["value"]: r["n"] for r in bd["manufacturer"]["rows"]},
                         {"BNL": 2, "(unset)": 1})


class ComponentQcFlagsTest(TestCase):
    """Yes/no/unknown counts for the binary QC flags (#51)."""

    def test_counts_yes_no_unknown(self):
        from explore.queries import component_qc_flags
        ptid = "D05700299998"
        HwdbComponentEvent.objects.create(part_type_id=ptid, part_id="P1",
                                          is_installed=True, qaqc_uploaded=True,
                                          certified_qaqc=True)
        HwdbComponentEvent.objects.create(part_type_id=ptid, part_id="P2",
                                          is_installed=False, qaqc_uploaded=True,
                                          certified_qaqc=False)
        HwdbComponentEvent.objects.create(part_type_id=ptid, part_id="P3")  # legacy NULLs
        flags = {f["field"]: f for f in component_qc_flags("prod", ptid)}
        self.assertEqual(set(flags), {"is_installed", "qaqc_uploaded", "certified_qaqc"})
        f = flags["is_installed"]
        self.assertEqual((f["yes"], f["no"], f["unknown"], f["total"]), (1, 1, 1, 3))
        self.assertEqual(flags["qaqc_uploaded"]["yes"], 2)
        self.assertEqual(flags["qaqc_uploaded"]["unknown"], 1)
        self.assertEqual(flags["is_installed"]["label"], "Installed")

    def test_empty_when_no_components(self):
        from explore.queries import component_qc_flags
        self.assertEqual(component_qc_flags("prod", "D00000000000"), [])


class PhysicsDatePathTest(TestCase):
    """For CE chip types the tests chart bins on the physics ``Test Date``
    (test_data), not the HWDB ``created`` upload stamp (the LArASIC gap the
    user flagged)."""

    def setUp(self):
        from django.conf import settings
        self.ptid = settings.HWDB_PROFILES["prod"]["larasic_part_type"]
        _node(self.ptid, system_id=81, system_name="FD CE",
              subsystem_name="LArASIC", component_type_name="LArASIC P5B Prod")

    def test_uses_physics_test_date_not_created(self):
        client = mock.MagicMock()

        def _make_request(method, endpoint, data=None, params=None):
            if endpoint.endswith("/components"):
                return {"data": [{"part_id": "P1"}], "pagination": {"pages": 1}}
            return {"data": {"created": "2026-05-29T00:00:00+00:00",
                             "updated": "2026-05-29T00:00:00+00:00"}}

        client._make_request.side_effect = _make_request
        client.get_test_types.return_value = {"data": [{"name": "CryoT QC Test", "id": 37}]}

        def _get_tests(pid, test_type_id=None, history=False):
            # detailed endpoint → carries test_data with the real Test Date
            return {"data": [{"created": "2026-05-29T00:00:00+00:00",
                              "test_data": {"Test Date": "2026/01/05"}}]}

        client.get_tests.side_effect = _get_tests
        with mock.patch("explore.events.FnalDbApiClient", return_value=client):
            list(events.sync_test_events("https://x", "b", self.ptid))

        evs = HwdbTestEvent.objects.filter(part_type_id=self.ptid)
        self.assertEqual(evs.count(), 1)
        e = evs.first()
        self.assertEqual((e.created.year, e.created.month, e.created.day), (2026, 1, 5))  # physics, not May 29
        self.assertEqual(e.test_type_name, "CryoT QC Test")

    def test_non_ce_type_has_no_physics_field(self):
        self.assertIsNone(events.physics_date_field("prod", "D05700200001"))   # TDE AMC
        self.assertEqual(events.physics_date_field("prod", self.ptid), "Test Date")


class ComponentUpdateProgressTest(TestCase):
    def test_single_series_by_component_updated_date(self):
        ptid = "D05500300001"
        for day in (10, 11, 12):
            HwdbComponentEvent.objects.create(
                part_type_id=ptid, part_id=f"P{day}",
                created=datetime(2025, 1, 1, tzinfo=dt_timezone.utc),
                updated=datetime(2025, 3, day, tzinfo=dt_timezone.utc),
            )
        ranges = component_update_progress("prod", ptid)
        series = ranges["all"]["series"]
        self.assertEqual(len(series), 1)
        self.assertEqual(series[0]["name"], "Components updated")
        self.assertEqual(sum(series[0]["counts"]), 3)
        # bins by `updated` (March), not `created` (January)
        self.assertIn("2025-03", ranges["all"]["labels"])
        self.assertNotIn("2025-01", ranges["all"]["labels"])

    def test_falls_back_to_created_when_updated_missing(self):
        ptid = "D05500300002"
        HwdbComponentEvent.objects.create(
            part_type_id=ptid, part_id="P1",
            created=datetime(2025, 5, 9, tzinfo=dt_timezone.utc), updated=None,
        )
        ranges = component_update_progress("prod", ptid)
        self.assertEqual(sum(ranges["all"]["series"][0]["counts"]), 1)


class ExplorePlotViewTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("plotter", "p@p.io", "pw")
        self.client.force_login(self.user)

    def test_synced_node_renders_both_charts(self):
        node = _node(tests_synced_at=timezone.now(), n_tests=1)
        HwdbTestEvent.objects.create(
            part_type_id=node.part_type_id, part_id="", test_type_name="amc_bandwidth_test",
            created=datetime(2025, 3, 10, tzinfo=dt_timezone.utc),
        )
        HwdbComponentEvent.objects.create(
            part_type_id=node.part_type_id, part_id="P1",
            created=datetime(2025, 1, 5, tzinfo=dt_timezone.utc),
        )
        html = self.client.get(navigation.leaf_path_for("prod", node.part_type_id)).content.decode()
        self.assertIn("node-chart-config", html)
        self.assertIn(f"bar_{node.part_type_id}_comp", html)   # components-updated chart
        self.assertIn(f"bar_{node.part_type_id}_test", html)   # tests-recorded chart
        self.assertIn("Components updated", html)
        self.assertIn("amc_bandwidth_test", html)

    def test_qc_flag_tiles_render_with_unsynced_hint(self):
        node = _node(tests_synced_at=timezone.now(), n_tests=0)
        HwdbComponentEvent.objects.create(
            part_type_id=node.part_type_id, part_id="P1",
            is_installed=False, qaqc_uploaded=True, certified_qaqc=False)
        HwdbComponentEvent.objects.create(  # mirrored pre-#51 → NULL flags
            part_type_id=node.part_type_id, part_id="P2")
        html = self.client.get(navigation.leaf_path_for("prod", node.part_type_id)).content.decode()
        self.assertIn("Installed", html)
        self.assertIn("QA/QC Uploaded", html)
        self.assertIn("Certified QA/QC", html)
        self.assertIn("1 not re-synced yet", html)  # the NULL row, honestly labeled

    def test_unsynced_node_shows_autosync_block(self):
        node = _node()  # tests_synced_at is NULL
        html = self.client.get(navigation.leaf_path_for("prod", node.part_type_id)).content.decode()
        self.assertIn('id="node-unsynced"', html)

    def test_errored_unsynced_node_does_not_autosync(self):
        # A leaf whose last sync failed must NOT auto-fire another sync on
        # render — that reload-loops forever on a persistent upstream error
        # (seen with dev HWDB's broken D00599800023 endpoint, #47).
        node = _node(tests_sync_error="500 response validation error")
        html = self.client.get(navigation.leaf_path_for("prod", node.part_type_id)).content.decode()
        self.assertNotIn('id="node-unsynced"', html)
        self.assertIn("Last test sync error", html)
        self.assertIn("retry with the sync buttons", html)

    def test_synced_but_empty_node(self):
        node = _node(tests_synced_at=timezone.now(), n_tests=0)
        html = self.client.get(navigation.leaf_path_for("prod", node.part_type_id)).content.decode()
        self.assertIn("No tests recorded", html)


class ExploreNodeSyncViewTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("ns", "n@n.io", "pw")
        self.client.force_login(self.user)
        _node()

    def test_get_not_allowed(self):
        resp = self.client.get(reverse("explore:node_sync", args=["D05700200001"]))
        self.assertEqual(resp.status_code, 405)

    def test_unlinked_redirects_with_node_next(self):
        with mock.patch("explore.views.mint_for", side_effect=FnalLinkRequired("no link")):
            resp = self.client.post(reverse("explore:node_sync", args=["D05700200001"]))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("node%3DD05700200001", resp["Location"])  # ?next=...?node=...

    def test_streams_when_linked(self):
        with mock.patch("explore.views.mint_for", return_value="bearer"), \
             mock.patch("explore.views.sync_test_events", return_value=iter(["scanning\n", "done\n"])):
            resp = self.client.post(reverse("explore:node_sync", args=["D05700200001"]))
            body = b"".join(resp.streaming_content).decode()
        self.assertEqual(resp.status_code, 200)
        self.assertIn("done", body)
