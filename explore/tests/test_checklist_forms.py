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
    return api


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
        self.assertIn('type="file" name="f2-2"', html)        # photo
        self.assertIn("Unwrap", html)                         # steps
        self.assertIn("https://edms.cern.ch/x", html)         # static link
        self.assertNotIn("Bogus", html)                       # unknown dropped
        self.assertIn("Submit to HWDB", html)

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
        api.get_component_type.return_value = {"data": {"connectors": {
            "FEB1": "D05700300001", "CBL1": "D08100100003"}}}
        api.get_subcomponents.return_value = {"data": [
            {"functional_position": "CBL1", "part_id": None}]}
        api.patch_component.return_value = {"status": "OK"}
        api.patch_subcomponents.return_value = {"status": "OK"}
        return api

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
                         {"Vendor": "Acme", "X dimension": 3366.0})
        self.assertEqual(checklistforms.link_requests(s, data), [
            {"label": "FEB board", "pid": "D05700300001-00012",
             "position": "FEB1"}])

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
        self.assertEqual(spec["DATA"], {"Kept": "yes", "Vendor": "Acme"})
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
