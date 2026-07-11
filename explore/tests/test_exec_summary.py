"""Tests for the executive-summary signing flow (issue #64), matching the
Python Dashboard: config from the type's images, signatures in the "ES"
test record (HWDB is the only state), rank-ordered role-gated signing,
reportlab PDF generation, gate-convention upload. HWDB is mocked.

    python manage.py test explore
"""

from __future__ import annotations

import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from explore import execsummary
from hwdb.fnal.bearer import FnalLinkRequired

BOX = "D00599800007-00128"
PAGE = f"/hw/dev/part/{BOX}/exec-summary/"

CFG = {
    "consortium_name": "CE (test)",
    "test_description": "Test config",
    "todos": {"title": "QC Checks", "check_list": ["Contents match", "Box sealed"]},
    "signees": [
        {"name": "Chao Zhang", "rank": 2, "roles": []},
        {"name": "Hajime Muramatsu", "rank": 1, "roles": [41]},
    ],
    "references": [{"url": "https://example.org/spec", "comments": "the spec"}],
    "plots": [],
}


def _api(cfg=CFG, es=None, todos=None, roles=(41,)):
    api = mock.MagicMock()
    api.get_component_type_images.return_value = {"data": [
        {"image_id": "cfg1", "image_name": f"ES_D00599800007_test.json",
         "created": "2026-07-01T00:00:00"}]} if cfg else {"data": []}
    cfg_resp = mock.Mock()
    cfg_resp.content = json.dumps(cfg or {}).encode()
    api.get_image_response.return_value = cfg_resp
    td = {"ES": es or []}
    if todos is not None:
        td["todos"] = todos
    api.get_tests.return_value = {"data": [{"test_data": td}] if es is not None else []}
    api.whoami.return_value = {"data": {
        "full_name": "Chao Zhang", "roles": [{"id": r, "name": f"role{r}"} for r in roles]}}
    api.get_roles.return_value = {"data": [{"id": 41, "name": "CE approver"}]}
    api.get_component.return_value = {"data": {
        "status": {"id": 120, "name": "QA/QC Tests - Passed All"},
        "certified_qaqc": True, "qaqc_uploaded": False}}
    api.get_images.return_value = {"data": []}
    api.get_subcomponents.return_value = {"data": [
        {"part_id": "D05700300001-00012", "type_name": "FEB",
         "functional_position": "FEB1", "operation": "mount"}]}
    api.post_test.return_value = {"status": "OK"}
    api.patch_component.return_value = {"status": "OK"}
    api.post_component_image.return_value = {"status": "OK", "image_id": "img-9"}
    api.post_component_type_image.return_value = {"status": "OK", "image_id": "cfg2"}
    return api


def _mocked(api):
    return (mock.patch("explore.views.mint_for", return_value="bearer"),
            mock.patch("explore.views.FnalDbApiClient", return_value=api))


def _entry(name, rank, sig="signed"):
    return {"name": name, "signature": sig, "rank": rank,
            "timestamp": "2026-07-11 09:00", "comments": ""}


class EngineTest(TestCase):
    def test_merge_upserts_by_name(self):
        merged = execsummary.merge_es_entry(
            [_entry("A", 1)], "A", "new sig", 1, "2026-07-11 10:00", "hi")
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["signature"], "new sig")
        merged = execsummary.merge_es_entry(merged, "B", "s", 2, "t", "")
        self.assertEqual([e["name"] for e in merged], ["A", "B"])

    def test_rank_order_highest_nonnegative_first(self):
        cfg = execsummary._normalize(CFG)
        st = execsummary.compute_status(cfg, [], {41})
        allowed = {r["name"]: r["allowed"] for r in st["rows"]}
        self.assertTrue(allowed["Chao Zhang"])       # rank 2 signs first
        self.assertFalse(allowed["Hajime Muramatsu"])  # rank 1 waits
        st2 = execsummary.compute_status(cfg, [_entry("Chao Zhang", 2)], {41})
        self.assertTrue({r["name"]: r["allowed"] for r in st2["rows"]}["Hajime Muramatsu"])
        self.assertFalse(st2["all_signed"])
        st3 = execsummary.compute_status(
            cfg, [_entry("Chao Zhang", 2), _entry("Hajime Muramatsu", 1)], {41})
        self.assertTrue(st3["all_signed"])

    def test_negative_ranks_sign_first_and_roles_gate(self):
        cfg = execsummary._normalize({**CFG, "signees": [
            {"name": "N", "rank": -1, "roles": []},
            {"name": "P", "rank": 5, "roles": [99]},
        ]})
        st = execsummary.compute_status(cfg, [], set())
        allowed = {r["name"]: r for r in st["rows"]}
        self.assertTrue(allowed["N"]["allowed"])
        self.assertFalse(allowed["P"]["allowed"])   # negative unsigned blocks P
        st2 = execsummary.compute_status(cfg, [_entry("N", -1)], set())
        self.assertFalse({r["name"]: r for r in st2["rows"]}["P"]["allowed"])  # role 99 missing
        st3 = execsummary.compute_status(cfg, [_entry("N", -1)], {99})
        self.assertTrue({r["name"]: r for r in st3["rows"]}["P"]["allowed"])

    def test_reset_needs_lowest_nonnegative_rank_roles(self):
        cfg = execsummary._normalize(CFG)   # lowest non-negative = Hajime (roles [41])
        self.assertTrue(execsummary.compute_status(cfg, [], {41})["reset_allowed"])
        self.assertFalse(execsummary.compute_status(cfg, [], {7})["reset_allowed"])

    def test_todos_payload_clamps_indices(self):
        cfg = execsummary._normalize(CFG)
        self.assertEqual(execsummary.todos_payload(cfg, [1, 1, 9, -2]),
                         {"title": "QC Checks",
                          "check_list": ["Contents match", "Box sealed"],
                          "checked": [1]})

    def test_pdf_builders_emit_pdf_bytes(self):
        cfg = execsummary._normalize(CFG)
        rows = execsummary.compute_status(
            cfg, [_entry("Chao Zhang", 2), _entry("Hajime Muramatsu", 1)], {41})["rows"]
        detail = execsummary.build_detail_pdf(BOX, {
            "type_name": "Test Type 007", "description": cfg["test_description"],
            "todos": {**cfg["todos"], "checked": [0]}, "signee_rows": rows,
            "status_label": "QA/QC Tests - Passed All",
            "certified_flag": True, "uploaded_flag": False,
            "references": cfg["references"], "subcomponents": ["a (b) @ c"]})
        default = execsummary.build_default_pdf(BOX, {
            "signature": "Chao", "comments": "", "timestamp": "now",
            "status_label": "Unknown", "certified_flag": False,
            "uploaded_flag": False}, [])
        self.assertTrue(detail.startswith(b"%PDF"))
        self.assertTrue(default.startswith(b"%PDF"))


class PageTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("s", "s@s.io", "pw")
        self.client.force_login(self.user)

    def test_detail_page_shows_signees_and_state(self):
        api = _api(es=[_entry("Chao Zhang", 2)])
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(PAGE).content.decode()
        self.assertIn("Chao Zhang", html)
        self.assertIn("Hajime Muramatsu", html)
        self.assertIn("signed 2026-07-11 09:00", html)     # Chao already signed
        self.assertIn("can sign now", html)                # Hajime's turn (role 41 held)
        self.assertIn("Contents match", html)              # todos rendered
        self.assertIn("ES_D00599800007_test.json", html)   # config named

    def test_default_mode_without_config(self):
        api = _api(cfg=None)
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(PAGE).content.decode()
        self.assertIn("Default sign-off", html)
        self.assertIn("Chao Zhang", html)                  # whoami prefill

    def test_prod_is_forbidden(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.get("/hw/part/D08120200001-00001/exec-summary/")
        self.assertEqual(resp.status_code, 403)


class SignTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("s", "s@s.io", "pw")
        self.client.force_login(self.user)

    def test_sign_posts_consolidated_es_and_patches_item(self):
        api = _api(es=[])
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post(PAGE, {
                "sign": "Chao Zhang", "sig:Chao Zhang": "Chao Zhang",
                "com:Chao Zhang": "looks good", "todo": ["0"],
                "status_id": "120", "certified": "on"}, follow=True)
        payload = api.post_test.call_args.args[1]
        self.assertEqual(payload["test_type"], "ES")
        entry = payload["test_data"]["ES"][0]
        self.assertEqual(entry["name"], "Chao Zhang")
        self.assertEqual(entry["signature"], "Chao Zhang")
        self.assertEqual(entry["rank"], 2)
        self.assertEqual(entry["comments"], "looks good")
        self.assertEqual(payload["test_data"]["todos"]["checked"], [0])
        patch = api.patch_component.call_args.args[1]
        self.assertEqual(patch["status"], {"id": 120})
        self.assertTrue(patch["certified_qaqc"])
        self.assertFalse(patch["qaqc_uploaded"])
        self.assertIn("Signature for “Chao Zhang” posted", resp.content.decode())

    def test_out_of_turn_sign_is_refused(self):
        api = _api(es=[])   # nobody signed → rank 1 must wait for rank 2
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post(PAGE, {
                "sign": "Hajime Muramatsu", "sig:Hajime Muramatsu": "H"}, follow=True)
        api.post_test.assert_not_called()
        self.assertIn("can’t sign now", resp.content.decode())

    def test_missing_role_is_refused(self):
        api = _api(es=[_entry("Chao Zhang", 2)], roles=(7,))  # not role 41
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post(PAGE, {
                "sign": "Hajime Muramatsu", "sig:Hajime Muramatsu": "H"}, follow=True)
        api.post_test.assert_not_called()
        self.assertIn("required role", resp.content.decode())


class GenerateResetUploadTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("s", "s@s.io", "pw")
        self.client.force_login(self.user)

    def test_generate_requires_all_signed(self):
        api = _api(es=[_entry("Chao Zhang", 2)])
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post(PAGE, {"action": "generate"}, follow=True)
        api.post_component_image.assert_not_called()
        self.assertIn("must sign before generating", resp.content.decode())

    def test_generate_builds_and_uploads_gate_named_pdf(self):
        api = _api(es=[_entry("Chao Zhang", 2), _entry("Hajime Muramatsu", 1)])
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post(PAGE, {"action": "generate"}, follow=True)
        (pid, fileobj, name), kwargs = api.post_component_image.call_args
        self.assertEqual(pid, BOX)
        self.assertRegex(name, rf"^ExecutiveSummary_{BOX}_\d{{8}}_\d{{6}}\.pdf$")
        self.assertTrue(fileobj.read().startswith(b"%PDF"))
        self.assertIn("uploaded by HWDB Explorer", kwargs["comments"])
        self.assertIn("Summary generated and posted", resp.content.decode())

    def test_reset_clears_signatures_preserving_todos(self):
        todos = {"title": "QC Checks", "check_list": ["a"], "checked": [0]}
        api = _api(es=[_entry("Chao Zhang", 2)], todos=todos)
        m1, m2 = _mocked(api)
        with m1, m2:
            self.client.post(PAGE, {"action": "reset"})
        payload = api.post_test.call_args.args[1]
        self.assertEqual(payload["test_data"]["ES"], [])
        self.assertEqual(payload["test_data"]["todos"], todos)

    def test_reset_without_final_approver_role_is_refused(self):
        api = _api(es=[_entry("Chao Zhang", 2)], roles=(7,))
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post(PAGE, {"action": "reset"}, follow=True)
        api.post_test.assert_not_called()
        self.assertIn("final approver", resp.content.decode())

    def test_manual_upload_still_works(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            self.client.post(PAGE, {
                "action": "upload",
                "pdf": SimpleUploadedFile("s.pdf", b"%PDF-1.4",
                                          content_type="application/pdf")})
        (pid, fileobj, name), kwargs = api.post_component_image.call_args
        self.assertRegex(name, rf"^ExecutiveSummary_{BOX}_\d{{8}}_\d{{6}}\.pdf$")

    def test_default_sign_patches_and_posts_pdf_without_es(self):
        api = _api(cfg=None)
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post(PAGE, {
                "action": "default_sign", "status_id": "140",
                "uploaded": "on"}, follow=True)
        api.post_test.assert_not_called()               # DEFAULT posts no ES record
        patch = api.patch_component.call_args.args[1]
        self.assertEqual(patch["status"], {"id": 140})
        (pid, fileobj, name), kwargs = api.post_component_image.call_args
        self.assertTrue(fileobj.read().startswith(b"%PDF"))
        self.assertIn("Signed and posted", resp.content.decode())

    def test_config_upload_lands_on_the_type(self):
        api = _api(cfg=None)
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post(PAGE, {
                "action": "upload_config",
                "config": SimpleUploadedFile("es.json", json.dumps(CFG).encode(),
                                             content_type="application/json")},
                follow=True)
        (ptid, fileobj, name), kwargs = api.post_component_type_image.call_args
        self.assertEqual(ptid, "D00599800007")
        self.assertRegex(name, r"^ES_D00599800007_\d{8}_\d{6}\.json$")
        self.assertIn("Config posted", resp.content.decode())

    def test_invalid_config_json_is_refused(self):
        api = _api(cfg=None)
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post(PAGE, {
                "action": "upload_config",
                "config": SimpleUploadedFile("es.json", b"{not json")}, follow=True)
        api.post_component_type_image.assert_not_called()
        self.assertIn("isn’t valid JSON", resp.content.decode())

    def test_expired_link_redirects(self):
        with mock.patch("explore.views.mint_for", side_effect=FnalLinkRequired()):
            resp = self.client.get(PAGE)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("link", resp["Location"])
