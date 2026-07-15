"""Tests for the executive-summary signing flow (issue #64), matching the
Python Dashboard: config from the type's images, signatures in the "ES"
test record (HWDB is the only state), rank-ordered role-gated signing,
reportlab PDF generation, gate-convention upload. HWDB is mocked.

    python manage.py test explore
"""

from __future__ import annotations

import base64
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


# ---- image_path plots -------------------------------------------------------

CFG_PLOTS = {**CFG, "plots": [
    {"title": "Noise RMS", "test_type_name": "RoomT QC",
     "image_path": {"image_name": "noise.png", "history_order": 0}},
    {"title": "FEB plot", "test_type_name": "RoomT QC",
     "sub_part_id": {"layer": 1, "pos_name": "FEB1"},
     "image_path": {"image_name": "feb.png"}},
    {"title": "Gain hist", "test_type_name": "RoomT QC",
     "data_paths": ["DATA/gain"]},                       # numeric → unsupported
]}

# a real 1x1 PNG so reportlab can embed it
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
    "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def _plots_api(**kw):
    """_api() with the plots config and per-test-type dispatch: the "ES"
    record keeps its shape; QC test history carries the referenced images."""
    api = _api(cfg=CFG_PLOTS, **kw)
    es_resp = api.get_tests.return_value
    cfg_resp = api.get_image_response.return_value

    def get_tests(pid, test_type_id=None, history=False):
        if test_type_id == "ES":
            return es_resp
        return {"data": [{"images": [
            {"image_name": "noise.png", "image_id": "img-noise"},
            {"image_name": "feb.png", "image_id": "img-feb"}]}]}

    def get_image_response(image_id):
        return cfg_resp if image_id == "cfg1" else mock.Mock(content=PNG)

    api.get_tests.side_effect = get_tests
    api.get_image_response.side_effect = get_image_response
    return api


class ImagePlotEngineTest(TestCase):
    def test_normalize_keeps_every_slot_with_kind_and_slug(self):
        cfg = execsummary._normalize(CFG_PLOTS)
        self.assertEqual([p["kind"] for p in cfg["plots"]],
                         ["image", "image", "numeric"])
        self.assertEqual(cfg["plots"][0]["history_order"], 0)
        self.assertEqual(cfg["plots"][1]["image_name"], "feb.png")
        self.assertEqual(cfg["plots"][1]["sub_part_id"],
                         {"layer": 1, "pos_name": "FEB1"})
        self.assertEqual(cfg["plots"][2]["slug"], "p02-Gain-hist")
        self.assertEqual(cfg["plots"][2]["data_paths"], ["DATA/gain"])

    def test_resolve_finds_image_ids_and_sub_part_pid(self):
        api = _plots_api()
        cfg = execsummary._normalize(CFG_PLOTS)
        children = lambda pid: [{"part_id": "D05700300001-00012",
                                 "functional_position": "FEB1"}]
        blocks = execsummary.resolve_plots(api, cfg, BOX, children, [])
        self.assertEqual(blocks[0]["pid"], BOX)                       # the item itself
        self.assertEqual(blocks[0]["image_id"], "img-noise")
        self.assertIsNone(blocks[0]["error"])
        self.assertEqual(blocks[1]["pid"], "D05700300001-00012")      # via sub_part_id
        self.assertEqual(blocks[1]["image_id"], "img-feb")
        # the numeric slot has no source and no error — the page offers upload
        self.assertIsNone(blocks[2]["image_id"])
        self.assertIsNone(blocks[2]["error"])

    def test_resolve_reports_missing_history_and_missing_image(self):
        api = _plots_api()
        api.get_tests.side_effect = lambda pid, test_type_id=None, history=False: \
            {"data": []}
        cfg = execsummary._normalize(CFG_PLOTS)
        blocks = execsummary.resolve_plots(api, cfg, BOX, lambda pid: [], [])
        self.assertIn("No test history found", blocks[0]["error"])
        # image name absent from the record
        api = _plots_api()
        api.get_tests.side_effect = lambda pid, test_type_id=None, history=False: \
            {"data": [{"images": [{"image_name": "other.png", "image_id": "x"}]}]}
        blocks = execsummary.resolve_plots(api, cfg, BOX, lambda pid: [], [])
        self.assertIn("Could not find image_name='noise.png'", blocks[0]["error"])

    def test_newest_upload_wins_a_slot(self):
        api = _plots_api()
        cfg = execsummary._normalize(CFG_PLOTS)
        item_images = [
            {"image_id": "up-old", "created": "2026-06-01T00:00:00",
             "image_name": f"ESPlot_{BOX}_p02-Gain-hist_20260601_000000.png"},
            {"image_id": "up-new", "created": "2026-07-01T00:00:00",
             "image_name": f"ESPlot_{BOX}_p02-Gain-hist_20260701_000000.png"},
            {"image_id": "up-noise", "created": "2026-07-01T00:00:00",
             "image_name": f"ESPlot_{BOX}_p00-Noise-RMS_20260701_000000.png"},
        ]
        blocks = execsummary.resolve_plots(api, cfg, BOX, lambda pid: [], item_images)
        self.assertEqual(blocks[2]["image_id"], "up-new")     # numeric slot filled
        self.assertTrue(blocks[2]["uploaded"])
        self.assertEqual(blocks[0]["image_id"], "up-noise")   # supersedes test record
        self.assertTrue(blocks[0]["uploaded"])
        self.assertEqual(blocks[1]["image_id"], "img-feb")    # no upload → config source

    def test_download_skips_pdfs_and_fills_bytes(self):
        api = _plots_api()
        blocks = [
            {"image_id": "img-noise", "image_name": "noise.png", "is_pdf": False},
            {"image_id": "att-1", "image_name": "report.pdf", "is_pdf": True},
            {"image_id": None, "image_name": "gone.png", "is_pdf": False},
        ]
        execsummary.download_plot_images(api, blocks)
        self.assertEqual(blocks[0]["bytes"], PNG)
        self.assertNotIn("bytes", blocks[1])
        self.assertIn("not embedded", blocks[1]["error"])
        self.assertNotIn("bytes", blocks[2])


class ImagePlotPageTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("s", "s@s.io", "pw")
        self.client.force_login(self.user)

    def test_page_shows_plots_via_image_proxy(self):
        api = _plots_api()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(PAGE).content.decode()
        self.assertIn("Noise RMS", html)
        self.assertIn("shipment-image/img-noise/", html)   # img via bearer proxy
        self.assertIn("shipment-image/img-feb/", html)
        self.assertIn("D05700300001-00012", html)          # sub_part_id resolved pid
        self.assertIn("Numeric plot (data_paths:", html)   # unfilled numeric slot
        self.assertIn("Upload plot image", html)           # ...offers the upload
        self.assertEqual(html.count('name="plot_image"'), 3)  # one form per slot
        self.assertLess(html.index("Plots (3 configured)"), html.index("Sign-off"))

    def test_upload_plot_posts_under_the_constructed_name(self):
        api = _plots_api()
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post(PAGE, {
                "action": "upload_plot", "plot_index": "2",
                "plot_image": SimpleUploadedFile("gain.png", PNG,
                                                 content_type="image/png")},
                follow=True)
        (pid, fileobj, name), kwargs = api.post_component_image.call_args
        self.assertEqual(pid, BOX)
        self.assertRegex(name, rf"^ESPlot_{BOX}_p02-Gain-hist_\d{{8}}_\d{{6}}\.png$")
        self.assertEqual(kwargs["comments"], "ES plot upload: Gain hist")
        self.assertIn("Plot image posted", resp.content.decode())

    def test_upload_plot_rejects_bad_slot_and_non_image(self):
        api = _plots_api()
        m1, m2 = _mocked(api)
        with m1, m2:
            self.client.post(PAGE, {   # not a configured slot
                "action": "upload_plot", "plot_index": "9",
                "plot_image": SimpleUploadedFile("x.png", PNG)})
            self.client.post(PAGE, {   # not an image
                "action": "upload_plot", "plot_index": "2",
                "plot_image": SimpleUploadedFile("x.pdf", b"%PDF-1.4")})
        api.post_component_image.assert_not_called()

    def test_generate_embeds_plot_images_in_the_pdf(self):
        api = _plots_api(es=[_entry("Chao Zhang", 2), _entry("Hajime Muramatsu", 1)])
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post(PAGE, {"action": "generate"}, follow=True)
        self.assertIn("Summary generated and posted", resp.content.decode())
        # plot bytes were fetched for embedding, and the PDF was uploaded
        fetched = [c.args[0] for c in api.get_image_response.call_args_list]
        self.assertIn("img-noise", fetched)
        self.assertIn("img-feb", fetched)
        pdf = api.post_component_image.call_args.args[1].read()
        self.assertTrue(pdf.startswith(b"%PDF"))


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
        self.assertIn("https://example.org/spec", html)    # reference URLs card
        self.assertIn("the spec", html)                    # reference comment
        self.assertIn("es-req", html)                      # red/green confirmations

    def test_summaries_selection_defaults_to_latest(self):
        api = _api()
        api.get_images.return_value = {"data": [
            {"image_id": "s-old", "created": "2026-01-01T00:00:00",
             "image_name": f"ExecutiveSummary_{BOX}_20260101_000000.pdf"},
            {"image_id": "s-new", "created": "2026-07-01T00:00:00",
             "image_name": f"ExecutiveSummary_{BOX}_20260701_000000.pdf"},
            {"image_id": "x", "image_name": "photo.jpg"},   # not a summary
        ]}
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(PAGE).content.decode()
        # one selection list with every summary, newest first = default choice
        self.assertIn("Summary PDFs (2)", html)
        self.assertIn('<option value="/hw/dev/shipment-image/s-new/', html)
        self.assertIn('<option value="/hw/dev/shipment-image/s-old/', html)
        self.assertLess(html.index("s-new"), html.index("s-old"))
        self.assertIn("— latest", html)
        # combined header card, Dashboard-style
        self.assertIn("Consortium:", html)
        self.assertIn("CE (test)", html)
        self.assertIn("Description:", html)
        self.assertIn("Test config", html)

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


CHIP = "Z00100300001-07630"           # not a curated shipping type
CHIP_PAGE = f"/hw/dev/part/{CHIP}/exec-summary/"


class NonShippingTypeTest(TestCase):
    """Any type can carry an executive summary, not just shipping boxes.
    Until the hierarchy-chart "requires ES" marking exists, the mark is an
    ES_{ptid}_*.json config on the type in HWDB."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("s", "s@s.io", "pw")
        self.client.force_login(self.user)

    def test_config_marked_type_gets_the_signing_page(self):
        api = _api()
        api.get_component_type_images.return_value = {"data": [
            {"image_id": "cfgZ", "image_name": "ES_Z00100300001_test_v8.json",
             "created": "2026-07-01T00:00:00"}]}
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(CHIP_PAGE).content.decode()
        self.assertIn("ES_Z00100300001_test_v8.json", html)  # config displayed
        self.assertIn("Hajime Muramatsu", html)              # signees from it

    def test_unmarked_type_is_forbidden(self):
        api = _api(cfg=None)   # no ES_*.json on the type
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.get(CHIP_PAGE)
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
                "com:Chao Zhang": "looks good", "todo": ["0", "1"],
                "status_id": "120", "certified": "on", "uploaded": "on"},
                follow=True)
        payload = api.post_test.call_args.args[1]
        self.assertEqual(payload["test_type"], "ES")
        entry = payload["test_data"]["ES"][0]
        self.assertEqual(entry["name"], "Chao Zhang")
        self.assertEqual(entry["signature"], "Chao Zhang")
        self.assertEqual(entry["rank"], 2)
        self.assertEqual(entry["comments"], "looks good")
        self.assertEqual(payload["test_data"]["todos"]["checked"], [0, 1])
        patch = api.patch_component.call_args.args[1]
        self.assertEqual(patch["status"], {"id": 120})
        self.assertTrue(patch["certified_qaqc"])
        self.assertTrue(patch["qaqc_uploaded"])
        self.assertIn("Signature for “Chao Zhang” posted", resp.content.decode())

    def test_sign_requires_all_checks_and_both_flags(self):
        # One QC check unticked and the uploaded flag missing → refused, and
        # the message names both; nothing reaches HWDB.
        api = _api(es=[])
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post(PAGE, {
                "sign": "Chao Zhang", "sig:Chao Zhang": "Chao Zhang",
                "todo": ["0"], "status_id": "120", "certified": "on"},
                follow=True)
        api.post_test.assert_not_called()
        api.patch_component.assert_not_called()
        html = resp.content.decode()
        self.assertIn("still unchecked", html)
        self.assertIn("1 QC check(s)", html)
        self.assertIn("All QA/QC Uploaded", html)

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
                "certified": "on", "uploaded": "on"}, follow=True)
        api.post_test.assert_not_called()               # DEFAULT posts no ES record
        patch = api.patch_component.call_args.args[1]
        self.assertEqual(patch["status"], {"id": 140})
        (pid, fileobj, name), kwargs = api.post_component_image.call_args
        self.assertTrue(fileobj.read().startswith(b"%PDF"))
        self.assertIn("Signed and posted", resp.content.decode())

    def test_default_sign_requires_both_flags(self):
        api = _api(cfg=None)
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post(PAGE, {
                "action": "default_sign", "status_id": "140",
                "uploaded": "on"}, follow=True)
        api.patch_component.assert_not_called()
        api.post_component_image.assert_not_called()
        self.assertIn("Certified QA/QC", resp.content.decode())

    def test_expired_link_redirects(self):
        with mock.patch("explore.views.mint_for", side_effect=FnalLinkRequired()):
            resp = self.client.get(PAGE)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("link", resp["Location"])


CFG_PAGE = "/hw/dev/es-config/D00599800007/"


class ConfigEditorTest(TestCase):
    """The structured ES-config editor: prefilled from the newest config (or
    the template), saves a new ES_{ptid}_{ts}.json onto the type."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("s", "s@s.io", "pw")
        self.client.force_login(self.user)

    def test_editor_prefills_the_existing_config(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(CFG_PAGE + "?next=/hw/dev/part/X/exec-summary/").content.decode()
        self.assertIn("CE (test)", html)                   # initial JSON embedded
        self.assertIn("Contents match", html)
        self.assertIn("ES_D00599800007_test.json", html)   # current file named
        self.assertIn("Edit the ES config", html)

    def test_editor_offers_template_when_type_has_none(self):
        api = _api(cfg=None)
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(CFG_PAGE).content.decode()
        self.assertIn("Create the ES config", html)
        self.assertIn("QC Checks", html)                   # template embedded
        self.assertIn("starting from the template", html)
        self.assertIn('"component_type_id": "D00599800007"', html)  # pre-set

    def test_save_posts_a_new_config_onto_the_type(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post(CFG_PAGE, {
                "config_json": json.dumps({"consortium_name": "CRP Consortium",
                                           "todos": {"title": "QC", "check_list": ["a"]}}),
                "next": ""}, follow=True)
        (ptid, fileobj, name), kwargs = api.post_component_type_image.call_args
        self.assertEqual(ptid, "D00599800007")
        self.assertRegex(name, r"^ES_D00599800007_\d{8}_\d{6}\.json$")
        saved = json.loads(fileobj.read())
        self.assertEqual(saved["consortium_name"], "CRP Consortium")
        # required field, auto-filled from the type when absent
        self.assertEqual(saved["component_type_id"], "D00599800007")
        self.assertIn("Explorer editor", kwargs["comments"])
        self.assertIn("Config posted", resp.content.decode())

    def test_invalid_json_is_refused(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post(CFG_PAGE, {"config_json": "{not json"}, follow=True)
        api.post_component_type_image.assert_not_called()
        self.assertIn("isn’t valid JSON", resp.content.decode())

    def test_save_redirects_back_to_next(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post(CFG_PAGE, {
                "config_json": "{}", "next": "/hw/dev/part/X/exec-summary/"})
        self.assertEqual(resp["Location"], "/hw/dev/part/X/exec-summary/")

    def test_prod_is_forbidden(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.get("/hw/es-config/D00599800007/")
        self.assertEqual(resp.status_code, 403)
