"""Tests for the generic part detail page (ADR-0014).

The engine (parts.py) and the view for a *non-shipping* part — the shipping-box
case is exercised in test_shipments.py (is_shipping=True). HWDB fetch is mocked.

    python manage.py test explore
"""

from __future__ import annotations

import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from explore import navigation, parts, shipments
from explore.models import HierarchyNode as H
from explore.models import ActivityEvent, HwdbComponentEvent
from hwdb.fnal.bearer import FnalLinkRequired


class SpecSectionsTest(TestCase):
    def test_scalars_fold_into_one_specifications_card(self):
        blob = {"Operating Voltage": "48V", "Channels": 64, "Notes": ""}
        secs = parts.spec_sections(blob)
        self.assertEqual([s["title"] for s in secs], ["Specifications"])
        labels = {f["label"]: f["value"] for f in secs[0]["fields"]}
        self.assertEqual(labels, {"Operating Voltage": "48V", "Channels": "64"})

    def test_nested_keys_become_their_own_cards_with_image_peeling(self):
        blob = {
            "Calibration": [{"gain": "1.2", "Image ID for the trace": "img-7"}],
            "Serial scan": {"barcode": "ABC123"},
        }
        secs = {s["title"]: s for s in parts.spec_sections(blob)}
        self.assertEqual(secs["Calibration"]["fields"], [{"label": "gain", "value": "1.2"}])
        self.assertEqual(secs["Calibration"]["attachments"], [{"label": "trace", "image_id": "img-7"}])
        self.assertEqual(secs["Serial scan"]["fields"], [{"label": "barcode", "value": "ABC123"}])

    def test_empty_blob(self):
        self.assertEqual(parts.spec_sections(None), [])

    def test_bare_list_blob_folds_into_one_card(self):
        secs = parts.spec_sections([{"a": "1"}, {"b": "2"}])
        self.assertEqual(secs[0]["title"], "Specifications")
        self.assertEqual({f["label"]: f["value"] for f in secs[0]["fields"]},
                         {"a": "1", "b": "2"})

    def test_non_dict_blob_is_ignored(self):
        self.assertEqual(parts.spec_sections("a string"), [])

    def test_full_block_renders_datasheet_keys_and_one_data_card(self):
        # The FNAL web UI writes Item Specifications as datasheet-level keys
        # next to _meta; checklists nest under DATA. Both render — DATA as ONE
        # card (its hierarchy visible, #98 review), _meta hidden.
        block = {
            "Vendor": "Acme",
            "_meta": {"v": 2},
            "DATA": {"Calibration": [{"gain": "1.2"}], "Channels": 64,
                     "Measurements — H": {"Thickness": {"P1": 1.6}, "Image ID for shot": "img-3"},
                     "Measurements — J": {"Thickness": {"P1": 2.0}}},
        }
        secs = {s["title"]: s for s in parts.spec_sections(block)}
        self.assertNotIn("_meta", secs)
        self.assertEqual({f["label"]: f["value"] for f in secs["Specifications"]["fields"]},
                         {"Vendor": "Acme"})
        rows = {f["label"]: f["value"] for f in secs["DATA"]["fields"]}
        self.assertEqual(rows, {
            "Calibration": '[{"gain": "1.2"}]', "Channels": "64",
            "Measurements — H › Thickness": '{"P1": 1.6}',
            "Measurements — J › Thickness": '{"P1": 2.0}'})       # H and J both kept
        self.assertEqual(secs["DATA"]["attachments"], [{"label": "shot", "image_id": "img-3"}])
        self.assertIn('"Channels": 64', secs["DATA"]["json"])
        # #102: rows know their origin for the delete control
        by = {f["label"]: f["spec_del"] for f in secs["DATA"]["fields"]}
        self.assertEqual(by["Channels"], {"section": "", "label": "Channels"})
        self.assertEqual(by["Measurements — H › Thickness"],
                         {"section": "Measurements — H", "label": "Thickness"})
        self.assertNotIn("spec_del", secs["Specifications"]["fields"][0])   # datasheet keys: no

    def test_bare_list_data_keeps_its_specifications_card(self):
        secs = parts.spec_sections({"DATA": [{"a": "1"}]})
        self.assertEqual([s["title"] for s in secs], ["Specifications"])
        self.assertEqual(secs[0]["fields"], [{"label": "a", "value": "1"}])

    def test_object_and_array_values_carry_a_json_payload(self):
        # Structured values render as a compact preview + click-to-view modal;
        # an array of scalars is a flat field, not a dropped card.
        secs = {s["title"]: s for s in parts.spec_sections({
            "Curve": [1, 2, 3],
            "Scan": {"nested": {"a": 1}},
        })}
        curve = secs["Specifications"]["fields"][0]
        self.assertEqual(curve["label"], "Curve")
        self.assertEqual(curve["value"], "[1, 2, 3]")
        self.assertEqual(curve["json"], "[\n  1,\n  2,\n  3\n]")
        nested = secs["Scan"]["fields"][0]
        self.assertEqual(nested["value"], '{"a": 1}')
        self.assertIn('"a": 1', nested["json"])
        # Every card carries its raw JSON for the copy button — the flat
        # "Specifications" card copies the loose keys' original values.
        self.assertIn('"nested"', secs["Scan"]["json"])
        self.assertEqual(json.loads(secs["Specifications"]["json"]),
                         {"Curve": [1, 2, 3]})

    def test_scalar_fields_carry_no_json_payload(self):
        secs = parts.spec_sections({"Vendor": "Acme"})
        self.assertNotIn("json", secs[0]["fields"][0])


class LatestSpecTest(TestCase):
    """Reads follow the write convention: specifications[-1] is current."""

    BODY = {"data": {"specifications": [
        {"Vendor": "old", "DATA": {"Stage": "created"}},
        {"Vendor": "new", "DATA": {"Stage": "edited"}},
    ]}}

    def test_spec_block_returns_the_latest_entry(self):
        self.assertEqual(shipments._spec_block(self.BODY)["Vendor"], "new")

    def test_spec_data_returns_the_latest_data_blob(self):
        self.assertEqual(shipments._spec_data(self.BODY), {"Stage": "edited"})

    def test_empty_and_malformed_specs_yield_none(self):
        self.assertIsNone(shipments._spec_block({"data": {"specifications": []}}))
        self.assertIsNone(shipments._spec_block({"data": {"specifications": ["x"]}}))
        self.assertIsNone(shipments._spec_data(None))


class TestSummaryTest(TestCase):
    def test_latest_record_per_type_wins(self):
        recs = [
            {"test_type": "HV", "status": "Pass", "created": "2026-01-01T00:00:00"},
            {"test_type": "HV", "status": "Fail", "created": "2026-05-01T00:00:00"},  # newer
            {"test_type": "Cold", "status": "Pass", "created": "2026-03-01T00:00:00"},
        ]
        summary = {r["test_type"]: r for r in parts.test_summary(recs)}
        self.assertEqual(summary["HV"]["status"], "Fail")          # newest HV
        self.assertEqual([r["test_type"] for r in parts.test_summary(recs)], ["Cold", "HV"])

    def test_handles_missing_fields(self):
        self.assertEqual(parts.test_summary(None), [])

    def test_unwraps_nested_test_type_and_status_refs(self):
        # HWDB returns test_type/status as {id, name} refs for some parts —
        # must not be used as an unhashable dict key.
        recs = [{"test_type": {"id": 7, "name": "HV"},
                 "status": {"name": "Pass"}, "created": "2026-01-01T00:00:00"}]
        summary = parts.test_summary(recs)
        self.assertEqual(summary[0]["test_type"], "HV")
        self.assertEqual(summary[0]["status"], "Pass")


class EnrichTestDataTest(TestCase):
    """The list endpoint omits the test oid + status; we backfill them from the
    per-type endpoint so the FNAL data link works."""

    def _api(self):
        api = mock.MagicMock()
        api.get_component.return_value = {"data": {"specifications": []}}
        api.get_locations.return_value = {"data": []}
        api.get_subcomponents.return_value = {"data": []}
        api.get_images.return_value = {"data": []}
        api.get_test_types.return_value = {"data": [{"name": "HV QC Test", "id": 42}]}

        def get_tests(pid, test_type_id=None, history=False):
            if test_type_id is None:  # list endpoint — no id, no status, no files
                return {"data": [{"test_type": {"name": "HV QC Test"},
                                  "created": "2026-05-29T00:00:00", "comments": "Cold"}]}
            return {"data": [{"id": 15023, "status": {"name": "Passed"},
                              "created": "2026-05-29T00:00:00",
                              "test_data": {"DATA": {"gain": 1.2}},
                              "images": [{"image_id": "z", "image_name": "hv.csv"}]}]}
        api.get_tests.side_effect = get_tests
        return api

    def test_oid_status_and_has_data_backfilled_from_per_type(self):
        d = parts.part_detail(self._api(), "D08100100003-00226", is_shipping=False)
        t = d["tests"][0]
        self.assertEqual(t["test_id"], 15023)    # → FNAL component_test data link
        self.assertEqual(t["test_type_id"], 42)  # → our test_data JSON download
        self.assertEqual(t["status"], "Passed")  # real status, not the empty list value
        self.assertTrue(t["has_data"])           # embedded files → show the link
        self.assertTrue(t["has_test_data"])      # test_data present → JSON download

    def test_no_files_means_no_data_link(self):
        api = self._api()

        def get_tests(pid, test_type_id=None, history=False):
            if test_type_id is None:
                return {"data": [{"test_type": {"name": "HV QC Test"},
                                  "created": "2026-05-29T00:00:00"}]}
            return {"data": [{"id": 15023, "status": {"name": "Passed"},
                              "created": "2026-05-29T00:00:00"}]}  # no images
        api.get_tests.side_effect = get_tests
        t = parts.part_detail(api, "D08100100003-14194", is_shipping=False)["tests"][0]
        self.assertEqual(t["test_id"], 15023)
        self.assertFalse(t["has_data"])          # no files → link hidden


class PartFactsTest(TestCase):
    def test_skips_blanks_and_unwraps_named_refs(self):
        comp = {
            "serial_number": "SN-9",
            "component_type": {"name": "ColdADC"},
            "institution": {"name": "BNL"},
            "manufacturer": "",                 # blank → skipped
            "status": {"id": 120, "name": "QA/QC Tests - Passed All"},  # nested ref
            "created": "2026-04-02T11:00:00",
            "creator": {"name": "Chao Zhang"},  # nested ref
        }
        facts = {f["label"]: f["value"] for f in parts.part_facts(comp)}
        self.assertEqual(facts["Serial number"], "SN-9")
        self.assertEqual(facts["Type"], "ColdADC")
        self.assertEqual(facts["Institution"], "BNL")
        self.assertEqual(facts["Status"], "QA/QC Tests - Passed All")  # name only, not the dict
        self.assertEqual(facts["Created"], "2026-04-02")
        self.assertEqual(facts["Created by"], "Chao Zhang")  # name only, not the dict
        self.assertNotIn("Manufacturer", facts)

    def test_category_fact_from_the_item_record(self):
        facts = {f["label"]: f["value"] for f in parts.part_facts({"category": "cable"})}
        self.assertEqual(facts["Category"], "cable")
        facts = {f["label"]: f["value"] for f in parts.part_facts({"serial_number": "S"})}
        self.assertNotIn("Category", facts)  # absent field skipped, not shown blank

    def test_qc_flags_render_yes_no_and_skip_absent(self):
        # False is meaningful (→ "No"); only a missing field is skipped.
        comp = {"serial_number": "SN-9", "is_installed": False,
                "qaqc_uploaded": True}  # certified_qaqc absent
        facts = {f["label"]: f["value"] for f in parts.part_facts(comp)}
        self.assertEqual(facts["Installed"], "No")
        self.assertEqual(facts["QA/QC Uploaded"], "Yes")
        self.assertNotIn("Certified QA/QC", facts)


class NormalizeStatusTest(TestCase):
    """#75: HWDB's obsolete pre-vocabulary statuses (ids 1-3) read as
    Unknown; the current vocabulary (0 and 100+) passes through."""

    def test_obsolete_ids_become_unknown(self):
        for i, name in ((1, "Available"), (2, "Temporarily Unavailable"),
                        (3, "Permanently Unavailable")):
            self.assertEqual(parts.normalize_status({"id": i, "name": name}),
                             "Unknown")

    def test_current_vocabulary_ids_pass_through(self):
        self.assertEqual(parts.normalize_status({"id": 0, "name": "Unknown"}),
                         "Unknown")
        # Modern id 170 shares the obsolete id 3's name — the id decides.
        self.assertEqual(
            parts.normalize_status({"id": 170, "name": "Permanently Unavailable"}),
            "Permanently Unavailable")
        self.assertEqual(
            parts.normalize_status({"id": 120, "name": "QA/QC Tests - Passed All"}),
            "QA/QC Tests - Passed All")

    def test_unambiguous_legacy_names_become_unknown(self):
        # Mirror rows carry bare names; only the unambiguous legacy ones map.
        self.assertEqual(parts.normalize_status("Available"), "Unknown")
        self.assertEqual(parts.normalize_status("Temporarily Unavailable"), "Unknown")

    def test_other_values_pass_through(self):
        # "Permanently Unavailable" by bare name could be modern id 170.
        for v in ("QA/QC Tests - Passed All", "Permanently Unavailable", "", None):
            self.assertEqual(parts.normalize_status(v), v)

    def test_part_page_shows_unknown_for_available(self):
        api = mock.MagicMock()
        api.get_component.return_value = {"data": {
            "serial_number": "SN-1", "status": {"id": 1, "name": "Available"},
            "component_type": {"name": "Test Type 003"}}}
        api.get_locations.return_value = {"data": []}
        api.get_subcomponents.return_value = {"data": []}
        api.get_images.return_value = {"data": []}
        api.get_tests.return_value = {"data": []}
        api.get_test_types.return_value = {"data": []}
        d = parts.part_detail(api, "D00599800003-00210", is_shipping=False)
        self.assertEqual(d["status"], "Unknown")
        self.assertIn(("Status", "Unknown"),
                      [(f["label"], f["value"]) for f in d["facts"]])


class SubcompRefTest(TestCase):
    """shipments.split_subcomp_ref / current_manifest with cable-end refs
    (#72): ``<PID>.<END name>:<connector #>`` on the connected component,
    ``<PID>.<position>`` peer back-references on the cable's own rows."""

    def test_cable_end_ref_splits(self):
        self.assertEqual(shipments.split_subcomp_ref("Z00100300080-00001.FCP Flange:1"),
                         ("Z00100300080-00001", "FCP Flange:1"))

    def test_peer_ref_splits(self):
        self.assertEqual(shipments.split_subcomp_ref("Z00100300064-00001.Cold Bottom FCT"),
                         ("Z00100300064-00001", "Cold Bottom FCT"))

    def test_plain_pid_passes_through(self):
        self.assertEqual(shipments.split_subcomp_ref("D05700200001-00042"),
                         ("D05700200001-00042", None))
        self.assertEqual(shipments.split_subcomp_ref(None), (None, None))

    def test_non_pid_prefix_left_whole(self):
        self.assertEqual(shipments.split_subcomp_ref("foo.bar"), ("foo.bar", None))

    def test_manifest_rows_carry_base_pid_connection_and_peer_flag(self):
        rows = shipments.current_manifest([
            {"part_id": "Z00100300080-00001.FCP Flange:1", "operation": "mount",
             "type_name": "Cold cable", "functional_position": "Cold Bottom FCT"},
            {"part_id": "Z00100300069-00005.FC Term Bottom", "operation": "mount",
             "type_name": "FC Termination board", "functional_position": "FC Term Bottom"},
            {"part_id": "D05700200001-00042", "operation": "mount",
             "type_name": "FEMB", "functional_position": "Slot 1"},
        ])
        self.assertEqual(
            [(r["part_id"], r["connection"], r["peer"]) for r in rows],
            [("Z00100300080-00001", "FCP Flange:1", False),   # cable-end mount
             ("Z00100300069-00005", "FC Term Bottom", True),  # peer back-reference
             ("D05700200001-00042", None, False)])            # classic containment

    def test_assembly_status_fetched_with_base_pid(self):
        api = mock.MagicMock()
        api.get_subcomponents.return_value = {"data": [
            {"part_id": "Z00100300080-00001.FCP Flange:1", "operation": "mount"}]}
        api.get_component.return_value = {"data": {"status": {"name": "Passed"}}}
        kids = parts.assembly_children(api, "Z00100300064-00001")
        api.get_component.assert_called_once_with("Z00100300080-00001")
        self.assertEqual(kids[0]["status"], "Passed")


class CableEndsTest(TestCase):
    """parts.cable_ends — a cable type's ENDs/connector counts from its
    expanded ``connectors`` keys (#72), e.g. HVS Test Bundle 4 Ends."""

    def test_groups_connector_slots_by_end_in_key_order(self):
        connectors = {f"Flange:{n}": None for n in range(1, 9)}
        connectors.update({"FC Termination:1": None, "FC Termination:2": None,
                           "Inner CRP:1": None, "Inner CRP:2": None, "Inner CRP:3": None})
        self.assertEqual(parts.cable_ends(connectors), [
            {"name": "Flange", "connectors": 8},
            {"name": "FC Termination", "connectors": 2},
            {"name": "Inner CRP", "connectors": 3}])

    def test_key_without_connector_number_is_a_single_connector_end(self):
        self.assertEqual(parts.cable_ends({"Bare End": None}),
                         [{"name": "Bare End", "connectors": 1}])
        self.assertEqual(parts.cable_ends(None), [])

    def _cable_api(self):
        api = mock.MagicMock()
        api.get_component.return_value = {"data": {
            "category": "cable", "serial_number": "FCP201NW",
            "component_type": {"name": "Bottom FC termination cold cable"}}}
        api.get_component_type.return_value = {"data": {
            "category": "cable",
            "connectors": {"FCP Flange:1": None, "FCT Board:1": None}}}
        for m in (api.get_locations, api.get_subcomponents, api.get_images,
                  api.get_test_types, api.get_tests, api.get_container):
            m.return_value = {"data": []}
        return api

    def test_part_detail_flags_cable_and_fetches_type_ends(self):
        d = parts.part_detail(self._cable_api(), "Z00100300080-00001", is_shipping=False)
        self.assertTrue(d["is_cable"])
        self.assertEqual(d["cable_ends"], [{"name": "FCP Flange", "connectors": 1},
                                           {"name": "FCT Board", "connectors": 1}])

    def test_generic_part_is_not_a_cable_and_skips_the_type_fetch(self):
        api = self._cable_api()
        api.get_component.return_value = {"data": {"category": "generic"}}
        d = parts.part_detail(api, "Z00100300037-00001", is_shipping=False)
        self.assertFalse(d["is_cable"])
        self.assertEqual(d["cable_ends"], [])
        api.get_component_type.assert_not_called()

    def test_failed_type_fetch_degrades_to_no_ends(self):
        api = self._cable_api()
        api.get_component_type.side_effect = RuntimeError("502")
        d = parts.part_detail(api, "Z00100300080-00001", is_shipping=False)
        self.assertTrue(d["is_cable"])
        self.assertEqual(d["cable_ends"], [])


class CableConnectionsTest(TestCase):
    """_annotate_cable_connections (#72) — each connection's cable-side
    ``END:connector`` recovered from the peer's manifest, plus the occupied
    slots for the diagram."""

    CABLE = "Z00100300035-00001"
    FLANGE = "Z00100300037-00001"
    TRAY = "Z00100300070-00001"

    def _api(self):
        # The flange holds the cable at Flange:1 and Flange:2 (two positions);
        # the tray holds it by bare PID (only-PID link, no connector).
        api = mock.MagicMock()
        api.get_subcomponents.side_effect = lambda pid: {"data": {
            self.FLANGE: [
                {"part_id": f"{self.CABLE}.Flange:1", "operation": "mount",
                 "functional_position": "Cold Inner CO"},
                {"part_id": f"{self.CABLE}.Flange:2", "operation": "mount",
                 "functional_position": "Cold Inner IN"},
            ],
            self.TRAY: [{"part_id": self.CABLE, "operation": "mount",
                         "functional_position": "Bottom FCT cables"}],
        }.get(pid, [])}
        return api

    def _manifest(self):
        # The cable's own reverse rows for those three connections.
        return shipments.current_manifest([
            {"part_id": f"{self.FLANGE}.Cold Inner CO", "operation": "mount",
             "functional_position": "Cold Inner CO", "type_name": "Flange"},
            {"part_id": f"{self.FLANGE}.Cold Inner IN", "operation": "mount",
             "functional_position": "Cold Inner IN", "type_name": "Flange"},
            {"part_id": f"{self.TRAY}.Bottom FCT cables", "operation": "mount",
             "functional_position": "Bottom FCT cables", "type_name": "Tray"},
        ])

    def test_via_and_used_slots(self):
        manifest = self._manifest()
        used = parts._annotate_cable_connections(self._api(), self.CABLE, manifest)
        self.assertEqual(used, ["Flange:1", "Flange:2"])
        self.assertEqual([m["via"] for m in manifest],
                         ["Flange:1", "Flange:2", None])  # only-PID link: no via

    def test_one_fetch_per_distinct_peer(self):
        api = self._api()
        parts._annotate_cable_connections(api, self.CABLE, self._manifest())
        called = [c.args[0] for c in api.get_subcomponents.call_args_list]
        self.assertEqual(sorted(called), [self.FLANGE, self.TRAY])  # deduped

    def test_failed_peer_fetch_degrades_that_peer_only(self):
        api = self._api()
        good = api.get_subcomponents.side_effect

        def side(pid):
            if pid == self.FLANGE:
                raise RuntimeError("502")
            return good(pid)

        api.get_subcomponents.side_effect = side
        manifest = self._manifest()
        used = parts._annotate_cable_connections(api, self.CABLE, manifest)
        self.assertEqual(used, [])
        self.assertEqual([m["via"] for m in manifest], [None, None, None])


class CableContainerTest(TestCase):
    """#72 follow-up (Hajime): a cable's /container rows include its
    connections' back-references, so the "newest" one is a single arbitrary
    connector out of many — "Inside" must not show a connection peer."""

    CABLE = "Z00100300035-00001"
    FLANGE = "Z00100300037-00001"

    def _api(self, container_rows):
        api = mock.MagicMock()
        api.get_component.return_value = {"data": {
            "category": "cable", "component_type": {"name": "HVS Test Bundle"}}}
        api.get_component_type.return_value = {"data": {"connectors": {"Flange:1": None}}}
        api.get_subcomponents.side_effect = lambda pid: {"data": {
            self.CABLE: [{"part_id": f"{self.FLANGE}.Cold Outer SH",
                          "operation": "mount", "type_name": "HVS Test Flange",
                          "functional_position": "Cold Outer SH"}],
            self.FLANGE: [{"part_id": f"{self.CABLE}.Flange:1", "operation": "mount",
                           "functional_position": "Cold Outer SH"}],
        }.get(pid, [])}
        api.get_container.return_value = {"data": container_rows}
        api.get_locations.return_value = {"data": []}
        api.get_images.return_value = {"data": []}
        api.get_tests.return_value = {"data": []}
        api.get_test_types.return_value = {"data": []}
        return api

    def test_connection_peer_is_not_shown_as_inside(self):
        rows = [{"operation": "mount", "created": "2026-07-01",
                 "functional_position": "Cold Outer SH",
                 "container": {"part_id": self.FLANGE,
                               "component_type": {"name": "HVS Test Flange"}}}]
        d = parts.part_detail(self._api(rows), self.CABLE, is_shipping=False)
        self.assertIsNone(d["container"])

    def test_genuine_box_container_still_shows(self):
        rows = [{"operation": "mount", "created": "2026-07-01",
                 "functional_position": "Slot 1",
                 "container": {"part_id": "D08120200001-00001",
                               "component_type": {"name": "CE Shipping Box"}}}]
        d = parts.part_detail(self._api(rows), self.CABLE, is_shipping=False)
        self.assertEqual(d["container"]["part_id"], "D08120200001-00001")


class AssemblyTreeTest(TestCase):
    """parts.assembly_children — one level of the assembly tree with QC status
    (ADR-0015)."""

    def _api(self, status_by_pid):
        api = mock.MagicMock()
        api.get_subcomponents.return_value = {"data": [
            {"part_id": "P1", "type_name": "FEMB", "functional_position": "Slot 1",
             "operation": "mount"},
            {"part_id": "P2", "type_name": "FEMB", "functional_position": "Slot 2",
             "operation": "unmount"},  # excluded by current_manifest
        ]}
        api.get_component.side_effect = lambda pid: {"data": status_by_pid.get(pid, {})}
        return api

    def test_children_carry_status(self):
        api = self._api({"P1": {"status": {"name": "Passed"}}})
        kids = parts.assembly_children(api, "B1")
        self.assertEqual([k["part_id"] for k in kids], ["P1"])     # unmount filtered
        self.assertEqual(kids[0]["status"], "Passed")              # nested ref unwrapped

    def test_failed_status_fetch_degrades_to_none(self):
        api = self._api({})
        api.get_component.side_effect = RuntimeError("502")
        self.assertIsNone(parts.assembly_children(api, "B1")[0]["status"])

    def test_status_fetch_capped(self):
        api = mock.MagicMock()
        api.get_subcomponents.return_value = {"data": [
            {"part_id": f"P{i}", "operation": "mount"} for i in range(parts._STATUS_FETCH_CAP + 5)]}
        api.get_component.return_value = {"data": {"status": "Passed"}}
        kids = parts.assembly_children(api, "B1")
        self.assertEqual(api.get_component.call_count, parts._STATUS_FETCH_CAP)  # capped
        self.assertEqual(kids[0]["status"], "Passed")
        self.assertIsNone(kids[-1]["status"])  # beyond the cap → listed, no status


class AssemblyViewTest(TestCase):
    """The lazy-expand endpoint /hw/assembly/<pid>/."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("a", "a@a.io", "pw")
        self.client.force_login(self.user)

    def test_returns_children_with_part_urls(self):
        api = mock.MagicMock()
        api.get_subcomponents.return_value = {"data": [
            {"part_id": "C1", "type_name": "ColdADC", "operation": "mount"}]}
        api.get_component.return_value = {"data": {"status": "Available"}}
        with mock.patch("explore.views.mint_for", return_value="bearer"), \
             mock.patch("explore.views.FnalDbApiClient", return_value=api):
            resp = self.client.get("/hw/assembly/B1/")
        self.assertEqual(resp.status_code, 200)
        child = json.loads(resp.content)["children"][0]
        self.assertEqual(child["part_id"], "C1")
        self.assertEqual(child["url"], "/hw/part/C1/")
        self.assertEqual(child["status"], "Unknown")   # obsolete default (#75)

    def test_fnal_link_required_returns_409(self):
        with mock.patch("explore.views.mint_for", side_effect=FnalLinkRequired()):
            resp = self.client.get("/hw/assembly/B1/")
        self.assertEqual(resp.status_code, 409)

    def test_peer_backref_flagged_with_base_pid_url(self):
        # Expanding a cable: its rows are peer back-references (#72) — the
        # JSON must carry the peer flag so the client renders an inert caret.
        api = mock.MagicMock()
        api.get_subcomponents.return_value = {"data": [
            {"part_id": "Z00100300064-00001.Cold Bottom FCT", "operation": "mount",
             "type_name": "Bias FT flange", "functional_position": "Cold Bottom FCT"}]}
        api.get_component.return_value = {"data": {"status": "Passed"}}
        with mock.patch("explore.views.mint_for", return_value="bearer"), \
             mock.patch("explore.views.FnalDbApiClient", return_value=api):
            resp = self.client.get("/hw/assembly/Z00100300080-00001/")
        child = json.loads(resp.content)["children"][0]
        self.assertEqual(child["part_id"], "Z00100300064-00001")
        self.assertEqual(child["connection"], "Cold Bottom FCT")
        self.assertTrue(child["peer"])
        self.assertEqual(child["url"], "/hw/part/Z00100300064-00001/")


class PartViewTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("p", "p@p.io", "pw")
        self.client.force_login(self.user)
        self.url = "/hw/part/D05700200099-00007/"  # not a curated shipping type

    def _api(self):
        api = mock.MagicMock()
        api.get_component.return_value = {"data": {
            "serial_number": "SN-7", "status": "Passed",
            "component_type": {"name": "ColdADC"},
            "specifications": [{"DATA": {"Channels": 64}}]}}
        api.get_locations.return_value = {"data": []}            # most parts have none
        api.get_subcomponents.return_value = {"data": []}
        api.get_images.return_value = {"data": [{"image_id": "i9", "image_name": "photo.jpg"}]}
        api.get_test_types.return_value = {"data": [{"name": "RoomT", "id": 7}]}

        def get_tests(pid, test_type_id=None, history=False):
            if test_type_id is None:
                return {"data": [{"test_type": {"name": "RoomT"},
                                  "created": "2026-02-02T00:00:00"}]}
            return {"data": [{"id": 15023, "status": {"name": "Pass"},
                              "created": "2026-02-02T00:00:00",
                              "images": [{"image_id": "z", "image_name": "t.csv"}]}]}
        api.get_tests.side_effect = get_tests
        return api

    def test_a_failing_aux_endpoint_does_not_break_the_page(self):
        # A part with no /tests (endpoint raises) must still render — the
        # section just degrades to empty, not a 502 (ADR-0014 hardening).
        api = self._api()
        api.get_tests.side_effect = RuntimeError("404 from HWDB")
        d = parts.part_detail(api, "X-1", is_shipping=False)
        self.assertEqual(d["tests"], [])
        self.assertEqual(d["facts"][0]["label"], "Serial number")  # rest still built

    def test_item_edit_mode_renders_the_form_and_saves_changed_fields(self):
        # #104: ✎ Edit → ?edit=1 form pre-filled from the record (manufacturers
        # from the type); Save PATCHes only what changed
        api = self._api()
        api.get_component.return_value["data"].update({
            "status": {"id": 120, "name": "QA/QC Tests - Passed All"},   # HWDB's real shape
            "manufacturer": None, "is_installed": False, "qaqc_uploaded": True,
            "certified_qaqc": False, "comments": "c"})
        api.get_component_type.return_value = {"data": {
            "manufacturers": [{"id": 7, "name": "Hajime Inc"}, {"id": 8, "name": "Acme"}]}}
        api.patch_component.return_value = {"status": "OK"}
        with mock.patch("explore.views.mint_for", return_value="bearer"), \
             mock.patch("explore.views.FnalDbApiClient", return_value=api):
            plain = self.client.get(self.url).content.decode()
            html = self.client.get(self.url + "?edit=1").content.decode()
            resp = self.client.post(self.url + "edit/", {
                "item-card": "1", "item-manufacturer": "8", "item-status": "120",
                "item-qaqc_uploaded": "on", "item-certified_qaqc": "on",
                "item-serial_number": "SN-7", "item-item_comments": "c"})
        self.assertIn('href="?edit=1"', plain)
        self.assertNotIn('class="sd-editform"', plain)          # form only in edit mode
        self.assertNotIn("Acme", plain)                         # …so no manufacturer list either
        self.assertIn('class="sd-editform"', html)
        self.assertIn('<option value="8">Acme</option>', html)
        self.assertIn('name="item-qaqc_uploaded" checked', html)
        self.assertIn("Update location", html)                  # location form opens in edit mode
        self.assertNotIn("<h2>Packing</h2>", html)               # …but no box-only panes (review)
        self.assertNotIn("<h2>Shipping Workflows</h2>", html)
        self.assertEqual(resp["Location"], self.url)
        self.assertEqual(api.patch_component.call_args.args[1],
                         {"part_id": "D05700200099-00007", "manufacturer": {"id": 8},
                          "certified_qaqc": True})
        self.assertEqual(ActivityEvent.objects.filter(kind="item").count(), 1)

    @mock.patch("django.conf.settings.HWDB_WRITE_INSTANCES", ["dev"])
    def test_item_edit_absent_and_forbidden_off_write_instances(self):
        api = self._api()
        with mock.patch("explore.views.mint_for", return_value="bearer"), \
             mock.patch("explore.views.FnalDbApiClient", return_value=api):
            html = self.client.get(self.url).content.decode()
            resp = self.client.post(self.url + "edit/", {"item-card": "1", "item-status": "130"})
        self.assertNotIn("?edit=1", html)
        self.assertEqual(resp.status_code, 403)
        api.patch_component.assert_not_called()

    def test_spec_row_delete_control_is_architect_only(self):
        api = self._api()
        with mock.patch("explore.views.mint_for", return_value="bearer"), \
             mock.patch("explore.views.FnalDbApiClient", return_value=api), \
             mock.patch("explore.views._is_architect", return_value=True):
            body = self.client.get(self.url).content.decode()
        self.assertIn('class="sd-del"', body)
        self.assertIn('name="label" value="Channels"', body)
        with mock.patch("explore.views.mint_for", return_value="bearer"), \
             mock.patch("explore.views.FnalDbApiClient", return_value=api), \
             mock.patch("explore.views._is_architect", return_value=False):
            body = self.client.get(self.url).content.decode()
        self.assertNotIn('class="sd-del"', body)

    def test_spec_row_delete_patches_the_item(self):
        api = self._api()
        api.get_component.return_value["data"]["specifications"] = [{"Note": "", "DATA": {
            "Channels": 64, "Measurements — H": {"Thickness": {"P1": 1.6}},
            "Measurements — J": {"Thickness": {"P1": 2.0}, "Other": 1}}}]
        api.patch_component.return_value = {"status": "OK"}
        url = self.url + "spec-delete/"
        with mock.patch("explore.views.mint_for", return_value="bearer"), \
             mock.patch("explore.views.FnalDbApiClient", return_value=api), \
             mock.patch("explore.views._is_architect", return_value=True):
            r1 = self.client.post(url, {"section": "Measurements — H", "label": "Thickness"})
            spec1 = api.patch_component.call_args.args[1]["specifications"]
            self.client.post(url, {"section": "", "label": "Channels"})
            spec2 = api.patch_component.call_args.args[1]["specifications"]
            self.client.post(url, {"section": "Nope", "label": "x"})
        self.assertEqual(r1.status_code, 302)
        self.assertNotIn("Measurements — H", spec1["DATA"])           # emptied section dropped
        self.assertEqual(spec1["DATA"]["Measurements — J"], {"Thickness": {"P1": 2.0}, "Other": 1})
        self.assertEqual(spec1["Note"], "")                          # datasheet key rides through
        self.assertNotIn("Channels", spec2["DATA"])
        self.assertEqual(api.patch_component.call_count, 2)          # unknown key → no PATCH
        self.assertEqual(ActivityEvent.objects.filter(kind="spec").count(), 2)

    def test_spec_row_delete_refused_for_non_architects(self):
        api = self._api()
        with mock.patch("explore.views.mint_for", return_value="bearer"), \
             mock.patch("explore.views.FnalDbApiClient", return_value=api), \
             mock.patch("explore.views._is_architect", return_value=False):
            resp = self.client.post(self.url + "spec-delete/", {"label": "Channels"})
        self.assertEqual(resp.status_code, 403)
        api.patch_component.assert_not_called()

    def test_renders_generic_part(self):
        with mock.patch("explore.views.mint_for", return_value="bearer"), \
             mock.patch("explore.views.FnalDbApiClient", return_value=self._api()):
            resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("SN-7", body)             # item fact
        self.assertIn("RoomT", body)            # test summary
        self.assertIn("/view/images/component_test/15023", body)  # per-test data link to FNAL
        self.assertIn("photo.jpg", body)        # downloadable attachment
        self.assertIn("<h2>DATA", body)         # the DATA card (#98 review)
        self.assertIn("Channels", body)
        self.assertNotIn("In Transit", body)    # no shipping framing for a normal part

    def test_shows_latest_spec_with_datasheet_level_fields(self):
        # An FNAL-UI edit appends a new specifications entry whose fields sit
        # at the top level (no DATA envelope) — the page must show that entry.
        api = self._api()
        api.get_component.return_value = {"data": {
            "serial_number": "SN-7", "component_type": {"name": "ColdADC"},
            "specifications": [
                {"DATA": {"Stage": "original"}},
                {"Vendor": "Acme", "_meta": {"v": 2}},
            ]}}
        with mock.patch("explore.views.mint_for", return_value="bearer"), \
             mock.patch("explore.views.FnalDbApiClient", return_value=api):
            body = self.client.get(self.url).content.decode()
        self.assertIn("Vendor", body)
        self.assertIn("Acme", body)
        self.assertNotIn("original", body)   # superseded entry
        self.assertNotIn("_meta", body)      # HWDB bookkeeping stays hidden

    def test_big_spec_cards_and_long_values_fold(self):
        api = self._api()
        api.get_component.return_value = {"data": {
            "serial_number": "SN-7", "component_type": {"name": "ColdADC"},
            "specifications": [{
                **{f"Field {i:02d}": f"v{i}" for i in range(14)},
                "Trace": "x" * 400,
            }]}}
        with mock.patch("explore.views.mint_for", return_value="bearer"), \
             mock.patch("explore.views.FnalDbApiClient", return_value=api):
            body = self.client.get(self.url).content.decode()
        self.assertIn("Show 5 more…", body)           # 15 fields, 10 shown
        self.assertIn('class="sd-vfold"', body)       # 400-char value folds
        self.assertIn("v13", body)                    # folded ≠ dropped

    def test_object_values_get_a_click_to_view_modal(self):
        api = self._api()
        api.get_component.return_value = {"data": {
            "serial_number": "SN-7", "component_type": {"name": "ColdADC"},
            "specifications": [{"Curve": [1, 2, 3]}]}}
        with mock.patch("explore.views.mint_for", return_value="bearer"), \
             mock.patch("explore.views.FnalDbApiClient", return_value=api):
            body = self.client.get(self.url).content.decode()
        self.assertIn('class="sd-jview"', body)                    # preview link
        self.assertIn('class="sd-jdata" data-label="Curve"', body)  # modal payload
        self.assertIn('<dialog id="sd-jmodal">', body)             # shared viewer
        self.assertIn('class="sd-copy"', body)                     # copy button

    def test_shipment_url_redirects_to_part(self):
        resp = self.client.get("/hw/shipment/D05700200099-00007/")
        self.assertEqual(resp.status_code, 301)
        self.assertEqual(resp["Location"], self.url)

    def test_renders_cable_part_with_ends_diagram_and_inert_peer_caret(self):
        api = self._api()
        api.get_component.return_value = {"data": {
            "category": "cable", "serial_number": "FCP201NW",
            "component_type": {"name": "Bottom FC termination cold cable"}}}
        api.get_component_type.return_value = {"data": {
            "connectors": {"FCP Flange:1": None, "FCT Board:1": None}}}
        api.get_subcomponents.return_value = {"data": [
            {"part_id": "Z00100300064-00001.Cold Bottom FCT", "operation": "mount",
             "type_name": "Bias FT flange", "functional_position": "Cold Bottom FCT"}]}
        with mock.patch("explore.views.mint_for", return_value="bearer"), \
             mock.patch("explore.views.FnalDbApiClient", return_value=api):
            body = self.client.get(self.url).content.decode()
        self.assertIn("<h2>Cable ends</h2>", body)        # diagram card
        self.assertIn('id="cable-ends-data"', body)       # ends JSON for the SVG
        self.assertIn('id="cable-used-data"', body)       # occupancy JSON (#72)
        self.assertIn("FCP Flange", body)
        self.assertIn("Connections (1)", body)            # not "Assembly" on a cable
        self.assertIn("asm-caret is-leaf", body)          # peer row: inert caret
        # A peer's suffix is its functional position — the dedicated Position
        # column already shows it, so the Part column stays clean (Hajime).
        self.assertNotIn(".Cold Bottom FCT", body)

    def test_cable_connection_rows_show_which_end_they_use(self):
        cable = "D05700200099-00007"
        flange = "Z00100300064-00001"
        api = self._api()
        api.get_component.return_value = {"data": {
            "category": "cable",
            "component_type": {"name": "Bottom FC termination cold cable"}}}
        api.get_component_type.return_value = {"data": {
            "connectors": {"FCP Flange:1": None, "FCT Board:1": None}}}
        api.get_subcomponents.side_effect = lambda pid: {"data": {
            cable: [{"part_id": f"{flange}.Cold Bottom FCT", "operation": "mount",
                     "type_name": "Bias FT flange",
                     "functional_position": "Cold Bottom FCT"}],
            flange: [{"part_id": f"{cable}.FCP Flange:1", "operation": "mount",
                      "functional_position": "Cold Bottom FCT"}],
        }.get(pid, [])}
        with mock.patch("explore.views.mint_for", return_value="bearer"), \
             mock.patch("explore.views.FnalDbApiClient", return_value=api):
            body = self.client.get(self.url).content.decode()
        self.assertIn("via FCP Flange:1", body)            # cable-side end recovered
        self.assertIn('"FCP Flange:1"', body)              # occupied slot in the used JSON

    def test_generic_part_has_no_cable_card(self):
        with mock.patch("explore.views.mint_for", return_value="bearer"), \
             mock.patch("explore.views.FnalDbApiClient", return_value=self._api()):
            body = self.client.get(self.url).content.decode()
        self.assertNotIn("<h2>Cable ends</h2>", body)
        self.assertIn("Assembly (0)", body)

    def test_forward_cable_end_row_does_not_expand(self):
        # A mounted cable end on a normal part (the flange case): the row
        # links to the cable but its caret is inert — expanding would fan out
        # into the cable's whole neighborhood, arbitrarily deep (#72).
        api = self._api()
        api.get_subcomponents.return_value = {"data": [
            {"part_id": "Z00100300035-00001.Flange:3", "operation": "mount",
             "type_name": "HVS Test Bundle 4 Ends",
             "functional_position": "Cold Inner SH"}]}
        with mock.patch("explore.views.mint_for", return_value="bearer"), \
             mock.patch("explore.views.FnalDbApiClient", return_value=api):
            body = self.client.get(self.url).content.decode()
        self.assertIn("asm-caret is-leaf", body)
        self.assertIn("Cable end — open the cable for its connections", body)
        self.assertIn(".Flange:3", body)

    def test_es_card_on_dev_part_whose_type_has_an_es_config(self):
        # A non-shipping part on the write instance gets the Executive-summary
        # card when its type carries an ES_{ptid}_*.json config in HWDB (the
        # interim "requires ES" mark until the hierarchy-chart one exists).
        api = self._api()
        api.get_images.return_value = {"data": [
            {"image_id": "i9", "image_name": "photo.jpg"},
            {"image_id": "es9", "image_name":
             "ExecutiveSummary_D05700200099-00007_20260701_000000.pdf"}]}
        api.get_component_type_images.return_value = {"data": [
            {"image_id": "c1", "image_name": "ES_D05700200099_test_v8.json",
             "created": "2026-07-01T00:00:00"}]}
        api.get_image_response.return_value = mock.Mock(content=json.dumps({
            "consortium_name": "CE (test)",
            "test_description": "Check the chip"}).encode())
        with mock.patch("explore.views.mint_for", return_value="bearer"), \
             mock.patch("explore.views.FnalDbApiClient", return_value=api):
            resp = self.client.get("/hw/dev/part/D05700200099-00007/")
        html = resp.content.decode()
        # The summary lives in the ES card's selector; the catch-all
        # Attachments pane must not list it again (#77 follow-up).
        self.assertEqual([a["image_id"] for a in resp.context["exec_summaries"]],
                         ["es9"])
        self.assertEqual([a["image_id"] for a in resp.context["other_attachments"]],
                         ["i9"])
        self.assertIn("Executive summary", html)
        # Dashboard-style header lines, from the config JSON
        self.assertIn("Consortium:", html)
        self.assertIn("CE (test)", html)
        self.assertIn("Description:", html)
        self.assertIn("Check the chip", html)
        self.assertIn("ES_D05700200099_test_v8.json", html)   # config named
        self.assertIn("/hw/dev/part/D05700200099-00007/exec-summary/", html)

    def test_es_card_shows_without_a_config_too(self):
        # Every item can carry an ES (2026-07-30) — a configless type still
        # gets the card (the ES page runs DEFAULT mode), just without the
        # config-driven header lines.
        api = self._api()
        api.get_component_type_images.return_value = {"data": []}
        with mock.patch("explore.views.mint_for", return_value="bearer"), \
             mock.patch("explore.views.FnalDbApiClient", return_value=api):
            html = self.client.get("/hw/dev/part/D05700200099-00007/").content.decode()
        self.assertIn("Executive summary", html)
        self.assertIn("/hw/dev/part/D05700200099-00007/exec-summary/", html)
        self.assertNotIn("Consortium:", html)
        self.assertNotIn(">Checklists</h2>", html)   # no checklist card (#95/#96)

    def test_checklist_card_lists_the_types_checklists_with_status(self):
        # #95: Checklist_{ptid}_{name}.json rows on the type's images become
        # named fill-out links on the part page (write instances only).
        # Editing lives on the TYPE page, not here (#96 review). Each link
        # carries a status chip: filled / draft / not filled yet (#97 review).
        from explore.models import ChecklistDraft
        api = self._api()
        api.get_component_type_images.return_value = {"data": [
            {"image_id": "cl1", "created": "2026-08-01T00:00:00",
             "image_name": "Checklist_D05700200099_Reception.json"},
            {"image_id": "cl2", "created": "2026-08-02T00:00:00",
             "image_name": "Checklist_D05700200099_Assembly.json"},
            {"image_id": "cl3", "created": "2026-08-03T00:00:00",
             "image_name": "Checklist_D05700200099_Final.json"}]}
        # Reception's test type matches the item's RoomT record → filled;
        # Assembly's doesn't; Final has a draft by THIS user.
        schemas = {
            "cl1": {"test_type_name": "RoomT"},
            "cl2": {"test_type_name": "Other QC"},
            "cl3": {"test_type_name": "Final QC"},
        }
        api.get_image_response.side_effect = lambda iid: mock.Mock(
            content=json.dumps(schemas[iid]).encode())
        ChecklistDraft.objects.create(
            instance="dev", part_id="D05700200099-00007", name="Final",
            username="p", data={})   # actor falls back to the Django username
        with mock.patch("explore.views.mint_for", return_value="bearer"), \
             mock.patch("explore.views.FnalDbApiClient", return_value=api):
            html = self.client.get("/hw/dev/part/D05700200099-00007/").content.decode()
        self.assertIn(">Checklists</h2>", html)
        self.assertIn("/hw/dev/part/D05700200099-00007/checklist/Reception/", html)
        self.assertIn("/hw/dev/part/D05700200099-00007/checklist/Assembly/", html)
        self.assertIn("&#10003; filled 2026-02-02", html)   # RoomT record date
        self.assertIn("&#9998; draft", html)                # Final's draft chip
        self.assertIn("not filled yet", html)               # Assembly untouched


class TestDataDownloadTest(TestCase):
    """Per-test test_data JSON download (the dashboard's test-data export)."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("td", "t@d.io", "pw")
        self.client.force_login(self.user)
        self.url = "/hw/test-data/D08100100003-00226/42/"

    def _api(self):
        api = mock.MagicMock()
        api.get_tests.return_value = {"data": [
            {"created": "2026-05-29T00:00:00", "test_data": {"DATA": {"gain": 1.2}}}]}
        return api

    def test_renders_test_data_as_inline_json_text(self):
        with mock.patch("explore.views.mint_for", return_value="bearer"), \
             mock.patch("explore.views.FnalDbApiClient", return_value=self._api()):
            resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "text/plain; charset=utf-8")
        self.assertNotIn("Content-Disposition", resp)        # inline, not a download
        self.assertEqual(json.loads(resp.content), {"DATA": {"gain": 1.2}})
        self.assertIn(b"\n", resp.content)                   # pretty-printed

    def test_fnal_link_required_returns_409(self):
        with mock.patch("explore.views.mint_for", side_effect=FnalLinkRequired()):
            resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 409)


def _comp_leaf(ptid="D05700200099"):
    """A synced non-shipping leaf under FD CE (so leaf_path_for resolves)."""
    sys, _ = H.objects.get_or_create(
        level=H.LEVEL_SYSTEM, system_id=81, subsystem_id=None, part_type_id="",
        defaults={"system_name": "FD CE", "name": "FD CE"})
    sub, _ = H.objects.get_or_create(
        level=H.LEVEL_SUBSYSTEM, system_id=81, subsystem_id=300, part_type_id="",
        defaults={"parent": sys, "system_name": "FD CE",
                  "subsystem_name": "ColdADC", "name": "ColdADC"})
    return H.objects.create(
        level=H.LEVEL_TYPE, parent=sub, system_id=81, system_name="FD CE",
        subsystem_id=300, subsystem_name="ColdADC", name="ColdADC",
        part_type_id=ptid, n_components=55,
        full_name="D.FD CE.ColdADC.ColdADC", tests_synced_at=timezone.now())


class LeafCableCardTest(TestCase):
    """The type leaf page's cable-ends card (#72) — mirror-only render."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("lc", "l@c.io", "pw")
        self.client.force_login(self.user)
        self.leaf = _comp_leaf()

    def _html(self):
        return self.client.get(
            navigation.leaf_path_for("prod", self.leaf.part_type_id)).content.decode()

    def test_cable_leaf_renders_ends_diagram(self):
        self.leaf.category = "cable"
        self.leaf.cable_ends = [{"name": "FCP Flange", "connectors": 1},
                                {"name": "FCT Board", "connectors": 1}]
        self.leaf.save()
        html = self._html()
        self.assertIn(">Cable ends<", html)
        self.assertIn('id="cable-ends-data"', html)
        self.assertIn("FCP Flange", html)
        self.assertIn("cable-diagram.js", html)

    def test_cable_leaf_without_mirrored_ends_offers_a_system_rewalk(self):
        self.leaf.category = "cable"
        self.leaf.save()
        html = self._html()
        self.assertIn(">Cable ends<", html)
        self.assertIn("aren’t mirrored yet", html)
        self.assertIn('id="system-walk-btn"', html)
        self.assertIn("/hw/sync-system/81/?project=D", html)

    def test_generic_leaf_has_no_cable_card(self):
        html = self._html()
        self.assertNotIn(">Cable ends<", html)

    def test_category_row_shows_mirrored_value(self):
        self.leaf.category = "generic"
        self.leaf.save()
        html = self._html()
        self.assertIn("<dt>Category</dt><dd>generic", html)   # #101 appends the shipping-container tag
        self.assertNotIn("not mirrored — re-walk system", html)

    def test_unmirrored_category_offers_a_system_rewalk(self):
        # Mirror rows from before the category field (#72) show "—" plus a
        # re-walk button, so the fields can be backfilled from the leaf page.
        html = self._html()
        self.assertIn("<dt>Category</dt>", html)
        self.assertIn("not mirrored — re-walk system", html)
        self.assertIn("/hw/sync-system/81/?project=D", html)


class LeafPartsTableTest(TestCase):
    """The paginated parts table on a synced component-type leaf page."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("lp", "l@p.io", "pw")
        self.client.force_login(self.user)
        self.leaf = _comp_leaf()
        for i in range(55):
            HwdbComponentEvent.objects.create(
                part_type_id=self.leaf.part_type_id,
                part_id=f"{self.leaf.part_type_id}-{i:05d}", created=timezone.now(),
                serial_number=f"SN-{i:05d}", created_by="Alex Wagner")
        self.url = navigation.leaf_path_for("prod", self.leaf.part_type_id)

    def test_lists_parts_paginated_50_with_part_links(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn("Items (55)", html)
        # 55 rows → 50 on page 1 (newest first), 5 on page 2.
        self.assertIn(f"/hw/part/{self.leaf.part_type_id}-00054/", html)  # row → part page
        self.assertIn('target="_blank"', html)                                 # opens new tab
        self.assertIn("SN-00054", html)                                        # serial column
        self.assertIn("<th>Serial number</th>", html)
        self.assertIn("<th>Created by</th>", html)                             # creator column
        self.assertIn("Alex Wagner", html)
        self.assertNotIn("<th>Created</th>", html)                             # created date dropped
        self.assertIn("Page 1 of 2", html)
        self.assertIn("Last »", html)                                          # first/last links
        self.assertIn("?page=2", html)                                         # Last → page 2
        self.assertNotIn(f"/hw/part/{self.leaf.part_type_id}-00000/", html)

    def test_second_page_has_first_and_prev_links(self):
        html = self.client.get(self.url + "?page=2").content.decode()
        self.assertIn("Page 2 of 2", html)
        self.assertIn(f"/hw/part/{self.leaf.part_type_id}-00000/", html)  # tail row
        self.assertIn("« First", html)
        self.assertIn('href="?page=1"', html)                                  # First → page 1

    def test_htmx_pager_click_returns_just_the_pane(self):
        # An hx-get from the pager swaps the pane in place (no full page, no
        # scroll-to-top): the response is the fragment only.
        html = self.client.get(self.url + "?page=2", HTTP_HX_REQUEST="true",
                               HTTP_HX_TARGET="parts-pane").content.decode()
        # Nothing renders outside the swapped div — stray text (e.g. a broken
        # template comment) would accumulate above the table on every swap.
        self.assertTrue(html.strip().startswith('<div id="parts-pane"'))
        self.assertIn('id="parts-pane"', html)
        self.assertIn("Page 2 of 2", html)
        self.assertNotIn("<html", html)                # not the full page
        self.assertNotIn("extree-leaf", html)          # no sidebar
        # Pager links carry the htmx swap attributes (inherited from the pane).
        self.assertIn('hx-get="?page=1"', html)
        self.assertIn('hx-target="#parts-pane"', html)

    def test_component_breakdown_panel_when_facets_present(self):
        # Mirror-only breakdown bar charts appear once components carry a facet.
        HwdbComponentEvent.objects.filter(part_type_id=self.leaf.part_type_id).update(
            status="QA/QC Passed", manufacturer="BNL")
        html = self.client.get(self.url).content.decode()
        self.assertIn("Component breakdown", html)
        self.assertIn('id="breakdown-config"', html)
        self.assertIn("QA/QC Passed", html)
        self.assertIn("BNL", html)


class SearchTest(TestCase):
    """Instant mirror search → component-type leaf or part page."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("sx", "s@x.io", "pw")
        self.client.force_login(self.user)
        self.leaf = _comp_leaf()  # ColdADC, D05700200099, under browsable FD CE
        HwdbComponentEvent.objects.create(
            part_type_id="D05700200099", part_id="D05700200099-00001",
            created=timezone.now(), serial_number="2502-18564")

    def test_page_renders(self):
        resp = self.client.get("/hw/search/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Advanced search")  # the future-seam note

    def test_api_finds_component_type_by_name_with_leaf_path(self):
        d = self.client.get("/hw/search/api/", {"q": "ColdADC"}).json()
        match = next(t for t in d["types"] if t["part_type_id"] == "D05700200099")
        self.assertTrue(match["path"])  # reachable leaf page

    def test_api_finds_mirrored_part_and_flags_direct_pid(self):
        d = self.client.get("/hw/search/api/", {"q": "D05700200099-00001"}).json()
        self.assertEqual(d["direct_part"], "D05700200099-00001")
        self.assertTrue(any(p["part_id"] == "D05700200099-00001" for p in d["parts"]))

    def test_api_finds_part_by_serial_number(self):
        d = self.client.get("/hw/search/api/", {"q": "2502-18564"}).json()
        match = next(p for p in d["parts"] if p["part_id"] == "D05700200099-00001")
        self.assertEqual(match["serial_number"], "2502-18564")

    def test_short_query_returns_empty(self):
        d = self.client.get("/hw/search/api/", {"q": "a"}).json()
        self.assertEqual(d, {"types": [], "parts": [], "direct_part": None})


class LeafSidebarCtxTest(TestCase):
    """A part page's sidebar ctx must open the whole branch down to the
    part's component-type leaf (region + family included), so the sidebar
    shows and can scroll to where you are."""

    def test_ctx_carries_region_and_family_keys(self):
        leaf = _comp_leaf()
        ctx = navigation.leaf_sidebar_ctx("prod", leaf)
        self.assertEqual(ctx, {"kind": "leaf", "part_type_id": "D05700200099",
                               "system_id": 81, "subsystem_id": 300, "project": "D",
                               "region_key": "FD", "family_key": "FD-CE"})

    def test_sidebar_tree_opens_branch_and_flags_leaf_current(self):
        leaf = _comp_leaf()
        tree = navigation.sidebar_tree("prod", navigation.leaf_sidebar_ctx("prod", leaf))
        dune = next(n for n in tree if n["label"] == "DUNE (D)")   # project tier (#71)
        self.assertTrue(dune["open"])
        region = next(r for r in dune["children"] if r["label"] == "Far Detector")
        self.assertTrue(region["open"])
        family = next(f for f in region["children"] if f["label"] == "FD CE")
        self.assertTrue(family["open"])
        # FD CE is a flat family (one system) → its children are subsystems.
        sub = next(s for s in family["children"] if s["label"] == "ColdADC")
        self.assertTrue(sub["open"])
        leaf_node = next(l for l in sub["children"] if l["is_leaf"])
        self.assertTrue(leaf_node["current"])
