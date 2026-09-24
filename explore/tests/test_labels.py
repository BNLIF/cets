"""#175: QR / bar-code label sheets — the utility's ``hwdb-labels`` in the
Explorer. The engine (labels.py) is exercised on its own; the view with
HWDB mocked.

    python manage.py test explore.tests.test_labels
"""

from __future__ import annotations

import io
import json
from unittest import mock

import fitz
import openpyxl
from django.contrib.auth import get_user_model
from django.test import TestCase

from explore import labels
from explore.models import HwdbComponentEvent
from hwdb.fnal.bearer import FnalLinkRequired

T = "D00400300001"
URL = f"/hw/dev/labels/{T}/"
UI = "https://dbweb2.fnal.gov:8443/cdbdev"


def _rec(n=12, **kw):
    d = {"part_id": f"{T}-{n:05d}", "country_code": "US", "institution": {"id": 186, "name": "BNL"},
         "component_type": {"part_type_id": T, "name": "SiPM Board"}, "serial_number": f"HPK-{n}",
         "manufacturer": {"id": 7, "name": "HPK"},
         "specifications": [{"Vbd": 51.4, "Notes": None, "Channels": [1, 2]}]}
    d.update(kw)
    return d


def _pages(pdf: bytes):
    doc = fitz.open(stream=pdf, filetype="pdf")
    try:
        return [(round(p.rect.width), round(p.rect.height)) for p in doc]
    finally:
        doc.close()


class EngineTest(TestCase):
    def test_item_data_adds_the_utilitys_convenience_fields(self):
        d = labels.item_data(_rec())
        self.assertEqual(d["external_id"], f"{T}-00012-US186")
        self.assertEqual((d["part_type_id"], d["part_name"]), (T, "SiPM Board"))
        self.assertEqual(d["specifications"], {"Vbd": 51.4, "Notes": None, "Channels": [1, 2]})
        bare = labels.item_data({"part_id": "X"})
        self.assertEqual((bare["external_id"], bare["part_name"]), ("X-", ""))

    def test_resolve_text_paths_and_blanks(self):
        d = labels.item_data(_rec())
        self.assertEqual(labels.resolve_text("${serial_number} · ${manufacturer.name} · ${specifications.Vbd}", d),
                         "HPK-12 · HPK · 51.4")
        self.assertEqual(labels.resolve_text("${specifications.Channels.1}/${nope.x}/${specifications.Notes}", d),
                         "2//")
        self.assertEqual(labels.resolve_text("plain", d), "plain")

    def test_field_paths_list_scalars_only(self):
        paths = labels.field_paths(labels.item_data(_rec()))
        self.assertIn("serial_number", paths)
        self.assertIn("manufacturer.name", paths)
        self.assertIn("specifications.Vbd", paths)
        self.assertIn("specifications.Channels.0", paths)
        self.assertNotIn("specifications", paths)
        self.assertNotIn("manufacturer", paths)

    def test_sheets_follow_the_template_geometry(self):
        items = [labels.item_data(_rec(n)) for n in range(1, 14)]   # 13 on a 12-per-sheet A4
        pdf = labels.build_pdf([labels.LAYOUTS["QR-A4-3x4-Generic"]], items, UI)
        self.assertEqual(_pages(pdf), [(595, 842)] * 4)   # intro, template, 2 label pages
        pdf = labels.build_pdf([labels.LAYOUTS["QR-A4-3x4-Generic"]], items, UI, intro=False)
        self.assertEqual(len(_pages(pdf)), 2)
        # a label set spanning two sheet types = one run per template, each with its intro pages
        pdf = labels.build_pdf([labels.LAYOUTS["QR-A4-3x4-Generic"], labels.LAYOUTS["Bar-Letter-2x7-Avery"]],
                               items[:2], UI)
        self.assertEqual(_pages(pdf), [(595, 842)] * 3 + [(612, 792)] * 3)
        # a layout naming an unknown template is skipped rather than crashing
        self.assertEqual(_pages(labels.build_pdf([{"label template": "nope"}], items, UI)), [])

    def test_labels_carry_the_codes_and_text(self):
        lay = {"label template": "Letter-2x4-Avery", "orientation": "portrait", "elements": [
            {"element type": "qr", "anchor": ["4%", "4%"], "size": ["40%", "80%"], "preserve aspect ratio": True},
            {"element type": "bar", "anchor": ["50%", "4%"], "size": ["45%", "30%"], "alignment": "top-left"},
            {"element type": "external id", "anchor": ["72%", "40%"], "alignment": "top-center", "font size": "8%"},
            {"element type": "text", "text": "SN ${serial_number}", "anchor": ["72%", "55%"],
             "alignment": "top-center", "font size": "8%", "font face": "Courier", "rotate": 0},
            {"element type": "text", "text": "x", "font face": "NoSuchFont"},   # falls back, no crash
            {"element type": "bogus"}]}
        pdf = labels.build_pdf([lay], [labels.item_data(_rec())], UI, intro=False)
        doc = fitz.open(stream=pdf, filetype="pdf")
        text = doc[0].get_text()
        doc.close()
        self.assertIn(f"{T}-00012-US186", text)
        self.assertIn("SN HPK-12", text)

    def test_presets_fit_their_text_elements(self):
        for name, lay in labels.LAYOUTS.items():
            for el in lay["elements"]:
                if el["element type"] in ("part id", "external id", "part name"):
                    self.assertTrue(el.get("fit width"), f"{name}: {el['element type']}")

    def test_fit_width_shrinks_long_text(self):
        long = labels.item_data(_rec(component_type={"part_type_id": T, "name": "A very long component type name indeed"}))
        el = {"element type": "part name", "anchor": ["50%", "50%"], "alignment": "top-center",
              "font size": "20%", "size": ["100%", "100%"]}
        lay = {"label template": "A4-6x11-Herma", "elements": [el]}
        wide = fitz.open(stream=labels.build_pdf([lay], [long], UI, intro=False), filetype="pdf")
        lay["elements"] = [dict(el, **{"fit width": True})]
        fit = fitz.open(stream=labels.build_pdf([lay], [long], UI, intro=False), filetype="pdf")
        label_w = 25.4 * 72 / 25.4   # the Herma label is 25.4 mm = 72 pt wide
        w_wide = wide[0].get_text("dict")["blocks"][0]["lines"][0]["bbox"][2] - wide[0].get_text("dict")["blocks"][0]["lines"][0]["bbox"][0]
        w_fit = fit[0].get_text("dict")["blocks"][0]["lines"][0]["bbox"][2] - fit[0].get_text("dict")["blocks"][0]["lines"][0]["bbox"][0]
        self.assertGreater(w_wide, label_w)
        self.assertLessEqual(w_fit, 0.9 * label_w + 1)   # a 5% cutting margin each side, even at 100% width
        self.assertGreater(w_fit, 0.8 * label_w)          # shrunk to fit, not further

    def test_preview_is_a_png_of_one_label(self):
        png = labels.preview_png(labels.LAYOUTS["QR-Letter-2x4-Avery"], labels.item_data(_rec()), UI, dpi=72)
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        w, h = fitz.open(stream=png, filetype="png")[0].rect.br
        self.assertEqual((round(w), round(h)), (288, 180))   # 4" × 2.5" at 72 dpi

    def test_upload_entries_picks_the_id_column(self):
        self.assertEqual(labels.upload_entries("a.csv", b"Name,Part ID\r\nx,D00400300001-00001\r\ny,HPK-2\r\n"),
                         f"{T}-00001\nHPK-2")
        self.assertEqual(labels.upload_entries("a.csv", b"D00400300001-00001;x\nD00400300001-00002;y\n"),
                         f"{T}-00001\n{T}-00002")
        self.assertEqual(labels.upload_entries("a.txt", b"\xef\xbb\xbfHPK-1\n\nHPK-2\n"), "HPK-1\nHPK-2")
        self.assertEqual(labels.upload_entries("a.csv", b""), "")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["board", "serial"])
        ws.append([1, "HPK-1"])
        ws.append([2, 7])
        buf = io.BytesIO()
        wb.save(buf)
        self.assertEqual(labels.upload_entries("list.xlsx", buf.getvalue()), "HPK-1\n7")


class RetryTest(TestCase):
    def test_get_item_retries_transient_drops(self):
        import requests
        api = mock.MagicMock()
        api.get_component.side_effect = [requests.ConnectionError("SSLEOFError"), {"data": _rec(1)}]
        with mock.patch("explore.labels.time.sleep"):
            self.assertEqual(labels.get_item(api, f"{T}-00001")["serial_number"], "HPK-1")
        self.assertEqual(api.get_component.call_count, 2)
        api.get_component.side_effect = requests.ConnectionError("down")
        with mock.patch("explore.labels.time.sleep"), self.assertRaises(requests.ConnectionError):
            labels.fetch_items([f"{T}-00001"], lambda: api)
        self.assertEqual(api.get_component.call_count, 5)   # 2 + 3 attempts


def _api():
    api = mock.MagicMock()
    api.get_component.side_effect = lambda pid: {"data": _rec(int(pid[-5:]))}
    return api


def _mocked(api):
    return (mock.patch("explore.views.mint_for", return_value="bearer"),
            mock.patch("explore.views.FnalDbApiClient", return_value=api))


class ViewTest(TestCase):
    def setUp(self):
        for n in (1, 2, 3):
            HwdbComponentEvent.objects.create(instance="dev", part_type_id=T, part_id=f"{T}-{n:05d}",
                                              serial_number=f"HPK-{n}", status="Unknown", status_id=0)
        self.client.force_login(get_user_model().objects.create_user("w", "w@w.io", "pw"))

    def test_page_renders_with_presets(self):
        with _mocked(_api())[0], _mocked(_api())[1], \
                mock.patch("explore.views.navigation.leaf_path_for", return_value="/hw/dev/x/y/"):
            r = self.client.get(URL)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'href="/hw/dev/x/y/"')
        self.assertContains(r, "QR-A4-3x4-Generic")
        self.assertContains(r, "Letter-2x7-Avery")
        self.assertContains(r, 'id="lb-form"')

    def test_unlinked_user_goes_to_the_link_page(self):
        with mock.patch("explore.views.mint_for", side_effect=FnalLinkRequired("x")):
            r = self.client.get(URL)
            self.assertEqual(r.status_code, 302)
            self.assertIn("/link", r["Location"])
            r = self.client.post(URL, {"step": "preview"})
            self.assertEqual(r.status_code, 401)

    def test_preview_renders_the_first_item_and_lists_fields(self):
        api = _api()
        p1, p2 = _mocked(api)
        with p1, p2:
            r = self.client.post(URL, {"step": "preview", "items": "HPK-2, 3 9",
                                       "layouts": json.dumps([labels.LAYOUTS["QR-Letter-2x4-Avery"]])})
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertEqual((j["n"], j["first"], j["unmatched"], j["over"]), (2, f"{T}-00002", ["9"], 0))
        self.assertIn("specifications.Vbd", j["fields"])
        self.assertTrue(j["png"])
        api.get_component.assert_called_once_with(f"{T}-00002")

    def test_preview_without_items_uses_a_sample(self):
        api = _api()
        p1, p2 = _mocked(api)
        with p1, p2:
            r = self.client.post(URL, {"step": "preview", "items": "",
                                       "layouts": json.dumps([labels.LAYOUTS["QR-A4-3x4-Generic"]])})
        self.assertEqual((r.json()["n"], r.json()["first"]), (0, ""))
        self.assertEqual(r.json()["fields"], labels.STANDARD_FIELDS)   # the picker is never empty
        api.get_component.assert_not_called()

    def test_bad_layout_is_refused(self):
        p1, p2 = _mocked(_api())
        with p1, p2:
            r = self.client.post(URL, {"step": "preview", "items": "1", "layouts": "[{}]"})
            self.assertEqual(r.status_code, 400)
            r = self.client.post(URL, {"step": "pdf", "items": "1", "layouts": "nope"})
            self.assertEqual(r.status_code, 400)

    def test_pdf_downloads_every_matched_item(self):
        api = _api()
        p1, p2 = _mocked(api)
        with p1, p2:
            r = self.client.post(URL, {"step": "pdf", "items": "1 2 3",
                                       "layouts": json.dumps([labels.LAYOUTS["QR-A4-6x11-Herma_10107"]])})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertIn(f'labels_{T}.pdf', r["Content-Disposition"])
        self.assertEqual(len(_pages(r.content)), 1)
        self.assertEqual(api.get_component.call_count, 3)
        with p1, p2:
            r = self.client.post(URL, {"step": "pdf", "items": "1", "intro": "1",
                                       "layouts": json.dumps([labels.LAYOUTS["QR-A4-6x11-Herma_10107"]])})
            self.assertEqual(len(_pages(r.content)), 3)   # intro + alignment template + labels
            r = self.client.post(URL, {"step": "pdf", "items": "9",
                                       "layouts": json.dumps([labels.LAYOUTS["QR-A4-6x11-Herma_10107"]])})
        self.assertEqual((r.status_code, r.json()["error"]), (400, "No items matched the list."))

    def test_rows_step_lists_the_mirror_newest_first(self):
        p1, p2 = _mocked(_api())
        with p1, p2:
            r = self.client.post(URL, {"step": "rows"})
        self.assertEqual([x[0] for x in r.json()["rows"]], [f"{T}-00003", f"{T}-00002", f"{T}-00001"])
        self.assertEqual(r.json()["rows"][0][1:], ["HPK-3", "Unknown", "", ""])

    def test_file_step_returns_the_list_as_text(self):
        p1, p2 = _mocked(_api())
        with p1, p2:
            f = io.BytesIO(b"pid\nHPK-1\nHPK-2\n")
            f.name = "list.csv"
            r = self.client.post(URL, {"step": "file", "file": f})
            self.assertEqual(r.json(), {"text": "HPK-1\nHPK-2"})
            r = self.client.post(URL, {"step": "file"})
            self.assertEqual(r.status_code, 400)
