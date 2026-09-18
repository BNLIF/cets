"""#166: bulk edit of items from the Type View — the pasted list resolves
against the mirror, the preview writes nothing, Apply PATCHes HWDB's
``bulk-update`` in chunks and the mirror rows follow. HWDB is mocked.

    python manage.py test explore.tests.test_items_edit
"""

from __future__ import annotations

import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from explore import itemsedit
from explore.models import ActivityEvent, HwdbComponentEvent

T = "D00400300001"
URL = f"/hw/dev/items-edit/{T}/"


def _rows():
    for n, sn in ((1, "HPK-1"), (2, "HPK-2"), (3, "SMB-3"), (4, "DUP"), (5, "DUP")):
        HwdbComponentEvent.objects.create(
            instance="dev", part_type_id=T, part_id=f"{T}-{n:05d}", serial_number=sn,
            status="Unknown", status_id=0, qaqc_uploaded=False,
            created_by="Maritza" if n < 4 else "Chao")
    HwdbComponentEvent.objects.create(instance="dev", part_type_id="D00400300002",
                                      part_id="D00400300002-00001", serial_number="OTHER")


LIVE = {1: ("first", "HPK-1"), 2: ("second", "HPK-2"), 3: ("", ""), 4: ("d", "DUP"), 5: ("d", "DUP")}


def _listing(*rows):
    """One page of HWDB's component listing; rows default to the mirror's values."""
    return {"pagination": {"pages": 1}, "data": list(rows) or [
        {"part_id": f"{T}-{n:05d}", "comments": c, "serial_number": sn,
         "status": {"id": 0, "name": "Unknown"}, "qaqc_uploaded": False,
         "certified_qaqc": None, "is_installed": None, "parent_part_id": None}
        for n, (c, sn) in LIVE.items()]}


def _api():
    api = mock.MagicMock()
    api.get_component_type.return_value = {"data": {"manufacturers": [{"id": 7, "name": "HPK"}]}}
    api.bulk_update_components.return_value = {"status": "OK"}
    api._make_request.return_value = _listing()
    return api


def _row(n, **kw):
    return HwdbComponentEvent.objects.get(part_id=f"{T}-{n:05d}", **kw)


def _mocked(api):
    return (mock.patch("explore.views.mint_for", return_value="bearer"),
            mock.patch("explore.views.FnalDbApiClient", return_value=api))


class ResolveTest(TestCase):
    def setUp(self):
        _rows()

    def pids(self, text):
        return [r.part_id for r in itemsedit.resolve("dev", T, text)["rows"]]

    def test_pid_suffix_range_and_serial(self):
        self.assertEqual(self.pids(f"{T}-00001"), [f"{T}-00001"])
        self.assertEqual(self.pids("2"), [f"{T}-00002"])
        self.assertEqual(self.pids("00002..00003"), [f"{T}-00002", f"{T}-00003"])
        self.assertEqual(self.pids("..00002"), [f"{T}-00001", f"{T}-00002"])
        self.assertEqual(self.pids("hpk-1"), [f"{T}-00001"])

    def test_separators_dedupe_and_order(self):
        self.assertEqual(self.pids(f"3, HPK-1\n{T}-00003 00002"),
                         [f"{T}-00001", f"{T}-00002", f"{T}-00003"])

    def test_unmatched_and_wrong_type(self):
        r = itemsedit.resolve("dev", T, "00099 nope D00400300002-00001 OTHER 00050..00060")
        self.assertEqual(r["rows"], [])
        self.assertEqual(r["unmatched"], ["00099", "nope", "D00400300002-00001", "OTHER", "00050..00060"])

    def test_match_rules_alone_select_every_matching_item(self):
        HwdbComponentEvent.objects.filter(part_id=f"{T}-00003").update(status="In Fabrication", manufacturer="SMB")
        self.assertEqual([r.part_id for r in itemsedit.resolve("dev", T, "", status="Unknown")["rows"]],
                         [f"{T}-0000{n}" for n in (1, 2, 4, 5)])
        self.assertEqual([r.part_id for r in itemsedit.resolve("dev", T, "", sn="^hpk")["rows"]],
                         [f"{T}-00001", f"{T}-00002"])
        self.assertEqual([r.part_id for r in itemsedit.resolve("dev", T, "", sn="^(?!HPK)")["rows"]],
                         [f"{T}-0000{n}" for n in (3, 4, 5)])
        self.assertEqual([r.part_id for r in itemsedit.resolve("dev", T, "", manufacturer="SMB")["rows"]],
                         [f"{T}-00003"])
        self.assertEqual([r.part_id for r in itemsedit.resolve("dev", T, "", created_by="Chao")["rows"]],
                         [f"{T}-00004", f"{T}-00005"])
        self.assertEqual([r.part_id for r in itemsedit.resolve("dev", T, "", sn="(-3")["rows"]],   # bad regex → substring
                         [])
        self.assertEqual([r.part_id for r in itemsedit.resolve("dev", T, "", sn="K-1")["rows"]], [f"{T}-00001"])

    def test_match_rules_narrow_a_pasted_list(self):
        r = itemsedit.resolve("dev", T, "1 2 3", sn="^HPK")
        self.assertEqual([x.part_id for x in r["rows"]], [f"{T}-00001", f"{T}-00002"])
        self.assertEqual(r["unmatched"], ["3"])
        self.assertEqual(itemsedit.resolve("dev", T, "", )["rows"], [])   # nothing asked = nothing

    def test_facets(self):
        HwdbComponentEvent.objects.filter(part_id=f"{T}-00003").update(status="")
        self.assertEqual(itemsedit.facet("dev", T, "status"), [("Unknown", 4), ("", 1)])
        self.assertEqual(itemsedit.facet("dev", T, "created_by"), [("Maritza", 3), ("Chao", 2)])

    def test_shared_serial_is_skipped_with_its_pids(self):
        r = itemsedit.resolve("dev", T, "DUP HPK-2")
        self.assertEqual([x.part_id for x in r["rows"]], [f"{T}-00002"])
        self.assertEqual(r["shared"], [("DUP", [f"{T}-00004", f"{T}-00005"])])


class ChangesTest(TestCase):
    def test_nothing_chosen(self):
        patch, mirror, shown = itemsedit.changes({"status": "", "qaqc_uploaded": "", "comments": "x"}, [])
        self.assertEqual((patch, mirror, shown), ({}, {}, []))

    def test_fields(self):
        patch, mirror, shown = itemsedit.changes(
            {"status": "110", "qaqc_uploaded": "1", "certified_qaqc": "0", "manufacturer": "7",
             "comments_set": "on", "comments": " bulk "}, [{"value": 7, "label": "HPK"}])
        self.assertEqual(patch, {"status": {"id": 110}, "qaqc_uploaded": True, "certified_qaqc": False,
                                 "manufacturer": {"id": 7}, "comments": "bulk"})
        self.assertEqual(mirror, {"status": "Waiting on QA/QC Tests", "status_id": 110,
                                  "qaqc_uploaded": True, "certified_qaqc": False, "manufacturer": "HPK"})
        self.assertEqual(shown[0], "Component status → Waiting on QA/QC Tests")
        self.assertIn("Item comments → “bulk”", shown)

    def test_unknown_status_or_manufacturer_ignored(self):
        patch, _, _ = itemsedit.changes({"status": "999", "manufacturer": "8"}, [{"value": 7, "label": "HPK"}])
        self.assertEqual(patch, {})


class RowsTest(TestCase):
    def setUp(self):
        _rows()
        HwdbComponentEvent.objects.filter(part_id=f"{T}-00001").update(manufacturer="HPK")

    def test_rows_echo_comments_and_manufacturer(self):
        mirror = list(HwdbComponentEvent.objects.filter(part_type_id=T))
        rows = itemsedit.rows_for([(f"{T}-00001", "keep me", "HPK-1"), (f"{T}-00002", "", "")],
                                  {"status": {"id": 110}}, mirror, [{"value": 7, "label": "HPK"}])
        self.assertEqual(rows, [
            {"part_id": f"{T}-00001", "status": {"id": 110}, "serial_number": "HPK-1",
             "comments": "keep me", "manufacturer": {"id": 7}},
            {"part_id": f"{T}-00002", "status": {"id": 110}, "serial_number": "",
             "comments": "Patched by the Explorer", "manufacturer": None}])

    def test_chosen_comments_and_manufacturer_win(self):
        rows = itemsedit.rows_for([(f"{T}-00001", "old", "S")], {"comments": "new", "manufacturer": {"id": 9}},
                                  [], [])
        self.assertEqual(rows, [{"part_id": f"{T}-00001", "comments": "new", "manufacturer": {"id": 9},
                                 "serial_number": "S"}])

    def test_live_rows_fetches_the_pages_after_the_first_in_parallel(self):
        api = _api()
        api._make_request.side_effect = lambda m, ep, params=None: {
            "pagination": {"pages": 3},
            "data": [{"part_id": f"{T}-{n:05d}", "comments": f"c{n}"}
                     for n in range((params["page"] - 1) * 20 + 1, params["page"] * 20 + 1)]}
        live = itemsedit.live_rows(api, T)
        self.assertEqual(len(live), 60)
        self.assertEqual(live[f"{T}-00045"]["comments"], "c45")
        self.assertEqual(api._make_request.call_count, 3)
        self.assertEqual(sorted(c.kwargs["params"]["page"] for c in api._make_request.call_args_list), [1, 2, 3])

    def test_refresh_mirror_restamps_status_flags_serial_parent(self):
        live = {f"{T}-00001": {"part_id": f"{T}-00001", "status": {"id": 110, "name": "Waiting on QA/QC Tests"},
                               "qaqc_uploaded": True, "certified_qaqc": False, "is_installed": None,
                               "serial_number": "HPK-1b", "parent_part_id": "D00400300009-00001",
                               "creator": {"id": 3, "name": "Karla"}},
                f"{T}-00002": {"part_id": f"{T}-00002", "status": None, "serial_number": "HPK-2"}}
        self.assertEqual(itemsedit.refresh_mirror("dev", T, live), 1)
        r = _row(1)
        self.assertEqual((r.status, r.status_id, r.qaqc_uploaded, r.certified_qaqc, r.is_installed,
                          r.serial_number, r.parent_part_id, r.created_by),
                         ("Waiting on QA/QC Tests", 110, True, False, None, "HPK-1b", "D00400300009-00001", "Karla"))
        self.assertEqual(_row(2).created_by, "Maritza")   # no creator in the row → kept
        self.assertEqual((_row(2).status, _row(2).status_id), ("Unknown", 0))   # blank status never wipes
        self.assertEqual(itemsedit.refresh_mirror("dev", T, live), 0)


class ViewTest(TestCase):
    def setUp(self):
        _rows()
        self.client.force_login(get_user_model().objects.create_user("w", "w@w.io", "pw"))

    def test_form_renders_with_type_manufacturers(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(URL).content.decode()
        self.assertIn('<textarea id="items" name="items"></textarea>', html)   # not dict_items([])
        self.assertNotIn("dict_items", html)
        self.assertIn("Waiting on QA/QC Tests", html)
        self.assertIn('<option value="7"', html)
        self.assertIn('<option value="Unknown">Unknown (5)</option>', html)
        self.assertIn('<option value="Maritza">Maritza (3)</option>', html)
        self.assertIn('name="f_sn"', html)
        api._make_request.assert_called_once()   # the page load sweeps the listing too

    def test_page_load_refreshes_blank_mirror_statuses(self):
        HwdbComponentEvent.objects.filter(part_type_id=T).update(status="", status_id=None)   # pre-status mirror rows
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(URL).content.decode()
        self.assertIn('<option value="Unknown">Unknown (5)</option>', html)
        self.assertEqual(_row(3).status_id, 0)

    def test_page_load_survives_a_failed_sweep(self):
        import requests
        api = _api()
        api._make_request.side_effect = requests.exceptions.HTTPError("503 down")
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(URL).content.decode()
        self.assertIn("Couldn’t read the items from HWDB", html)
        self.assertIn('name="items"', html)

    @override_settings(HWDB_WRITE_INSTANCES=["dev"])
    def test_read_only_instance_is_forbidden(self):
        m1, m2 = _mocked(_api())
        with m1, m2:
            self.assertEqual(self.client.get(f"/hw/items-edit/{T}/").status_code, 403)

    def test_preview_resolves_and_writes_nothing(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.post(URL, {"step": "preview", "items": "1 2 DUP zzz",
                                          "status": "110"}).content.decode()
        self.assertIn("Component status → Waiting on QA/QC Tests", html)
        self.assertIn(f">{T}-00001<", html)
        self.assertIn("Not in the mirror: <span class=\"ie-mono\">zzz</span>", html)
        self.assertIn("is on 2 items", html)
        self.assertIn(json.dumps([[f"{T}-00001", "first", "HPK-1"], [f"{T}-00002", "second", "HPK-2"]]), html)
        self.assertIn('Apply to <span id="ie-n">2</span> items', html)
        self.assertEqual(html.count('class="ie-pick"'), 2)
        api.bulk_update_components.assert_not_called()

    def test_preview_names_items_hwdb_no_longer_has(self):
        api = _api()
        HwdbComponentEvent.objects.create(instance="dev", part_type_id=T, part_id=f"{T}-00009", serial_number="gone")
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.post(URL, {"step": "preview", "items": "9 2", "status": "110"}).content.decode()
        self.assertIn(f"no longer in HWDB (re-sync the type): <span class=\"ie-mono\">{T}-00009</span>", html)
        self.assertIn('Apply to <span id="ie-n">1</span> item<', html)

    def test_big_previews_show_the_first_rows_without_checkboxes(self):
        HwdbComponentEvent.objects.bulk_create([
            HwdbComponentEvent(instance="dev", part_type_id=T, part_id=f"{T}-{n:05d}", serial_number=f"B{n}",
                               status="Unknown") for n in range(100, 100 + itemsedit.PICK_MAX)])
        api = _api()
        api._make_request.return_value = {"pagination": {"pages": 1}, "data": [
            {"part_id": r.part_id, "comments": "", "serial_number": r.serial_number}
            for r in HwdbComponentEvent.objects.filter(part_type_id=T)]}
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.post(URL, {"step": "preview", "f_status": "Unknown", "status": "110"}).content.decode()
        n = itemsedit.PICK_MAX + 5
        self.assertIn(f'Apply to <span id="ie-n">{n}</span> items', html)
        self.assertNotIn('class="ie-pick"', html)
        self.assertEqual(html.count('class="ie-mono"><a href='), itemsedit.SHOW_MAX)
        self.assertIn(f"First {itemsedit.SHOW_MAX} of {n} shown; Apply covers all of them.", html)
        self.assertEqual(len(json.loads(html.split('id="ie-rows">')[1].split("</script>")[0])), n)

    def test_preview_sweeps_even_when_comments_are_set(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.post(URL, {"step": "preview", "items": "1", "comments_set": "on",
                                          "comments": "note"}).content.decode()
        api._make_request.assert_called_once()   # the serial must still be echoed
        self.assertIn(json.dumps([[f"{T}-00001", "first", "HPK-1"]]), html)

    def test_preview_by_rule_only(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.post(URL, {"step": "preview", "items": "", "f_sn": "^HPK",
                                          "status": "110"}).content.decode()
        self.assertIn('Apply to <span id="ie-n">2</span> items', html)
        self.assertIn("Match: serial ^HPK</li>", html)

    def test_preview_refreshes_the_mirror_before_matching(self):
        api = _api()
        rows = _listing()["data"]
        rows[0]["status"] = {"id": 110, "name": "Waiting on QA/QC Tests"}   # 00001 re-statused in HWDB
        api._make_request.return_value = {"pagination": {"pages": 1}, "data": rows}
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.post(URL, {"step": "preview", "f_status": "Unknown", "status": "110"}).content.decode()
        self.assertEqual((_row(1).status, _row(1).status_id), ("Waiting on QA/QC Tests", 110))
        self.assertNotIn(f">{T}-00001<", html)          # no longer Unknown → not matched
        self.assertIn('Apply to <span id="ie-n">4</span> items', html)
        self.assertIn("4</b> items — now Unknown 4", html)

    def test_preview_needs_items_or_a_rule(self):
        m1, m2 = _mocked(_api())
        with m1, m2:
            html = self.client.post(URL, {"step": "preview", "items": " ", "status": "110"}).content.decode()
        self.assertIn("Paste items or pick a match rule.", html)
        self.assertNotIn("Apply to", html)

    def test_preview_needs_a_field(self):
        m1, m2 = _mocked(_api())
        with m1, m2:
            html = self.client.post(URL, {"step": "preview", "items": "1"}).content.decode()
        self.assertIn("Pick at least one field to change.", html)
        self.assertNotIn("Apply to", html)

    def _apply(self, api, rows, first="1", total=None, **fields):
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post(URL, {"step": "apply", "rows": json.dumps(rows), "first": first,
                                          "total": total or len(rows), **fields})
        return resp.status_code, resp.json()

    def test_apply_slice_patches_echoing_comments_and_updates_the_mirror(self):
        api = _api()
        HwdbComponentEvent.objects.filter(part_id=f"{T}-00001").update(manufacturer="HPK")
        code, j = self._apply(api, [[f"{T}-00001", "first", "HPK-1"], [f"{T}-00003", "", ""],
                                    ["D00400300002-00001", "x", "y"]],
                              total=3, status="110", qaqc_uploaded="1")
        self.assertEqual((code, j), (200, {"done": 2}))
        api.bulk_update_components.assert_called_once_with(T, {"data": [
            {"part_id": f"{T}-00001", "status": {"id": 110}, "qaqc_uploaded": True, "serial_number": "HPK-1",
             "comments": "first", "manufacturer": {"id": 7}},
            {"part_id": f"{T}-00003", "status": {"id": 110}, "qaqc_uploaded": True, "serial_number": "",
             "comments": "Patched by the Explorer", "manufacturer": None}]})
        self.assertEqual((_row(1).status, _row(1).status_id, _row(1).qaqc_uploaded),
                         ("Waiting on QA/QC Tests", 110, True))
        self.assertEqual(_row(2).status, "Unknown")
        ev = ActivityEvent.objects.get(kind=ActivityEvent.KIND_ITEM)
        self.assertEqual(ev.part_type_id, T)
        self.assertIn(f"3 {T} items: Component status → Waiting on QA/QC Tests; QA/QC uploaded → yes", ev.summary)

    def test_later_slices_do_not_log_again(self):
        code, j = self._apply(_api(), [[f"{T}-00002", "second", "HPK-2"]], first="0", certified_qaqc="0")
        self.assertEqual((code, j), (200, {"done": 1}))
        self.assertFalse(ActivityEvent.objects.filter(kind=ActivityEvent.KIND_ITEM).exists())
        self.assertIs(_row(2).certified_qaqc, False)

    def test_apply_reports_a_rejected_slice_and_leaves_the_mirror(self):
        import requests
        api = _api()
        api.bulk_update_components.side_effect = requests.exceptions.HTTPError("500 boom")
        code, j = self._apply(api, [[f"{T}-00002", "second", "HPK-2"]], certified_qaqc="0")
        self.assertEqual((code, j), (200, {"done": 0, "error": "500 boom"}))
        self.assertIsNone(_row(2).certified_qaqc)

    def test_apply_without_a_field_is_a_400(self):
        code, j = self._apply(_api(), [[f"{T}-00002", "second", "HPK-2"]])
        self.assertEqual(code, 400)
