"""Tests for consortium checklist forms (#95): schema listing/normalizing,
the fill-out page, prefill (revive) and the submit flow.

    python manage.py test explore
"""

import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from explore import checklistforms
from explore.models import ChecklistDraft

PART = "Z00100300041-00150"
PTID = "Z00100300041"
NAME = "Reception"
PAGE = f"/hw/dev/part/{PART}/checklist/{NAME}/"

SCHEMA = {
    "name": "PCB Segments Interface",
    "test_type_name": "PCB Segments Interface",
    "sections": [
        {"title": "Identification", "fields": [
            {"type": "qr", "label": "PCB Batch PID"},
            {"type": "datetime", "label": "Reception date"},
            {"type": "select", "label": "Segment type", "options": ["G", "J", "C"]},
        ]},
        {"title": "Measurements", "fields": [
            {"type": "row", "fields": [
                {"type": "number", "label": "Dim 1", "units": "cm"},
                {"type": "number", "label": "Dim 2", "units": "cm"},
            ]},
            {"type": "table", "label": "Thickness", "units": "mm",
             "columns": ["P1", "P2"], "nominal": 1.6, "tol": 0.1},
        ]},
        {"title": "Visual Inspection", "fields": [
            {"type": "check", "label": "Planarity"},
            {"type": "textarea", "label": "Anomaly description"},
            {"type": "photo", "label": "Photo 1"},
            {"type": "steps", "label": "Procedure", "steps": ["Unwrap", "Inspect"]},
            {"type": "static", "label": "Drawing", "url": "https://edms.cern.ch/x"},
            {"type": "wibble", "label": "Bogus"},          # unknown → dropped
            {"type": "select", "label": "No options"},     # malformed → dropped
        ]},
    ],
}

PNG = (b"\x89PNG\r\n\x1a\n" + b"0" * 32)


def _api(schema=SCHEMA, prev=None, test_types=("ES",)):
    api = mock.MagicMock()
    api.get_component_type_images.return_value = {"data": [
        {"image_id": "cl1", "image_name": f"Checklist_{PTID}_{NAME}.json",
         "created": "2026-08-01T00:00:00"}]}
    api.get_image_response.return_value = mock.Mock(
        content=json.dumps(schema).encode())
    api.get_tests.return_value = {
        "data": [{"test_data": prev}] if prev is not None else []}
    api.get_test_types.return_value = {
        "data": [{"id": i, "name": t} for i, t in enumerate(test_types)]}
    api.post_test.return_value = {"status": "OK"}
    api.post_test_type.return_value = {"status": "OK"}
    api.post_component_image.return_value = {"status": "OK", "image_id": "img-77"}
    # #103: the Item card's prefill + option lists
    api.get_component.return_value = {"data": {
        "status": {"id": 120, "name": "QA/QC Tests - Passed All"},
        "is_installed": False, "qaqc_uploaded": True, "certified_qaqc": False,
        "manufacturer": None, "location": None,
        "serial_number": "SN-1", "comments": "c",
        "specifications": [{"DATA": {}}]}}
    api.get_component_type.return_value = {"data": {
        "manufacturers": [{"id": 7, "name": "Hajime Inc"}, {"id": 8, "name": "Acme"}],
        "connectors": {}, "properties": {"specifications": [{"datasheet": {"DATA": {}}}]}}}
    api.get_institutions.return_value = {"data": [
        {"id": 128, "name": "BNL", "country": {"code": "US"}}]}
    api.patch_component.return_value = {"status": "OK"}
    api.post_location.return_value = {"status": "OK"}
    return api


ITEM_POST = {"item-card": "1", "item-manufacturer": "8", "item-status": "130",
             "item-qaqc_uploaded": "on", "item-serial_number": "SN-1",
             "item-item_comments": "c", "item-location": "128",
             "item-arrived": "2026-08-26T10:00", "item-test_comments": "looks fine"}


def _mocked(api):
    return (mock.patch("explore.views.mint_for", return_value="bearer"),
            mock.patch("explore.views.FnalDbApiClient", return_value=api))


class SchemaModuleTest(TestCase):
    """checklistforms unit behavior — no HTTP involved."""

    def test_available_groups_newest_per_name(self):
        rows = [
            {"image_id": "a", "image_name": f"Checklist_{PTID}_Reception.json",
             "created": "2026-07-01T00:00:00"},
            {"image_id": "b", "image_name": f"Checklist_{PTID}_Reception.json",
             "created": "2026-08-01T00:00:00"},      # newer version wins
            {"image_id": "c", "image_name": f"Checklist_{PTID}_Assembly.json",
             "created": "2026-07-15T00:00:00"},
            {"image_id": "d", "image_name": f"ES_{PTID}_test.json"},   # not a checklist
            {"image_id": "e", "image_name": f"Checklist_{PTID}_.json"},  # blank name
            "garbage",
        ]
        out = checklistforms.available(None, PTID, rows=rows)
        self.assertEqual([(r["name"], r["image_id"]) for r in out],
                         [("Assembly", "c"), ("Reception", "b")])

    def test_section_when_resolves_to_the_selects_key(self):
        cfg = json.loads(json.dumps(SCHEMA))
        cfg["sections"][1]["when"] = {"field": "Segment type", "equals": "J"}
        cfg["sections"][1]["collapsed"] = True
        cfg["sections"][2]["when"] = {"field": "Segment type", "equals": "X"}  # no such option
        cfg["sections"].append({"title": "Typo", "when": {"field": "Segmnt", "equals": "G"},
                                "fields": [{"type": "text", "label": "t"}]})
        schema = checklistforms.normalize(cfg, NAME)
        secs = {s["title"]: s for s in schema["sections"]}
        self.assertEqual(secs["Measurements"]["when"],
                         {"field": "Segment type", "key": "f0-2", "equals": "J"})
        self.assertTrue(secs["Measurements"]["collapsed"])
        self.assertNotIn("when", secs["Visual Inspection"])   # unmatched option → dropped
        self.assertNotIn("when", secs["Typo"])                # unmatched field → dropped
        self.assertNotIn("collapsed", secs["Identification"])
        # bind/parse are unaffected — hidden sections just post blanks
        bound = checklistforms.bind(schema, None)
        self.assertEqual(bound["sections"][1]["when"]["key"], "f0-2")

    def test_item_fields_default_to_all_and_accept_a_subset(self):
        # #103: absent = every standard field; a list = that subset
        self.assertEqual(checklistforms.normalize(SCHEMA, NAME)["item_fields"],
                         checklistforms.ITEM_FIELDS)
        cfg = {**SCHEMA, "item_fields": ["status", "bogus", "location"]}
        self.assertEqual(checklistforms.normalize(cfg, NAME)["item_fields"],
                         ["status", "location"])
        self.assertEqual(checklistforms.normalize({**SCHEMA, "item_fields": []}, NAME)["item_fields"], [])

    def test_item_values_diff_against_the_record(self):
        schema = checklistforms.normalize(SCHEMA, NAME)
        item = {"status": {"id": 120}, "is_installed": False, "qaqc_uploaded": True,
                "certified_qaqc": False, "manufacturer": None, "location": {"id": 5, "name": "FNAL"},
                "serial_number": "SN-1", "comments": "c"}
        opts = {"manufacturers": [{"value": 8, "label": "Acme"}],
                "institutions": [{"value": 128, "label": "BNL"}]}
        iv = checklistforms.item_values(schema, ITEM_POST, item, opts)
        self.assertEqual(iv["patch"], {"manufacturer": {"id": 8}, "status": {"id": 130}})
        self.assertEqual(iv["location"], {"id": 128})               # changed from FNAL
        self.assertEqual(iv["test_comments"], "looks fine")
        self.assertEqual(iv["record"]["Manufacturer"], {"id": 8, "name": "Acme"})
        self.assertEqual(iv["record"]["Component status"]["name"], "QA/QC Tests - Non-conforming")
        self.assertEqual(iv["record"]["Location"], {"id": 128, "name": "BNL"})
        self.assertTrue(iv["record"]["QA/QC uploaded"])
        self.assertFalse(iv["record"]["Certified QA/QC"])
        # no card in the POST (older drafts / tests) → nothing at all
        self.assertIsNone(checklistforms.item_values(schema, {"f0-0": "x"}, item, opts))
        # same values as the record → empty patch, no location
        same = {"item-card": "1", "item-status": "120", "item-qaqc_uploaded": "on",
                "item-serial_number": "SN-1", "item-item_comments": "c", "item-location": "5"}
        iv2 = checklistforms.item_values(schema, same, item, opts)
        self.assertEqual(iv2["patch"], {})
        self.assertIsNone(iv2["location"])

    def test_available_swallows_failures(self):
        api = mock.MagicMock()
        api.get_component_type_images.side_effect = RuntimeError("boom")
        self.assertEqual(checklistforms.available(api, PTID), [])
        self.assertEqual(checklistforms.available(None, PTID, rows=object()), [])

    def test_normalize_drops_unknown_and_malformed_keeps_rows(self):
        s = checklistforms.normalize(SCHEMA, NAME)
        self.assertEqual(s["name"], "PCB Segments Interface")
        self.assertEqual(s["test_type_name"], "PCB Segments Interface")
        vi = s["sections"][2]
        labels = [f["label"] for f in vi["fields"]]
        self.assertNotIn("Bogus", labels)
        self.assertNotIn("No options", labels)
        # the row groups its children, each leaf carries a stable key
        row = s["sections"][1]["fields"][0]
        self.assertEqual(row["type"], "row")
        self.assertEqual([k["key"] for k in row["fields"]], ["f1-0-0", "f1-0-1"])
        # nominal ± tol becomes min/max and a display range
        table = s["sections"][1]["fields"][1]
        self.assertEqual((table["min"], table["max"]), (1.5, 1.7))
        self.assertEqual(table["range"], "1.5 – 1.7")

    def test_parse_typed_values(self):
        s = checklistforms.normalize(SCHEMA, NAME)
        data = checklistforms.parse(s, {
            "f0-0": " PCB0001 ",              # qr → stripped string
            "f0-2": "C",                      # select
            "f1-0-0": "1709.5",               # number → float
            "f1-0-1": "about 12",             # unparseable → kept verbatim
            "f1-1-c0": "1.6", "f1-1-c1": "",  # table: blank cell omitted
            "f2-0": "pass",                   # tri-state → True
            "f2-3-s0": "on",                  # step 1 done, step 2 not
        })
        self.assertEqual(data["Identification"],
                         {"PCB Batch PID": "PCB0001", "Segment type": "C"})
        self.assertEqual(data["Measurements"],
                         {"Dim 1": 1709.5, "Dim 2": "about 12",
                          "Thickness": {"P1": 1.6}})
        self.assertEqual(data["Visual Inspection"],
                         {"Planarity": True,
                          "Procedure": {"Unwrap": True, "Inspect": False}})

    def test_parse_omits_blank_and_untouched(self):
        s = checklistforms.normalize(SCHEMA, NAME)
        self.assertEqual(checklistforms.parse(s, {"f2-0": ""}), {
            "Visual Inspection": {   # steps always post (all unchecked)
                "Procedure": {"Unwrap": False, "Inspect": False}}})

    def test_bind_fills_values_from_a_previous_submission(self):
        s = checklistforms.normalize(SCHEMA, NAME)
        b = checklistforms.bind(s, {"DATA": {
            "Identification": {"Segment type": "C"},
            "Measurements": {"Dim 1": 1709.5, "Thickness": {"P2": 1.62}},
            "Visual Inspection": {
                "Planarity": False,
                "Photo 1": {"image_id": "img-1", "image_name": "p.jpg"},
                "Procedure": {"Unwrap": True}},
        }})
        self.assertEqual(b["sections"][0]["fields"][2]["value"], "C")
        row = b["sections"][1]["fields"][0]
        self.assertEqual(row["fields"][0]["value"], "1709.5")
        self.assertEqual(row["fields"][1]["value"], "")
        cells = b["sections"][1]["fields"][1]["cells"]
        self.assertEqual([c["value"] for c in cells], ["", "1.62"])
        self.assertEqual([c["name"] for c in cells], ["f1-1-c0", "f1-1-c1"])
        vi = b["sections"][2]["fields"]
        self.assertEqual(vi[0]["value"], "fail")
        self.assertEqual(vi[2]["existing"]["image_id"], "img-1")
        self.assertEqual([i["done"] for i in vi[3]["items"]], [True, False])


class ChecklistPageTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("c", "c@c.io", "pw")
        self.client.force_login(self.user)

    def test_renders_every_field_type(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(PAGE).content.decode()
        self.assertIn("PCB Segments Interface", html)
        self.assertIn("Identification", html)                 # section cards
        self.assertIn('name="f0-0"', html)                    # qr input
        self.assertIn("cl-scan", html)                        # …with a Scan button
        self.assertIn('type="datetime-local"', html)
        self.assertIn("<option>C</option>", html)             # select options
        self.assertIn('data-min="1.5"', html)                 # tolerance attrs
        self.assertIn('data-max="1.7"', html)
        self.assertIn("allowed 1.5 – 1.7", html)
        self.assertIn('value="pass"', html)                   # tri-state radios
        self.assertIn('type="file" id="f2-2" name="f2-2"', html)   # photo
        self.assertIn('cl-photo-cam" data-target="f2-2"', html)   # camera button
        self.assertIn("Unwrap", html)                         # steps
        self.assertIn("https://edms.cern.ch/x", html)         # static link
        self.assertNotIn("Bogus", html)                       # unknown dropped
        self.assertIn("Submit to HWDB", html)

    def test_sections_fold_and_follow_a_select(self):
        cfg = json.loads(json.dumps(SCHEMA))
        cfg["sections"][1]["when"] = {"field": "Segment type", "equals": "J"}
        cfg["sections"][2]["collapsed"] = True
        api = _api(schema=cfg)
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(PAGE).content.decode()
        self.assertIn('data-when-key="f0-2" data-when-eq="J"', html)
        self.assertIn("shown when Segment type = J", html)
        self.assertIn('class="es-card cl-sec cl-folded"', html)       # opens folded
        self.assertIn('class="cl-fold" aria-expanded="false">Visual Inspection', html)
        self.assertIn('class="cl-fold" aria-expanded="true">Identification', html)
        self.assertIn("clApplyWhen", html)                             # behavior script

    def test_item_card_renders_prefilled_from_the_record(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(PAGE).content.decode()
        self.assertIn('name="item-card" value="1"', html)
        self.assertIn("<option value=\"8\">Acme</option>", html)          # type's manufacturers
        self.assertIn('<option value="120" selected>QA/QC Tests - Passed All', html)
        self.assertIn('name="item-qaqc_uploaded" checked', html)
        self.assertIn('name="item-certified_qaqc">', html)                  # unchecked
        self.assertIn('name="item-location"', html)
        self.assertIn(">BNL</option>", html)
        self.assertIn('name="item-serial_number" value="SN-1"', html)
        self.assertIn("Test comments", html)

    def test_no_item_card_when_the_schema_opts_out(self):
        api = _api(schema={**SCHEMA, "item_fields": []})
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(PAGE).content.decode()
            self.client.post(PAGE, {"f0-0": "x", **ITEM_POST})
        self.assertNotIn("item-card", html)
        api.patch_component.assert_not_called()
        api.post_location.assert_not_called()

    def test_submit_writes_item_fields_then_location_then_record(self):
        api = _api(test_types=("PCB Segments Interface",))
        m1, m2 = _mocked(api)
        with m1, m2:
            self.client.post(PAGE, {"f0-0": "PCB0001", **ITEM_POST})
        self.assertEqual(api.patch_component.call_args.args[1],
                         {"part_id": PART, "manufacturer": {"id": 8}, "status": {"id": 130}})
        loc = api.post_location.call_args.args[1]
        self.assertEqual(loc["location"], {"id": 128})
        self.assertTrue(loc["arrived"].startswith("2026-08-26T10:00"))
        payload = api.post_test.call_args.args[1]
        self.assertEqual(payload["comments"], "looks fine")                 # test comments
        self.assertEqual(payload["test_data"]["DATA"]["Item"]["Manufacturer"], {"id": 8, "name": "Acme"})
        self.assertEqual(payload["test_data"]["DATA"]["Identification"]["PCB Batch PID"], "PCB0001")
        calls = [c[0] for c in api.method_calls]
        self.assertLess(calls.index("patch_component"), calls.index("post_location"))
        self.assertLess(calls.index("post_location"), calls.index("post_test"))

    def test_unchanged_item_fields_skip_the_writes(self):
        api = _api(test_types=("PCB Segments Interface",))
        m1, m2 = _mocked(api)
        with m1, m2:
            self.client.post(PAGE, {"f0-0": "PCB0001", "item-card": "1", "item-status": "120",
                                    "item-qaqc_uploaded": "on", "item-serial_number": "SN-1",
                                    "item-item_comments": "c"})
        api.patch_component.assert_not_called()
        api.post_location.assert_not_called()
        api.post_test.assert_called_once()

    def test_prefills_from_the_latest_submission(self):
        api = _api(prev={"DATA": {
            "Measurements": {"Dim 1": 1709.5},
            "Visual Inspection": {
                "Planarity": True,
                "Photo 1": {"image_id": "img-1", "image_name": "p.jpg"}}}})
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(PAGE).content.decode()
        self.assertIn('value="1709.5"', html)
        self.assertIn("Pre-filled from the latest submission", html)
        self.assertIn("p.jpg", html)                          # existing photo linked
        # the checked tri-state: pass radio carries checked
        self.assertIn('value="pass"\n      checked', html.replace("\r", ""))

    def test_submit_posts_photos_first_then_the_test_record(self):
        api = _api()   # type list carries only "ES" → checklist type auto-created
        m1, m2 = _mocked(api)
        with m1, m2:
            self.client.post(PAGE, {
                "f0-0": "PCB0001", "f0-2": "C",
                "f1-0-0": "1709.5", "f1-1-c0": "1.6",
                "f2-0": "fail", "f2-3-s0": "on",
                "f2-2": SimpleUploadedFile("shot.png", PNG,
                                           content_type="image/png"),
            })
        # photo posted onto the item, named for part/checklist/slot
        img_name = api.post_component_image.call_args.args[2]
        self.assertTrue(img_name.startswith(f"CLPhoto_{PART}_{NAME}_f2-2_"))
        # missing test type created (TestTypeIn shape)
        tt = api.post_test_type.call_args.args[1]
        self.assertEqual(tt["name"], "PCB Segments Interface")
        # the record carries the parsed DATA incl. the fresh photo reference
        payload = api.post_test.call_args.args[1]
        self.assertEqual(payload["test_type"], "PCB Segments Interface")
        data = payload["test_data"]["DATA"]
        self.assertEqual(data["Identification"]["PCB Batch PID"], "PCB0001")
        self.assertEqual(data["Measurements"]["Thickness"], {"P1": 1.6})
        self.assertEqual(data["Visual Inspection"]["Planarity"], False)
        self.assertEqual(data["Visual Inspection"]["Photo 1"],
                         {"image_id": "img-77", "image_name": img_name})
        # ordering: the photo upload happened before the record post
        calls = [c[0] for c in api.mock_calls]
        self.assertLess(calls.index("post_component_image"),
                        calls.index("post_test"))

    def test_submit_keeps_the_previous_photo_without_a_new_file(self):
        api = _api(prev={"DATA": {"Visual Inspection": {
            "Photo 1": {"image_id": "img-old", "image_name": "old.jpg"}}}},
            test_types=("ES", "PCB Segments Interface"))
        m1, m2 = _mocked(api)
        with m1, m2:
            self.client.post(PAGE, {"f2-0": "pass"})
        api.post_component_image.assert_not_called()
        api.post_test_type.assert_not_called()    # type already defined
        data = api.post_test.call_args.args[1]["test_data"]["DATA"]
        self.assertEqual(data["Visual Inspection"]["Photo 1"],
                         {"image_id": "img-old", "image_name": "old.jpg"})

    def test_submit_rejects_a_non_image_photo(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            self.client.post(PAGE, {
                "f2-2": SimpleUploadedFile("notes.txt", b"hi",
                                           content_type="text/plain")})
        api.post_test.assert_not_called()

    def test_unknown_checklist_404s(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.get(f"/hw/dev/part/{PART}/checklist/Nope/")
        self.assertEqual(resp.status_code, 404)

    def test_forbidden_off_a_write_instance(self):
        with override_settings(HWDB_WRITE_INSTANCES=["prod"]):
            resp = self.client.get(PAGE)
        self.assertEqual(resp.status_code, 403)

    def test_anonymous_is_redirected_to_login(self):
        self.client.logout()
        resp = self.client.get(PAGE)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("login", resp["Location"])


# ---- #96: item-spec destination + subcomponent links -------------------------

SCHEMA96 = {
    "name": "Panel prep",
    "test_type_name": "Panel prep",
    "sections": [
        {"title": "Facts", "fields": [
            {"type": "text", "label": "Vendor", "to_spec": True},
            {"type": "number", "label": "X dimension", "to_spec": True},
            {"type": "text", "label": "Operator"},                # NOT to_spec
            {"type": "photo", "label": "Shot", "to_spec": True},  # incapable → off
        ]},
        {"title": "Assembly", "fields": [
            {"type": "link", "label": "FEB board", "position": "FEB1"},
            {"type": "link", "label": "Any cable"},               # auto-position
        ]},
    ],
}


class SpecAndLinkTest(TestCase):
    """#96 runtime: ``to_spec`` values fold into the item's specifications;
    ``link`` fields patch the item's subcomponents ahead of the record."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("s", "s@s.io", "pw")
        self.client.force_login(self.user)

    def _api96(self, **kw):
        api = _api(schema=SCHEMA96, **kw)
        api.get_component.return_value = {"data": {
            "serial_number": "SN-1", "comments": "c",
            "manufacturer": {"id": 7},
            "specifications": [{"Old": 1, "DATA": {"Kept": "yes"}}]}}
        api.get_component_type.return_value = {"data": {
            "connectors": {"FEB1": "D05700300001", "CBL1": "D08100100003"},
            "properties": {"specifications": [{"datasheet": {"DATA": {}}}]}}}
        api.get_subcomponents.return_value = {"data": [
            {"functional_position": "CBL1", "part_id": None}]}
        api.patch_component.return_value = {"status": "OK"}
        api.patch_subcomponents.return_value = {"status": "OK"}
        return api

    def test_spec_write_needs_data_on_the_type(self):
        # #100: HWDB validates item spec keys against the type template —
        # without DATA there, a non-architect gets told, not a cryptic 400
        api = self._api96()
        api.get_component_type.return_value["data"]["properties"] = {}
        m1, m2 = _mocked(api)
        with m1, m2, mock.patch("explore.views._is_architect", return_value=False):
            self.client.post(PAGE, {"f0-0": "Acme"}, follow=True)
        api.patch_component.assert_not_called()
        api.patch_component_type.assert_not_called()
        api.post_test.assert_not_called()

    def test_architect_gets_data_defined_on_the_type_first(self):
        api = self._api96()
        api.get_component_type.return_value["data"]["properties"] = {
            "specifications": [{"datasheet": {"Note": ""}}]}
        api.patch_component_type.return_value = {"status": "OK"}
        m1, m2 = _mocked(api)
        with m1, m2, mock.patch("explore.views._is_architect", return_value=True):
            self.client.post(PAGE, {"f0-0": "Acme"})
        env = api.patch_component_type.call_args.args[1]
        self.assertEqual(env["properties"]["specifications"]["datasheet"],
                         {"Note": "", "DATA": {}})
        calls = [c[0] for c in api.method_calls]
        self.assertLess(calls.index("patch_component_type"), calls.index("patch_component"))
        api.post_test.assert_called_once()

    def test_normalize_flags(self):
        s = checklistforms.normalize(SCHEMA96, NAME)
        facts = s["sections"][0]["fields"]
        self.assertTrue(facts[0]["to_spec"])
        self.assertFalse(facts[2]["to_spec"])
        self.assertFalse(facts[3]["to_spec"])      # photo can't go to spec
        links = s["sections"][1]["fields"]
        self.assertEqual(links[0]["position"], "FEB1")
        self.assertEqual(links[1]["position"], "")

    def test_form_shows_which_fields_go_to_the_item_specs(self):
        # #96 review: the flag must be visible on the rendered form, not just
        # in the schema JSON — the operator should know where a value lands.
        api = _api(schema=SCHEMA96)
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(PAGE).content.decode()
        self.assertEqual(html.count("also saved to the item"), 2)

    def test_spec_values_and_link_requests(self):
        s = checklistforms.normalize(SCHEMA96, NAME)
        data = checklistforms.parse(s, {
            "f0-0": "Acme", "f0-1": "3366", "f0-2": "cz",
            "f1-0": "D05700300001-00012"})
        self.assertEqual(checklistforms.spec_values(s, data),
                         {"Facts": {"Vendor": "Acme", "X dimension": 3366.0}})
        self.assertEqual(checklistforms.link_requests(s, data), [
            {"label": "FEB board", "pid": "D05700300001-00012",
             "position": "FEB1"}])

    def test_resubmission_replaces_the_sections_it_owns(self):
        # #98 review: the item's DATA had this checklist's earlier sections
        # (one since renamed, one with a since-removed label) plus a key
        # someone else wrote — only the owned sections get replaced
        api = self._api96(prev={"DATA": {"Old facts": {"Vendor": "Z"}}})
        api.get_component.return_value["data"]["specifications"] = [{"DATA": {
            "Kept": "yes",
            "Old facts": {"Vendor": "Z"},                 # previous section name → dropped
            "Facts": {"Vendor": "Z", "Stale": 1}}}]      # owned → replaced
        m1, m2 = _mocked(api)
        with m1, m2:
            self.client.post(PAGE, {"f0-0": "Acme"})
        spec = api.patch_component.call_args.args[1]["specifications"]
        self.assertEqual(spec["DATA"], {"Kept": "yes", "Facts": {"Vendor": "Acme"}})

    def test_unchanged_specs_skip_the_patch(self):
        api = self._api96(prev={"DATA": {"Facts": {"Vendor": "Acme"}}})
        api.get_component.return_value["data"]["specifications"] = [{"DATA": {
            "Kept": "yes", "Facts": {"Vendor": "Acme"}}}]
        m1, m2 = _mocked(api)
        with m1, m2:
            self.client.post(PAGE, {"f0-0": "Acme"})
        api.patch_component.assert_not_called()
        api.post_test.assert_called_once()

    def test_submit_patches_specs_and_links_before_the_record(self):
        api = self._api96(test_types=("Panel prep",))
        m1, m2 = _mocked(api)
        with m1, m2:
            self.client.post(PAGE, {
                "f0-0": "Acme", "f0-2": "cz",
                "f1-0": "D05700300001-00012",       # named position
                "f1-1": "D08100100003-00226"})      # auto → first free CBL slot
        # the link patch carries the COMPLETE positions dict
        sub_payloads = [c.args[1] for c in api.patch_subcomponents.call_args_list]
        self.assertEqual(sub_payloads[0]["subcomponents"],
                         {"FEB1": "D05700300001-00012", "CBL1": None})
        self.assertEqual(sub_payloads[1]["subcomponents"]["CBL1"],
                         "D08100100003-00226")
        # the spec patch folds to_spec values into the latest entry's DATA
        spec = api.patch_component.call_args.args[1]["specifications"]
        self.assertEqual(spec["DATA"], {"Kept": "yes", "Facts": {"Vendor": "Acme"}})
        self.assertEqual(spec["Old"], 1)            # datasheet keys ride through
        # …and the record still posts, carrying everything incl. the PIDs
        data = api.post_test.call_args.args[1]["test_data"]["DATA"]
        self.assertEqual(data["Facts"]["Operator"], "cz")
        self.assertEqual(data["Assembly"]["FEB board"], "D05700300001-00012")
        calls = [c[0] for c in api.mock_calls]
        self.assertLess(calls.index("patch_subcomponents"), calls.index("post_test"))
        self.assertLess(calls.index("patch_component"), calls.index("post_test"))

    def test_no_spec_patch_when_nothing_is_flagged(self):
        api = self._api96(test_types=("Panel prep",))
        m1, m2 = _mocked(api)
        with m1, m2:
            self.client.post(PAGE, {"f0-2": "cz"})   # only the manual field
        api.patch_component.assert_not_called()
        api.patch_subcomponents.assert_not_called()

    def test_link_failure_aborts_the_submission(self):
        api = self._api96()
        api.get_subcomponents.return_value = {"data": [
            {"functional_position": "FEB1", "part_id": "D05700300001-09999"}]}
        m1, m2 = _mocked(api)
        with m1, m2:
            self.client.post(PAGE, {"f1-0": "D05700300001-00012"})
        api.patch_subcomponents.assert_not_called()   # occupied by another pid
        api.post_test.assert_not_called()

    def test_already_linked_child_is_a_noop_success(self):
        api = self._api96(test_types=("Panel prep",))
        api.get_subcomponents.return_value = {"data": [
            {"functional_position": "FEB1", "part_id": "D05700300001-00012"}]}
        m1, m2 = _mocked(api)
        with m1, m2:
            self.client.post(PAGE, {"f1-0": "D05700300001-00012"})
        api.patch_subcomponents.assert_not_called()
        api.post_test.assert_called_once()


# ---- #96: the structured editor + live preview -------------------------------

CONFIG_PAGE = f"/hw/dev/checklist-config/{PTID}/"


class ChecklistEditorTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("e", "e@e.io", "pw")
        self.client.force_login(self.user)

    def test_new_checklist_starts_blank_with_templates(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(CONFIG_PAGE).content.decode()
        self.assertIn("Create a checklist", html)
        self.assertIn("clc-initial", html)                 # skeleton JSON
        self.assertIn("PCB Segments Interface", html)      # repo templates offered
        self.assertIn("PCB Panel Interface", html)
        self.assertIn(f"?name=Reception", html)            # existing listed
        self.assertIn("pair &#8593;", html)                # row pairing control
        self.assertIn("&#8594; Specs", html)               # to_spec control

    def test_editing_an_existing_checklist_loads_its_raw_json(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(f"{CONFIG_PAGE}?name={NAME}").content.decode()
        self.assertIn("Edit a checklist", html)
        self.assertIn(f"Checklist_{PTID}_{NAME}.json", html)
        self.assertIn("PCB Batch PID", html)               # raw schema embedded

    def test_save_posts_the_named_schema_file(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            self.client.post(CONFIG_PAGE, {
                "cl_name": "Assembly",
                "config_json": json.dumps({"name": "A", "test_type_name": "T",
                                           "sections": []})})
        args = api.post_component_type_image.call_args
        self.assertEqual(args.args[0], PTID)
        self.assertEqual(args.args[2], f"Checklist_{PTID}_Assembly.json")

    def test_save_rejects_bad_names_and_bad_json(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            self.client.post(CONFIG_PAGE, {"cl_name": "", "config_json": "{}"})
            self.client.post(CONFIG_PAGE, {"cl_name": "a/b", "config_json": "{}"})
            self.client.post(CONFIG_PAGE, {"cl_name": "ok", "config_json": "{nope"})
        api.post_component_type_image.assert_not_called()

    def test_preview_renders_the_runtime_form(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.post(f"{CONFIG_PAGE}preview/", {
                "config_json": json.dumps(SCHEMA), "cl_name": NAME,
            }).content.decode()
        self.assertIn("Identification", html)              # real section cards
        self.assertIn('name="item-card"', html)            # #103 Item card previews too
        self.assertIn('data-min="1.5"', html)              # real tolerance attrs
        self.assertIn('value="pass"', html)                # real tri-state
        self.assertNotIn("<form", html)                    # fragment only

    def test_preview_tolerates_garbage(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.post(f"{CONFIG_PAGE}preview/",
                                    {"config_json": "{nope"}).content.decode()
        self.assertIn("isn’t valid JSON", html)

    def test_editor_offers_roles(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(CONFIG_PAGE).content.decode()
        self.assertIn('id="f-roles"', html)
        self.assertIn("ff-imgfile", html)   # reference-image upload control
        self.assertIn("fs-whenf", html)     # #98 show-only-when pickers
        self.assertEqual(html.count('class="f-itemf"'), 9)   # #103 item-field strip
        self.assertIn("fs-collapsed", html)
        self.assertIn("Variant-dependent sections", html)   # the H/J template

    def test_asset_upload_posts_onto_the_type(self):
        api = _api()
        api.post_component_type_image.return_value = {"status": "OK",
                                                      "image_id": "ref-9"}
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post(f"{CONFIG_PAGE}asset/", {
                "image": SimpleUploadedFile("p1-p10.png", PNG,
                                            content_type="image/png")})
        self.assertEqual(resp.json()["image_id"], "ref-9")
        args = api.post_component_type_image.call_args
        self.assertEqual(args.args[0], PTID)
        self.assertTrue(args.args[2].startswith(f"ChecklistImage_{PTID}_"))
        self.assertIn("p1-p10.png", args.kwargs["comments"])

    def test_asset_upload_rejects_non_images(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post(f"{CONFIG_PAGE}asset/", {
                "image": SimpleUploadedFile("notes.txt", b"hi",
                                            content_type="text/plain")})
        self.assertEqual(resp.status_code, 400)
        api.post_component_type_image.assert_not_called()

    def test_static_image_id_renders_through_the_proxy(self):
        cfg = {**SCHEMA, "sections": [{"title": "Guide", "fields": [
            {"type": "static", "label": "Where to measure",
             "image_id": "ref-9"}]}]}
        s = checklistforms.normalize(cfg, NAME)
        self.assertEqual(s["sections"][0]["fields"][0]["image_id"], "ref-9")
        api = _api(schema=cfg)
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(PAGE).content.decode()
        self.assertIn("/hw/dev/shipment-image/ref-9/", html)


# ---- #97: drafts, CSV export, roles gate, new-item flow ----------------------

class DraftAndExportTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("d", "d@d.io", "pw")
        self.client.force_login(self.user)

    def _actor(self):
        # no FNAL link in the test session — actor_of falls back to the
        # Django username
        return self.user.get_username()

    def test_save_draft_stores_parsed_data_and_posts_nothing(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            self.client.post(PAGE, {"action": "draft",
                                    "f0-0": "PCB0001", "f1-0-0": "1709.5"})
        api.post_test.assert_not_called()
        api.post_component_image.assert_not_called()
        d = ChecklistDraft.objects.get()
        self.assertEqual(d.part_id, PART)
        self.assertEqual(d.name, NAME)
        self.assertEqual(d.data["Identification"]["PCB Batch PID"], "PCB0001")
        self.assertEqual(d.data["Measurements"]["Dim 1"], 1709.5)

    def test_draft_prefills_and_wins_over_the_last_submission(self):
        api = _api(prev={"DATA": {
            "Identification": {"PCB Batch PID": "OLD"},
            "Visual Inspection": {
                "Photo 1": {"image_id": "img-1", "image_name": "p.jpg"}}}})
        ChecklistDraft.objects.create(
            instance="dev", part_id=PART, name=NAME, username=self._actor(),
            data={"Identification": {"PCB Batch PID": "DRAFTED"}})
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(PAGE).content.decode()
        self.assertIn('value="DRAFTED"', html)      # draft wins the field
        self.assertNotIn('value="OLD"', html)
        self.assertIn("p.jpg", html)                # photo reference survives
        self.assertIn("Draft from", html)           # banner + discard control
        self.assertIn("discard_draft", html)

    def test_submit_deletes_the_draft(self):
        api = _api(test_types=("ES", "PCB Segments Interface"))
        ChecklistDraft.objects.create(
            instance="dev", part_id=PART, name=NAME, username=self._actor(),
            data={"Identification": {"PCB Batch PID": "DRAFTED"}})
        m1, m2 = _mocked(api)
        with m1, m2:
            self.client.post(PAGE, {"f0-0": "PCB0001"})
        api.post_test.assert_called_once()
        self.assertEqual(ChecklistDraft.objects.count(), 0)

    def test_discard_draft(self):
        api = _api()
        ChecklistDraft.objects.create(
            instance="dev", part_id=PART, name=NAME, username=self._actor(),
            data={})
        m1, m2 = _mocked(api)
        with m1, m2:
            self.client.post(PAGE, {"action": "discard_draft"})
        self.assertEqual(ChecklistDraft.objects.count(), 0)
        api.post_test.assert_not_called()

    def test_csv_export_of_the_latest_submission(self):
        api = _api(prev={"DATA": {
            "Identification": {"PCB Batch PID": "PCB0001", "Segment type": "C"},
            "Measurements": {"Thickness": {"P1": 1.6}},
            "Visual Inspection": {
                "Photo 1": {"image_id": "img-1", "image_name": "p.jpg"}}}})
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.get(f"{PAGE}?export=csv")
        self.assertEqual(resp["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn(f"Checklist_{PART}_{NAME}.csv", resp["Content-Disposition"])
        body = resp.content.decode()
        self.assertIn("PCB0001", body)
        self.assertIn('"{""P1"": 1.6}"', body)              # dict → JSON cell
        self.assertIn("p.jpg (image_id=img-1)", body)       # photo flattened
        self.assertNotIn("Drawing", body)                   # static skipped

    def test_email_button_carries_a_mailto_draft(self):
        api = _api(prev={"DATA": {
            "Identification": {"PCB Batch PID": "PCB0001"},
            "Measurements": {"Thickness": {"P1": 1.6}}}})
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(PAGE).content.decode()
        self.assertIn('href="mailto:?subject=Checklist%20PCB%20Segments%20Interface', html)
        self.assertIn("Identification%20/%20PCB%20Batch%20PID%3A%20PCB0001", html)
        self.assertIn(f"http%3A//testserver{PAGE}", html.replace("%2F", "/"))
        self.assertIn("Email</a>", html)

    def test_email_button_absent_without_a_submission(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(PAGE).content.decode()
        self.assertNotIn("mailto:", html)

    def test_email_body_skips_blanks_and_truncates(self):
        schema = checklistforms.normalize(SCHEMA, NAME)
        body = checklistforms.email_body(schema, PART, {"DATA": {
            "Identification": {"PCB Batch PID": "PCB0001"}}}, "http://x/p", "2026-08-26 10:00")
        self.assertIn("Submitted: 2026-08-26 10:00", body)
        self.assertIn("Identification / PCB Batch PID: PCB0001", body)
        self.assertNotIn("Dim 1", body)                       # blank → skipped
        self.assertNotIn("Drawing", body)                     # static → skipped
        long = checklistforms.email_body(schema, PART, {"DATA": {
            "Visual Inspection": {"Anomaly description": "x" * 5000}}}, "http://x/p")
        self.assertLess(len(long), checklistforms.EMAIL_BODY_MAX + 100)
        self.assertIn("truncated", long)

    def test_csv_export_without_a_submission_redirects(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.get(f"{PAGE}?export=csv")
        self.assertEqual(resp.status_code, 302)


CFG_GATED = {**SCHEMA, "roles": [41]}


class RolesGateTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("r", "r@r.io", "pw")
        self.client.force_login(self.user)

    def _whoami(self, api, role_ids):
        api.whoami.return_value = {"data": {
            "roles": [{"id": r, "name": f"role{r}"} for r in role_ids]}}

    def test_submission_refused_without_the_role(self):
        api = _api(schema=CFG_GATED, test_types=("PCB Segments Interface",))
        self._whoami(api, [7])
        m1, m2 = _mocked(api)
        with m1, m2:
            self.client.post(PAGE, {"f0-0": "PCB0001"})
        api.post_test.assert_not_called()

    def test_submission_allowed_with_the_role(self):
        api = _api(schema=CFG_GATED, test_types=("PCB Segments Interface",))
        self._whoami(api, [41, 7])
        m1, m2 = _mocked(api)
        with m1, m2:
            self.client.post(PAGE, {"f0-0": "PCB0001"})
        api.post_test.assert_called_once()

    def test_form_names_the_required_roles(self):
        api = _api(schema=CFG_GATED)
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(PAGE).content.decode()
        self.assertIn("requires HWDB role id", html)
        self.assertIn("41", html)

    def test_ungated_schema_never_calls_whoami(self):
        api = _api(test_types=("PCB Segments Interface",))
        m1, m2 = _mocked(api)
        with m1, m2:
            self.client.post(PAGE, {"f0-0": "PCB0001"})
        api.whoami.assert_not_called()
        api.post_test.assert_called_once()


NEW_PAGE = f"/hw/dev/part-new/{PTID}/"
NEW_PID = f"{PTID}-00777"


class ItemCreateTest(TestCase):
    """#97: the separate New-Item page — create first, then land in the
    type's checklist (one continuous motion when there's exactly one)."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("n", "n@n.io", "pw")
        self.client.force_login(self.user)

    def _api_create(self, **kw):
        api = _api(**kw)
        api.get_institutions.return_value = {"data": [
            {"id": 128, "name": "BNL", "country": {"code": "US"}}]}
        api.get_component_type.return_value = {"data": {
            "manufacturers": [{"id": 7}],
            "properties": {"specifications": [{"datasheet": {"Note": ""}}]}}}
        api.create_component.return_value = {"status": "OK", "part_id": NEW_PID}
        return api

    def test_form_renders_with_institutions_and_checklist_hint(self):
        api = self._api_create()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(NEW_PAGE).content.decode()
        self.assertIn('name="institution_id"', html)
        self.assertIn("BNL", html)
        self.assertIn("Create the item", html)
        self.assertIn(NAME, html)      # tells the user which checklist is next

    def test_create_lands_in_the_single_checklist(self):
        api = self._api_create()
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post(NEW_PAGE, {
                "institution_id": "128", "serial_number": "SN-9"})
        payload = api.create_component.call_args.args[1]
        self.assertEqual(payload["institution"], {"id": 128})
        self.assertEqual(payload["country_code"], "US")
        self.assertEqual(payload["serial_number"], "SN-9")
        self.assertEqual(payload["manufacturer"], {"id": 7})
        self.assertEqual(resp["Location"],
                         f"/hw/dev/part/{NEW_PID}/checklist/{NAME}/")
        api.post_test.assert_not_called()     # creation posts no record

    def test_create_lands_on_the_part_page_with_several_checklists(self):
        api = self._api_create()
        api.get_component_type_images.return_value = {"data": [
            {"image_id": "a", "created": "2026-08-01T00:00:00",
             "image_name": f"Checklist_{PTID}_Reception.json"},
            {"image_id": "b", "created": "2026-08-01T00:00:00",
             "image_name": f"Checklist_{PTID}_Assembly.json"}]}
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post(NEW_PAGE, {"institution_id": "128"})
        self.assertEqual(resp["Location"], f"/hw/dev/part/{NEW_PID}/")

    def test_create_triggers_an_incremental_mirror_sync(self):
        # #97 review: the fresh item must show in the mirror without a
        # manual "sync new" on the type page.
        api = self._api_create()
        m1, m2 = _mocked(api)
        with m1, m2, mock.patch("explore.views.sync_test_events",
                                return_value=iter(["ok\n"])) as sync:
            self.client.post(NEW_PAGE, {"institution_id": "128"})
        self.assertEqual(sync.call_args.args[2], PTID)
        self.assertEqual(sync.call_args.kwargs["mode"], "incremental")

    def test_spec_template_shown_and_non_architect_warned(self):
        # #100: the type's datasheet has no DATA → the page says "→ Specs"
        # can't save yet; the item is created from the template AS IS (HWDB
        # validates item spec keys against the type — no seeding)
        api = self._api_create()
        m1, m2 = _mocked(api)
        with m1, m2, mock.patch("explore.views._is_architect", return_value=False):
            html = self.client.get(NEW_PAGE).content.decode()
            self.client.post(NEW_PAGE, {"institution_id": "128", "define_type_data": "1"})
        self.assertIn("Item Specs template", html)
        self.assertIn("&quot;Note&quot;: &quot;&quot;", html)          # pretty JSON shown
        self.assertIn("can't save on this type until", html)
        self.assertNotIn('name="define_type_data"', html)            # not an architect
        payload = api.create_component.call_args.args[1]
        self.assertEqual(payload["specifications"], {"Note": ""})
        api.patch_component_type.assert_not_called()                 # gate holds on POST too

    def test_architect_can_define_data_on_the_type(self):
        api = self._api_create()
        api.get_component_type.return_value["data"]["connectors"] = {"Slot 1": "Z001"}
        api.get_component_type.return_value["data"]["full_name"] = "A.B.C"
        api.patch_component_type.return_value = {"status": "OK"}
        m1, m2 = _mocked(api)
        with m1, m2, mock.patch("explore.views._is_architect", return_value=True):
            html = self.client.get(NEW_PAGE).content.decode()
            self.client.post(NEW_PAGE, {"institution_id": "128", "define_type_data": "1"})
        self.assertIn('name="define_type_data" value="1" checked', html)
        env = api.patch_component_type.call_args.args[1]
        self.assertEqual(env["properties"]["specifications"]["datasheet"],
                         {"Note": "", "DATA": {}})                   # merged, not replaced
        self.assertNotIn("connectors", env)     # echoing them is refused once positions are in use
        self.assertEqual(env["name"], "A.B.C")
        # the type now defines DATA → the new item carries it from the start
        self.assertEqual(api.create_component.call_args.args[1]["specifications"],
                         {"Note": "", "DATA": {}})

    def test_type_patch_failure_creates_the_item_without_data(self):
        api = self._api_create()
        api.patch_component_type.return_value = {"status": "Error", "data": "nope"}
        m1, m2 = _mocked(api)
        with m1, m2, mock.patch("explore.views._is_architect", return_value=True):
            self.client.post(NEW_PAGE, {"institution_id": "128", "define_type_data": "1"})
        self.assertEqual(api.create_component.call_args.args[1]["specifications"],
                         {"Note": ""})

    def test_existing_data_template_is_left_alone(self):
        api = self._api_create()
        api.get_component_type.return_value["data"]["properties"] = {
            "specifications": [{"datasheet": {"DATA": {"x": 1}}}]}
        m1, m2 = _mocked(api)
        with m1, m2, mock.patch("explore.views._is_architect", return_value=True):
            html = self.client.get(NEW_PAGE).content.decode()
            self.client.post(NEW_PAGE, {"institution_id": "128", "define_type_data": "1"})
        self.assertIn("Defines <code>DATA</code>", html)
        self.assertNotIn('name="define_type_data"', html)
        self.assertEqual(api.create_component.call_args.args[1]["specifications"],
                         {"DATA": {"x": 1}})
        api.patch_component_type.assert_not_called()

    def test_create_without_an_institution_is_refused(self):
        api = self._api_create()
        m1, m2 = _mocked(api)
        with m1, m2:
            self.client.post(NEW_PAGE, {"serial_number": "SN-9"})
        api.create_component.assert_not_called()
