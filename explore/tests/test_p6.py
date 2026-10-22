"""#206 (Anselmo 2026-10-20): the P6 schedule — the monthly activities
spreadsheet parsed into a project-wide table, a plan naming two activity
ids whose dates the status table shows, one plan per consortium for a
type two consortia list. HWDB mocked — no network.

    python manage.py test explore.tests.test_p6
"""

import io
import json
from datetime import date, datetime
from unittest import mock

import openpyxl
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from explore import navigation, p6, production
from explore.models import ActivityEvent, ConsortiumTypeOverride, P6Activity, P6Upload, ProductionList, ProductionPlan
from explore.tests.test_events import _node
from explore.tests.test_production import LIST, PDS, PLAN, PTID, SIPM, _api, _mocked

HEADER = ["Detector", "Component", "Prod Activity Type", "Prod Activity Name", "Prod Activity ID",
          "Install Activity Type", "Install Activity Name", "Install Activity ID", "Production End Date",
          "Prod Date Source", "Installation Start Date", "Install Date Source", "Float (days)", "Notes"]
ROWS = [
    ["HD", "HD-PDS", "End of Production", "Deliver to Storage (300 modules) (1500 total) #1 - CSU", "13122.A12812",
     "Start of Installation", "Install modules in Detector Slice 21-22 - CSU", "13122.A12834",
     datetime(2029, 3, 8, 17, 0), "Forecast", datetime(2030, 1, 30, 8, 0), "Forecast", None, None],
    ["HD", "HD-PDS", "End of Production", "Assemble and test 32 DAPHNE modules #1 (32 total) NIU", "13122.A12742",
     "Start of Installation", "Install/Checkout Warm Electronics Detector 1 - Colombia", "13122.A28866",
     datetime(2027, 7, 26, 17, 0), "Forecast", None, "Not found in P6", None, "no install date"],
    # a second batch of the same production id: the first row's date stays
    ["HD", "HD-PDS", "End of Production", "Deliver to Storage (300 modules) (1500 total) #1 - CSU", "13122.A12812",
     "Start of Installation", "Install PD monitoring - SDSMT", "13122.A12840",
     datetime(2029, 3, 8, 17, 0), "Forecast", datetime(2029, 5, 29, 8, 0), "Forecast", None, None],
]
VD_ROWS = [["VD", "Frontend MotherBoard", "End of Production", "Test production quantity of FEMBs, last25%", "13124.3.4.25",
            "Start of Installation", "Install FEMBs - CRU (CRP 61-70)", "13124.A368642",
            datetime(2027, 8, 25, 17, 0), "Forecast", datetime(2028, 3, 28, 8, 0), "Forecast", "=K2-I2", None]]


def _xlsx(sheets=None) -> bytes:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for title, rows in (sheets or {"HD-PDS": ROWS, "TPC-Elec_BDE-VD": VD_ROWS,
                                   "DAQ": [["Tier", "Milestone Activity ID", "Milestone Name"], ["T6", "13122.A453245", "x"]]}).items():
        ws = wb.create_sheet(title)
        if title != "DAQ":
            ws.append(HEADER)
        for r in rows:
            ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class ParseTest(TestCase):
    def test_one_activity_per_id_and_kind_the_daq_sheet_skipped(self):
        rows = p6.parse("Float_Chart_Activities_Combined.xlsx", _xlsx())
        self.assertEqual([(r["activity_id"], r["kind"]) for r in rows],
                         [("13122.A12812", "prod"), ("13122.A12834", "install"), ("13122.A12742", "prod"),
                          ("13122.A28866", "install"), ("13122.A12840", "install"), ("13124.3.4.25", "prod"), ("13124.A368642", "install")])
        self.assertEqual(rows[0], {"activity_id": "13122.A12812", "kind": "prod", "name": "Deliver to Storage (300 modules) (1500 total) #1 - CSU",
                                   "date": date(2029, 3, 8), "source": "Forecast", "detector": "HD", "sheet": "HD-PDS",
                                   "component": "HD-PDS", "notes": ""})
        self.assertEqual((rows[3]["date"], rows[3]["source"], rows[3]["notes"]), (None, "Not found in P6", "no install date"))
        self.assertEqual(rows[5]["detector"], "VD")

    def test_problems_name_the_sheet_and_row(self):
        bad = [list(r) for r in ROWS[:1]]
        bad[0][8] = "next spring"
        with self.assertRaisesMessage(p6.P6Error, "HD-PDS row 2: 'next spring' is not a date"):
            p6.parse("x.xlsx", _xlsx({"HD-PDS": bad}))
        with self.assertRaisesMessage(p6.P6Error, "No sheet with a “Prod Activity ID” column"):
            p6.parse("x.xlsx", _xlsx({"DAQ": [["Tier"]]}))
        with self.assertRaisesMessage(p6.P6Error, "is an .xlsx file"):
            p6.parse("x.csv", b"a,b")
        with self.assertRaisesMessage(p6.P6Error, "Not a readable .xlsx file"):
            p6.parse("x.xlsx", b"nope")

    def test_replace_keeps_one_upload(self):
        p6.replace(p6.parse("a.xlsx", _xlsx()), "chaoz", "a.xlsx")
        up = p6.replace(p6.parse("b.xlsx", _xlsx({"HD-PDS": ROWS[:1]})), "anselmo", "b.xlsx")
        self.assertEqual((P6Upload.objects.count(), p6.current().filename, up.n_rows, up.uploaded_by), (1, "b.xlsx", 2, "anselmo"))
        self.assertEqual(P6Activity.objects.count(), 2)
        self.assertEqual(p6.lookup({"13122.A12812", "zzz"})[("13122.A12812", "prod")].date, date(2029, 3, 8))
        self.assertEqual(p6.options()[0]["id"], "13122.A12812")


class ApplyTest(TestCase):
    def setUp(self):
        p6.replace(p6.parse("a.xlsx", _xlsx()), "chaoz", "a.xlsx")

    def test_dates_come_from_p6_the_typed_months_otherwise(self):
        plans = production.apply_p6({
            PDS: {**production.normalize_plan(PLAN), "p6_completed_id": "13122.A12812", "p6_needed_id": "13122.A12834"},
            SIPM: production.normalize_plan(PLAN),
            "X": {**production.normalize_plan(PLAN), "p6_completed_id": "gone", "p6_needed_id": "13122.A28866"},
        })
        self.assertEqual((plans[PDS]["completed_by"], plans[PDS]["needed_by"], plans[PDS]["p6_missing"]), ("2029-03-08", "2030-01-30", []))
        self.assertEqual(plans[PDS]["completed_src"], "P6 13122.A12812: Deliver to Storage (300 modules) (1500 total) #1 - CSU (Forecast)")
        self.assertEqual((plans[SIPM]["completed_by"], plans[SIPM]["completed_src"]), ("2026-12", ""))
        self.assertEqual((plans["X"]["completed_by"], plans["X"]["needed_by"]), ("2026-12", "2028-05"))   # the typed months stay
        self.assertEqual(plans["X"]["p6_missing"], ["gone is not in the latest P6 schedule", "13122.A28866 has no date in P6 (Not found in P6)"])
        # the table: day precision, the source in the cell, the float still in whole months
        rows = production.table([{"type": PDS}, {"type": "X"}], plans, {}, {}, date(2026, 10, 20))
        self.assertEqual((rows[0]["completed_by"], rows[0]["needed_by"], rows[0]["float"], rows[0]["completed_past"]), ("8 Mar 2029", "30 Jan 2030", "10", False))
        self.assertEqual(rows[1]["p6_missing"], "gone is not in the latest P6 schedule; 13122.A28866 has no date in P6 (Not found in P6)")
        self.assertEqual(production.month_label("2029-03-08"), "8 Mar 2029")
        self.assertEqual(production.summary([{"type": PDS}], plans, date(2026, 10, 20))["needed_by"], "2030-01-30")

    def test_type_plan_and_per_consortium_caches(self):
        production.cache_plan("dev", PDS, {**production.normalize_plan(PLAN), "p6_completed_id": "13122.A12812"})
        production.cache_plan("dev", PDS, {**production.normalize_plan(PLAN), "needed": 7}, consortium=PTID)
        self.assertEqual(ProductionPlan.objects.count(), 2)
        self.assertEqual(production.cached_plans("dev", [PDS])[PDS]["needed"], 48000)
        self.assertEqual(production.cached_plans("dev", [PDS], PTID)[PDS]["needed"], 7)   # the consortium's own plan wins
        self.assertEqual(production.cached_plans("dev", [PDS], "Z99")[PDS]["needed"], 48000)
        tp = production.type_plan("dev", PDS)
        self.assertEqual((tp["needed"], tp["completed_by"]), (48000, "2029-03-08"))   # the type page: the plain plan, P6 applied
        production.cache_plan("dev", PDS, None)
        self.assertEqual(production.type_plan("dev", PDS)["needed"], 7)
        production.cache_list("dev", PTID, production.normalize_list(LIST))
        production.cache_list("dev", "Z00100600002", [{"type": PDS, "label": ""}])
        self.assertEqual(production.shared_by("dev", PDS), [PTID, "Z00100600002"])
        self.assertEqual(production.shared_by("dev", SIPM), [PTID])
        self.assertEqual(production.plan_name(PDS, PTID), f"Production_plan_{PDS}_{PTID}.json")
        # Chao 2026-10-22: the type page lists every tracker's plan — its own, else the plain one, else none
        _node(PTID, instance="dev", component_type_name="HD PDS", full_name="x")
        _node("Z00100600002", instance="dev", component_type_name="VD PDS", full_name="y")
        rows = production.type_plans("dev", PDS)
        self.assertEqual([(r["consortium"], r["name"], r["plan"] and r["plan"]["needed"]) for r in rows],
                         [(PTID, "HD PDS", 7), ("Z00100600002", "VD PDS", None)])
        production.cache_plan("dev", PDS, {**production.normalize_plan(PLAN), "p6_completed_id": "13122.A12812"})
        rows = production.type_plans("dev", PDS)
        self.assertEqual([(r["consortium"], r["plan"]["needed"], r["plan"]["completed_by"]) for r in rows],
                         [(PTID, 7, "2026-12"), ("Z00100600002", 48000, "2029-03-08")])   # VD falls back to the plain plan
        self.assertEqual([r["consortium"] for r in production.type_plans("dev", SIPM)], [""])   # one list: the single row

    def test_type_page_lists_a_plan_per_tracker(self):
        self.client.force_login(get_user_model().objects.create_user("t", "t@t.io", "pw"))
        production.cache_list("prod", PTID, production.normalize_list(LIST))
        production.cache_list("prod", "Z00100600002", [{"type": PDS, "label": ""}])
        _node(PTID, instance="prod", component_type_name="HD PDS", full_name="x")
        _node("Z00100600002", instance="prod", component_type_name="VD PDS", full_name="y")
        leaf = _node(PDS, instance="prod", component_type_name="PDS modules", full_name="z")
        production.cache_plan("prod", PDS, production.normalize_plan(PLAN))
        production.cache_plan("prod", PDS, {**production.normalize_plan(PLAN), "needed": 7}, consortium=PTID)
        url = navigation.leaf_path_for("prod", PDS)
        html = self.client.get(url).content.decode()
        self.assertIn(f'<dt>Plan</dt><dd class="span"><a href="/hw/status/{PTID}/" title="This status tracker’s table">HD PDS</a><span class="sep">·</span>needed 7<span class="sep">·</span>completed by 2026-12', html)
        self.assertIn('<dt>Plan</dt><dd class="span"><a href="/hw/status/Z00100600002/" title="This status tracker’s table">VD PDS</a><span class="sep">·</span>needed 48000<span class="sep">·</span>completed by 2026-12', html)
        self.assertIn(f'<a href="/hw/plan/{PDS}/?for={PTID}&amp;next=', html)
        self.assertIn(f'<a href="/hw/plan/{PDS}/?for=Z00100600002&amp;next=', html)
        self.assertEqual(html.count("<dt>Plan</dt>"), 2)
        production.cache_plan("prod", PDS, None)
        html = self.client.get(url).content.decode()
        self.assertIn('>VD PDS</a><span class="sep">·</span><a href="/hw/plan/' + PDS + '/?for=Z00100600002&amp;next=', html)   # no plan of its own, none plain: Set plan
        self.assertIn(">Set plan</a></dd>", html)


class UploadTest(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("u", "u@u.io", "pw"))

    def test_schedule_page_and_upload(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get("/hw/dev/schedule/").content.decode()
        self.assertIn('<a class="hc-tab" aria-selected="true" href="/hw/dev/schedule/">P6 schedule</a>', html)
        self.assertIn("None uploaded yet — plans show their typed dates.", html)
        self.assertIn('<form method="post" action="/hw/dev/schedule/upload/" enctype="multipart/form-data">', html)   # the architect's form
        self.assertNotIn('<table class="p6-table">', html)
        with m1, m2:
            r = self.client.post("/hw/dev/schedule/upload/", {"file": SimpleUploadedFile("Float_Chart_Activities_Combined.xlsx", _xlsx())})
            self.assertEqual(r["Location"], "/hw/dev/schedule/")
            html = self.client.get("/hw/dev/schedule/").content.decode()
        self.assertIn("P6 schedule read — 7 activities from Float_Chart_Activities_Combined.xlsx.", html)
        self.assertIn("<b>Float_Chart_Activities_Combined.xlsx</b> · 7 activities · uploaded ", html)
        self.assertEqual(ActivityEvent.objects.get(kind="curation").summary, "P6 schedule uploaded: Float_Chart_Activities_Combined.xlsx, 7 activities")
        # the table: one group row per sheet, the activities in the spreadsheet's order with their kind, date and source
        self.assertIn('<tr class="p6-sheet" data-sheet="HD-PDS"><td colspan="7">HD-PDS<span class="mono">HD</span></td></tr>', html)
        self.assertIn('<tr class="p6-sheet" data-sheet="TPC-Elec_BDE-VD"><td colspan="7">TPC-Elec_BDE-VD<span class="mono">VD</span></td></tr>', html)
        self.assertIn('<tr data-det="HD" data-sheet="HD-PDS" data-kind="prod">\n      <td>HD-PDS</td>\n      <td class="mono">13122.A12812</td>\n'
                      '      <td class="p6-dim">production end</td>\n      <td>Deliver to Storage (300 modules) (1500 total) #1 - CSU</td>\n'
                      '      <td class="p6-date">2029-03-08</td>\n      <td class="p6-dim">Forecast</td>', html)
        self.assertIn('<td class="p6-dim">installation start</td>\n      <td>Install/Checkout Warm Electronics Detector 1 - Colombia</td>\n'
                      '      <td class="p6-date">—</td>\n      <td class="p6-dim">Not found in P6</td>\n      <td class="p6-dim">no install date</td>', html)
        self.assertEqual(html.count('<tr data-det='), 7)
        self.assertIn('<option value="HD-PDS">HD-PDS</option><option value="TPC-Elec_BDE-VD">TPC-Elec_BDE-VD</option>', html)
        with m1, m2:
            r = self.client.post("/hw/dev/schedule/upload/", {"file": SimpleUploadedFile("x.xlsx", b"nope")}, follow=True)
        self.assertIn("P6 schedule not read — Not a readable .xlsx file", r.content.decode())
        self.assertEqual(P6Activity.objects.count(), 7)   # the last good upload stays
        with m1, m2:
            r = self.client.post("/hw/dev/schedule/upload/", {}, follow=True)
        self.assertIn("Choose the P6 .xlsx file first.", r.content.decode())

    def test_a_very_different_file_waits_for_confirmation(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            self.client.post("/hw/dev/schedule/upload/", {"file": SimpleUploadedFile("a.xlsx", _xlsx())})
        self.assertEqual(P6Activity.objects.count(), 7)
        # the same ids with other dates: no question asked
        with m1, m2:
            r = self.client.post("/hw/dev/schedule/upload/", {"file": SimpleUploadedFile("b.xlsx", _xlsx())}, follow=True)
        self.assertIn("P6 schedule read — 7 activities from b.xlsx.", r.content.decode())
        # a file with 2 of the 7: held in the session, the table untouched, the page asks
        production.cache_plan("dev", PDS, {**production.normalize_plan(PLAN), "p6_completed_id": "13122.A12812"})
        with m1, m2:
            r = self.client.post("/hw/dev/schedule/upload/", {"file": SimpleUploadedFile("vd-only.xlsx", _xlsx({"TPC-Elec_BDE-VD": VD_ROWS}))}, follow=True)
        html = r.content.decode()
        self.assertEqual(P6Activity.objects.count(), 7)
        self.assertEqual(P6Upload.objects.get().filename, "b.xlsx")
        self.assertIn("<b>Not replaced yet.</b> <b>vd-only.xlsx</b> (2 activities) differs a lot from the current schedule:\n    5 of the 7 current activities are not in it, among them 1 that plans name — <span class=\"mono\">13122.A12812</span>.", html)
        self.assertIn('<button type="submit" name="confirm" value="1">Replace anyway</button>', html)
        with m1, m2:
            r = self.client.post("/hw/dev/schedule/upload/", {"discard": "1"}, follow=True)
        self.assertNotIn("Not replaced yet", r.content.decode())
        self.assertEqual(P6Activity.objects.count(), 7)
        with m1, m2:
            r = self.client.post("/hw/dev/schedule/upload/", {"confirm": "1"}, follow=True)
        self.assertIn("Nothing waiting to be confirmed", r.content.decode())
        with m1, m2:
            self.client.post("/hw/dev/schedule/upload/", {"file": SimpleUploadedFile("vd-only.xlsx", _xlsx({"TPC-Elec_BDE-VD": VD_ROWS}))})
            r = self.client.post("/hw/dev/schedule/upload/", {"confirm": "1"}, follow=True)
        self.assertIn("P6 schedule read — 2 activities from vd-only.xlsx.", r.content.decode())
        self.assertEqual(P6Activity.objects.count(), 2)
        self.assertNotIn("Not replaced yet", r.content.decode())

    def test_compare(self):
        self.assertIsNone(p6.compare([]))
        rows = p6.parse("a.xlsx", _xlsx())
        p6.replace(rows, "x", "a.xlsx")
        self.assertEqual(p6.compare(rows), {"n_old": 7, "n_new": 7, "missing": 0, "plan_missing": [], "changed": 0, "warn": False})
        moved = [{**r, "date": date(2031, 1, 1)} for r in rows[:6]]   # one of seven missing, six dates moved: fine
        self.assertEqual(p6.compare(moved), {"n_old": 7, "n_new": 6, "missing": 1, "plan_missing": [], "changed": 6, "warn": False})
        production.cache_plan("dev", PDS, {**production.normalize_plan(PLAN), "p6_needed_id": "13122.A12840"})
        d = p6.compare([r for r in rows if r["activity_id"] != "13122.A12840"])   # but not one a plan names
        self.assertEqual((d["missing"], d["plan_missing"], d["warn"]), (1, ["13122.A12840"], True))
        self.assertTrue(p6.compare(rows[:5])["warn"])   # two of seven = over a fifth

    def test_not_an_architect(self):
        api = _api()
        api.whoami.return_value = {"data": {"architect": False}}
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get("/hw/dev/schedule/").content.decode()
            self.assertEqual(self.client.post("/hw/dev/schedule/upload/", {"file": SimpleUploadedFile("a.xlsx", _xlsx())}).status_code, 403)
        self.assertNotIn('action="/hw/dev/schedule/upload/"', html)
        self.assertNotIn("Upload the month", html)   # nothing to see, nothing to do

    def test_status_page_no_longer_carries_the_upload(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get("/hw/dev/status/").content.decode()
        self.assertNotIn("hc-p6", html)
        self.assertIn('<a class="hc-tab" aria-selected="false" href="/hw/dev/schedule/">P6 schedule</a>', html)


class PlanPageTest(TestCase):
    URL = f"/hw/dev/plan/{PDS}/"

    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("p", "p@p.io", "pw"))
        _node(PDS, instance="dev", component_type_name="PDS module")
        _node(PTID, instance="dev", component_type_name="HD PDS")
        _node("Z00100600002", instance="dev", component_type_name="VD PDS")
        p6.replace(p6.parse("a.xlsx", _xlsx()), "chaoz", "a.xlsx")

    def test_pickers_and_save(self):
        api = _api(plans={PDS: {**PLAN, "p6_completed_id": "13122.A12812", "p6_needed_id": "old-id"}})
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(self.URL).content.decode()
        self.assertIn('<select id="p6-det"><option value="">HD and VD</option>', html)
        self.assertIn('<select id="pl-done-p6" name="p6_completed_id" class="p6-pick" data-kind="prod" data-value="13122.A12812"></select>', html)
        self.assertIn('<select id="pl-need-p6" name="p6_needed_id" class="p6-pick" data-kind="install" data-value="old-id"></select>', html)
        self.assertIn('<input type="month" id="pl-done" name="completed_by" value="2026-12"', html)   # the fallback stays editable
        self.assertIn('<script id="p6-options" type="application/json">', html)
        self.assertIn('"id": "13122.A12812", "kind": "prod"', html)
        with m1, m2:
            r = self.client.post(self.URL, {"needed": "1500", "completed_by": "", "needed_by": "2029-05",
                                            "p6_completed_id": "13122.A12812", "p6_needed_id": "13122.A12834", "reason": "from P6"})
            self.assertEqual(r["Location"], self.URL)
        body = json.loads(api.post_component_type_image.call_args.args[1].getvalue())
        self.assertEqual((body["p6_completed_id"], body["p6_needed_id"], body["completed_by"]), ("13122.A12812", "13122.A12834", ""))
        self.assertEqual(api.post_component_type_image.call_args.args[2], f"Production_plan_{PDS}.json")
        self.assertEqual(ProductionPlan.objects.get().p6_needed_id, "13122.A12834")
        self.assertIn("p6 needed id old-id → 13122.A12834", ActivityEvent.objects.get(kind="curation").summary)
        # read-only: the resolved dates with their ids, and the missing one flagged
        api.get_component_type.return_value = {"data": {"roles": [{"id": 34, "name": "x"}]}}
        with mock.patch("explore.views._my_roles", return_value=[]), m1, m2:
            html = self.client.get(self.URL).content.decode()
        self.assertIn('<dt>Completed by</dt><dd>2029-03-08 <span class="p6-id" title="P6 13122.A12812: Deliver to Storage (300 modules) (1500 total) #1 - CSU (Forecast)">P6 13122.A12812</span></dd>', html)
        self.assertIn('<dt>Needed by</dt><dd>2028-05 <span class="p6-id" title="">P6 old-id</span></dd>', html)
        self.assertIn("&#9888; old-id is not in the latest P6 schedule", html)
        self.assertIn('<td><span class="p6-id">P6 13122.A12812</span></td>', html)   # the history names the id

    def test_no_upload_means_plain_id_inputs(self):
        P6Activity.objects.all().delete()
        P6Upload.objects.all().delete()
        api = _api(plans={PDS: PLAN})
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(self.URL).content.decode()
        self.assertNotIn("p6-pick", html)
        self.assertIn('<input type="text" name="p6_completed_id" value="" placeholder="production activity id"', html)

    def test_one_plan_per_consortium_for_a_shared_type(self):
        production.cache_list("dev", PTID, production.normalize_list(LIST))
        production.cache_list("dev", "Z00100600002", [{"type": PDS, "label": ""}])
        api = _api(plans={PDS: PLAN})
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(self.URL + "?for=Z00100600002").content.decode()
        self.assertIn("<h1>Production plan for VD PDS", html)
        self.assertIn("No plan for VD PDS on this type yet — shown is the type’s own plan. Saving here makes a plan for VD PDS only.", html)
        self.assertIn('value="48000"', html)   # prefilled from the plain plan
        self.assertIn('<input type="hidden" name="for" value="Z00100600002">', html)
        self.assertIn(f'<span class="mono">Production_plan_{PDS}_Z00100600002.json</span> on the type in HWDB · last set', html)   # no version of its own yet
        with m1, m2:
            r = self.client.post(self.URL, {"needed": "9", "completed_by": "2026-12", "needed_by": "2028-05", "comment": PLAN["comment"], "for": "Z00100600002", "reason": "VD share"})
            self.assertEqual(r["Location"], self.URL + "?for=Z00100600002")
        self.assertEqual(api.post_component_type_image.call_args.args[2], f"Production_plan_{PDS}_Z00100600002.json")
        self.assertEqual(ProductionPlan.objects.get(consortium="Z00100600002").needed, 9)
        self.assertEqual(ActivityEvent.objects.get(kind="curation").summary, f"Production plan of {PDS} for Z00100600002: needed 48000 → 9 — VD share")
        # a type on one list ignores ?for=
        with m1, m2:
            html = self.client.get(f"/hw/dev/plan/{SIPM}/?for={PTID}").content.decode()
        self.assertNotIn("Production plan for", html)
        self.assertIn(f'<span class="mono">Production_plan_{SIPM}.json</span>', html)


class StatusPageTest(TestCase):
    URL = f"/hw/dev/status/{PTID}/"

    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("s", "s@s.io", "pw"))
        _node(PTID, instance="dev", component_type_name="HD PDS")
        _node(PDS, instance="dev", component_type_name="PDS module")
        p6.replace(p6.parse("a.xlsx", _xlsx()), "chaoz", "a.xlsx")

    def test_p6_dates_and_the_consortiums_own_plan(self):
        own = {**PLAN, "needed": 9, "p6_completed_id": "13122.A12812", "p6_needed_id": "13122.A12834"}
        api = _api(plans={PDS: PLAN})
        listing = api.get_component_type_images.side_effect
        api.get_component_type_images.side_effect = lambda t: {"data": listing(t)["data"] + ([
            {"image_id": "own", "image_name": f"Production_plan_{PDS}_{PTID}.json", "created": "2026-10-20T10:00:00", "comments": "VD"}] if t == PDS else [])}
        api.get_image_response.side_effect = lambda iid: mock.Mock(content=json.dumps(
            own if iid == "own" else LIST if iid == "l1" else PLAN).encode())
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(self.URL).content.decode()
        self.assertIn('<td class="cl-const ps-num">9</td>', html)   # the consortium's own plan over the plain one
        self.assertIn('<td class="cl-const" title="P6 13122.A12812: Deliver to Storage (300 modules) (1500 total) #1 - CSU (Forecast)">8 Mar 2029</td>', html)
        self.assertIn('<td class="cl-const" title="P6 13122.A12834: Install modules in Detector Slice 21-22 - CSU (Forecast)">30 Jan 2030</td>', html)
        self.assertIn('<td class="cl-const ps-num">10</td>', html)   # the float, whole months
        self.assertEqual(ProductionPlan.objects.get(part_type_id=PDS, consortium=PTID).needed, 9)
        self.assertEqual(ProductionPlan.objects.get(part_type_id=PDS, consortium="").needed, 48000)
        self.assertEqual(api.get_component_type_images.call_count, 3)   # one listing per type
        # the overview draws the same from the caches
        ConsortiumTypeOverride.objects.create(instance="dev", part_type_id=PTID)
        with m1, m2:
            html = self.client.get("/hw/dev/status/").content.decode()
        self.assertIn('title="P6 13122.A12812: Deliver to Storage (300 modules) (1500 total) #1 - CSU (Forecast)">8 Mar 2029</td>', html)
        self.assertIn(f'<a class="ps-plan" href="/hw/dev/plan/{PDS}/?for={PTID}"', html)
