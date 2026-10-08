"""#199: a consortium's production-status table — the ``status`` checklist
flag and month columns, the engine shaping an item's Specs into the slide's
table and the plan cache, the status page, the Detector tab's list and the
type page's plan feed. HWDB mocked — no network.

    python manage.py test explore.tests.test_production
"""

import json
from datetime import date
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from explore import checklistforms, navigation, production
from explore.models import HwdbComponentEvent, HwdbTestEvent, ProductionPlan, ProductionTable
from explore.tests.test_events import _node

PTID = "Z00100600001"
PID = f"{PTID}-00001"
STATUS = {
    "name": "Production status",
    "test_type_name": "Production status",
    "status": True,
    "sections": [{"title": "Table", "fields": [
        {"type": "table", "label": "Components", "to_spec": True,
         "columns": ["Type IDs", {"label": "PRR date", "month": True}, "Needed",
                     "Produced and tested", {"label": "Completed by", "month": True},
                     {"label": "Needed by", "month": True}, "Comments"],
         "rows": ["Rails and cables", "SiPM boards", "Monitoring system"]},
    ]}],
}
DATA = {"Table": {"Components": {
    "Rails and cables": {"Type IDs": "D05800100001", "PRR date": "2022-10", "Needed": 1500,
                         "Produced and tested": 1200, "Completed by": "2027-03",
                         "Needed by": "2029-01", "Comments": "<green>Near completion</green>"},
    "SiPM boards": {"Type IDs": "D05800200001 | D05800200002", "PRR date": "2022-11",
                    "Needed": 48000, "Produced and tested": "39000 (80%)",
                    "Completed by": "2026-12", "Needed by": "2028-05"},
    "Monitoring system": {"PRR date": "2026-10", "Needed": 18, "Produced and tested": "Feb 2027"},
}}}


def _api(schema=STATUS, data=DATA, items=None):
    api = mock.MagicMock()
    api.get_component_type_images.return_value = {"data": [
        {"image_id": "st1", "image_name": f"Checklist_{PTID}_Production status.json",
         "created": "2026-10-08T00:00:00"},
        {"image_id": "org", "image_name": f"Checklist_{PTID}_Organizer.json",
         "created": "2026-10-08T00:00:00"}]}
    other = {"name": "Organizer", "organizer": True, "sections": []}
    api.get_image_response.side_effect = lambda iid: mock.Mock(
        content=json.dumps(schema if iid == "st1" else other).encode())
    api.get_component.return_value = {"data": {
        "part_id": PID, "serial_number": "PDS",
        "specifications": [{"DATA": {}, "created": "2026-09-01 10:00:00-05:00"},
                           {"DATA": data, "created": "2026-10-08 10:00:00-05:00"}]}}
    api.get_component_types.return_value = {"data": [{"part_id": p} for p in (items or [])]}
    return api


def _mocked(api):
    return (mock.patch("explore.views.mint_for", return_value="bearer"),
            mock.patch("explore.views.FnalDbApiClient", return_value=api))


class SchemaTest(TestCase):
    def test_status_flag_and_month_columns(self):
        s = checklistforms.normalize(STATUS, "Production status")
        self.assertTrue(s["status"])
        f = s["sections"][0]["fields"][0]
        self.assertEqual(f["months"], ["PRR date", "Completed by", "Needed by"])
        self.assertEqual(f["columns"][:3], ["Type IDs", "PRR date", "Needed"])
        self.assertTrue(f["to_spec"])
        self.assertFalse(checklistforms.normalize({"name": "x", "sections": []}, "x")["status"])

    def test_date_column_kind(self):
        # Chao 2026-10-08: `label = date` — a day picker beside the month one
        cfg = json.loads(json.dumps(STATUS))
        cfg["sections"][0]["fields"][0]["columns"].append({"label": "Received", "date": True})
        s = checklistforms.normalize(cfg, "x")
        f = s["sections"][0]["fields"][0]
        self.assertEqual(f["dates"], ["Received"])
        self.assertNotIn("Received", f["months"])
        data = json.loads(json.dumps(DATA))
        data["Table"]["Components"]["Rails and cables"]["Received"] = "2026-09-15"
        b = checklistforms.bind(s, {"DATA": data})["sections"][0]["fields"][0]
        c = b["trows"][0]["cells"][7]
        self.assertTrue(c["date"]); self.assertNotIn("month", c)
        from django.template.loader import render_to_string
        html = render_to_string("explore/_checklist_cell.html", {"c": c, "f": b, "forloop": {"counter0": 7}})
        self.assertIn('<input type="date" name="f0-0-r0-c7" value="2026-09-15" placeholder="YYYY-MM-DD"', html)
        parsed = checklistforms.parse(s, {"f0-0-r0-c7": "2026-09-15"})
        self.assertEqual(parsed["Table"]["Components"]["Rails and cables"]["Received"], "2026-09-15")
        shaped = production.shape(s, data)
        self.assertEqual(shaped["rows"][0]["cells"][7], {"kind": "month", "text": "2026-09-15", "past": True})
        # a full date in a month-role column still feeds the plan by its month
        data["Table"]["Components"]["Rails and cables"]["Completed by"] = "2027-03-20"
        self.assertEqual(production.shape(s, data)["rows"][0]["completed_by"], "2027-03")   # the plan is monthly
        self.assertEqual(production.months_between("2027-03-20", "2029-01"), 22)

    def test_status_forces_specs_on_the_table(self):
        cfg = json.loads(json.dumps(STATUS))
        cfg["sections"][0]["fields"][0].pop("to_spec")
        s = checklistforms.normalize(cfg, "Production status")
        self.assertTrue(s["sections"][0]["fields"][0]["to_spec"])
        cfg["status"] = False
        self.assertFalse(checklistforms.normalize(cfg, "x")["sections"][0]["fields"][0]["to_spec"])

    def test_month_cell_renders_a_month_input_and_round_trips(self):
        s = checklistforms.normalize(STATUS, "Production status")
        bound = checklistforms.bind(s, {"DATA": DATA})
        f = bound["sections"][0]["fields"][0]
        prr = f["trows"][0]["cells"][1]
        self.assertTrue(prr["month"])
        self.assertEqual(prr["value"], "2022-10")
        post = {f"{f['key']}-r0-c1": "2027-05", f"{f['key']}-r0-c2": "1500"}
        parsed = checklistforms.parse(s, post)
        self.assertEqual(parsed["Table"]["Components"]["Rails and cables"],
                         {"PRR date": "2027-05", "Needed": 1500})


class EngineTest(TestCase):
    def test_rows_shape_float_and_plan_values(self):
        s = checklistforms.normalize(STATUS, "Production status")
        shaped = production.shape(s, DATA)
        self.assertEqual(shaped["columns"][-1], "Float (months)")
        r0, r1, r2 = shaped["rows"]
        self.assertEqual(r0["label"], "Rails and cables")
        self.assertEqual([c["text"] for c in r0["cells"]],
                         ["D05800100001", "Oct 2022", "1,500", "1,200", "Mar 2027", "Jan 2029",
                          "<green>Near completion</green>", "22"])
        self.assertEqual(r0["cells"][0], {"kind": "types", "text": "D05800100001", "ids": ["D05800100001"]})
        self.assertTrue(r0["cells"][1]["past"])
        self.assertEqual((r0["needed"], r0["completed_by"], r0["needed_by"]), (1500, "2027-03", "2029-01"))
        self.assertEqual(r1["type_ids"], ["D05800200001", "D05800200002"])
        self.assertEqual(r1["cells"][-1]["text"], "17")
        self.assertEqual(r2["type_ids"], [])                 # no type → nothing for the cache
        self.assertEqual(r2["cells"][-1]["text"], "")         # no dates → no float
        self.assertEqual(r2["cells"][3]["text"], "Feb 2027")  # produced-and-tested is free text

    def test_float_column_of_the_tables_own_is_not_doubled(self):
        cfg = json.loads(json.dumps(STATUS))
        cfg["sections"][0]["fields"][0]["columns"].append("Float")
        s = checklistforms.normalize(cfg, "x")
        self.assertNotIn("Float (months)", production.shape(s, DATA)["columns"])

    def test_past_month_is_relative_to_today(self):
        s = checklistforms.normalize(STATUS, "x")
        _t, f = production.status_table(s)
        rows = production.rows(f, production.table_value(s, _t, f, DATA), today=date(2022, 10, 1))
        self.assertTrue(rows["rows"][0]["cells"][1]["past"])    # Oct 2022 on 2022-10-01
        self.assertFalse(rows["rows"][1]["cells"][1]["past"])   # Nov 2022 not yet

    def test_table_under_its_own_spec_key(self):
        cfg = json.loads(json.dumps(STATUS))
        cfg["sections"][0]["fields"][0]["spec"] = "plan"
        s = checklistforms.normalize(cfg, "x")
        shaped = production.shape(s, {"plan": DATA["Table"]["Components"]})
        self.assertEqual(shaped["rows"][0]["needed"], 1500)
        self.assertEqual(production.shape(s, "a string")["rows"][0]["needed"], None)

    def test_refresh_rewrites_one_items_table_and_plan_rows(self):
        s = checklistforms.normalize(STATUS, "x")
        n = production.refresh("dev", PTID, PID, "PDS", production.card("Production status", s, DATA, "2026-10-08"))
        self.assertEqual(n, 4)   # one row per type named (1 + 2) + the untyped Monitoring row
        rows = {(p.part_type_id, p.component): p for p in ProductionPlan.for_instance("dev")}
        # one type per row is the convention: a two-type row feeds its dates, not its total (Chao 2026-10-08)
        self.assertEqual(rows[("D05800200002", "SiPM boards")].needed, None)
        self.assertEqual(rows[("D05800200002", "SiPM boards")].completed_by, "2026-12")
        self.assertEqual(rows[("D05800100001", "Rails and cables")].needed, 1500)
        self.assertEqual(rows[("", "Monitoring system")].needed, 18)
        self.assertEqual(rows[("", "Monitoring system")].checklist, "Production status")
        self.assertEqual(rows[("D05800100001", "Rails and cables")].completed_by, "2027-03")
        t = ProductionTable.for_instance("dev").get()
        self.assertEqual((t.source_type_id, t.source_part_id, t.checklist, t.serial, t.as_of),
                         (PTID, PID, "Production status", "PDS", "2026-10-08"))
        self.assertEqual(t.columns[-1], "Float (months)")
        self.assertEqual(t.rows[0]["cells"][1], {"kind": "month", "text": "Oct 2022", "past": True})
        # a second checklist on the same item lives beside it; clearing one leaves the other
        production.refresh("dev", PTID, PID, "PDS", production.card("Other", s, DATA))
        self.assertEqual(ProductionTable.for_instance("dev").count(), 2)
        production.refresh("dev", PTID, PID, "PDS", None, checklist="Production status")
        self.assertEqual([t.checklist for t in ProductionTable.for_instance("dev")], ["Other"])
        self.assertEqual(ProductionPlan.for_instance("dev").filter(checklist="Production status").count(), 0)


class StatusPageTest(TestCase):
    URL = f"/hw/dev/status/{PTID}/"

    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("s", "s@s.io", "pw"))
        _node(PTID, instance="dev", system_id=1, system_name="Sandbox", subsystem_id=6,
              subsystem_name="Test Production Status", component_type_name="Test Production Status",
              full_name="Z.Sandbox.Test Production Status.Test Production Status")
        HwdbComponentEvent.objects.create(instance="dev", part_type_id=PTID, part_id=PID, serial_number="PDS")

    def test_renders_the_table_and_fills_the_plan_cache(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            r = self.client.get(self.URL)
            html = r.content.decode()
        self.assertEqual(r.status_code, 200)
        self.assertIn("<h1>Test Production Status</h1>", html)
        self.assertIn('<table class="cl-table cl-gridlines ps-table">', html)   # the fill page's table look
        self.assertIn("<th></th><th>Type IDs</th><th>PRR date</th>", html)
        self.assertIn("<th>Float (months)</th>", html)
        self.assertIn('<th scope="row" class="cl-rowlab">Rails and cables</th>', html)
        self.assertIn('<td class="cl-const ps-past">Oct 2022</td>', html)
        self.assertIn('<td class="cl-const">Mar 2027</td>', html)
        self.assertIn('<span class="clmd-green">Near completion</span>', html)   # comments take the checklist markup
        # a long comment is full Markdown (paragraphs, lists), the plain cells still one line
        api.get_component.return_value["data"]["specifications"][-1]["DATA"]["Table"]["Components"]["SiPM boards"]["Comments"] = "First line\n\n- one\n- two"
        with m1, m2:
            html = self.client.get(self.URL).content.decode()
        self.assertIn("<p>First line</p>\n<ul>\n<li>one</li>\n<li>two</li>\n</ul>", html)
        self.assertIn('<td class="cl-const"><p>1,500</p>\n</td>', html)
        self.assertIn('?node=D05800200002" title="the type’s page">D05800200002</a>', html)
        self.assertIn("as of 2026-10-08", html)
        self.assertIn(f'href="/hw/dev/part/{PID}/checklist/Production%20status/"', html)   # ✎ Edit table
        self.assertIn("&#9998; Edit checklist", html)
        self.assertEqual(ProductionPlan.for_instance("dev").filter(source_part_id=PID).count(), 4)
        self.assertEqual(ProductionTable.for_instance("dev").get().serial, "PDS")
        self.assertEqual(api.get_component.call_args_list, [mock.call(PID)] * 2)   # one read per visit
        api.get_component_types.assert_not_called()   # the mirror knew the item

    def test_older_submission_via_the_picker(self):
        # Hajime 2026-10-08: the Submission list on the rendered page too
        api = _api()
        old = json.loads(json.dumps(DATA)); old["Table"]["Components"]["Rails and cables"]["Needed"] = 1400
        api.get_tests.return_value = {"data": [
            {"created": "2026-10-08T10:00:00", "creator": {"username": "chaoz"}, "test_data": {"DATA": DATA}},
            {"created": "2026-10-01T09:00:00", "creator": {"username": "hajime3"}, "test_data": {"DATA": old}}]}
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(self.URL).content.decode()
            self.assertIn('<select class="ps-rev" data-pid="Z00100600001-00001"', html)
            self.assertIn('<option value="0" selected>2026-10-08 10:00 · chaoz (latest)</option>', html)
            self.assertIn('<option value="1">2026-10-01 09:00 · hajime3</option>', html)
            self.assertIn("<p>1,500</p>", html)
            self.assertNotIn("an older submission —", html)
            html = self.client.get(self.URL + "?rev=1&pid=Z00100600001-00001").content.decode()
        self.assertIn("<p>1,400</p>", html)                        # the old table, read off the test record
        self.assertIn('<option value="1" selected>', html)
        self.assertIn("an older submission — the Detector tab and the plan lines keep the latest", html)
        self.assertIn("as of 2026-10-01", html)
        self.assertIn(f'href="/hw/dev/part/{PID}/checklist/Production%20status/?rev=1"', html)
        self.assertEqual(ProductionPlan.for_instance("dev").get(part_type_id="D05800100001").needed, 1500)   # cache = latest
        api.get_tests.assert_called_with(PID, test_type_id="Production status", history=True)
        api.get_tests.return_value = {"data": [{"created": "2026-10-08T10:00:00", "test_data": {"DATA": DATA}}]}
        with m1, m2:
            html = self.client.get(self.URL).content.decode()
        self.assertNotIn('class="ps-rev"', html)                   # one submission: nothing to pick

    def test_unsynced_type_asks_hwdb_for_its_items(self):
        HwdbComponentEvent.objects.all().delete()
        api = _api(items=[PID])
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(self.URL).content.decode()
        self.assertIn('<th scope="row" class="cl-rowlab">Rails and cables</th>', html)
        api.get_component_types.assert_called_once_with(PTID)

    def test_no_status_checklist_says_so(self):
        api = _api()
        api.get_component_type_images.return_value = {"data": []}
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(self.URL).content.decode()
        self.assertIn("No production-status checklist on this type yet", html)
        api.get_component.assert_not_called()


class DetectorListTest(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("d", "d@d.io", "pw"))

    def test_detector_pages_link_each_other(self):
        html = self.client.get("/hw/dev/hierarchy/").content.decode()
        self.assertIn('<a class="hc-tab" aria-selected="true" href="/hw/dev/hierarchy/">Hierarchy chart</a>', html)
        self.assertIn('<a class="hc-tab" aria-selected="false" href="/hw/dev/status/">Production status</a>', html)
        self.assertNotIn("hc-cons", html)
        r = self.client.get("/hw/dev/hierarchy/?tab=status")   # the old tab link
        self.assertEqual(r["Location"], "/hw/dev/status/")

    def test_overview_indexes_and_shows_one_consortium_at_a_time(self):
        _node(PTID, instance="dev", system_id=1, system_name="Sandbox", subsystem_id=6,
              subsystem_name="x", component_type_name="Test Production Status",
              full_name="Z.Sandbox.x.Test Production Status")
        html = self.client.get("/hw/dev/status/").content.decode()
        self.assertIn('<a class="hc-tab" aria-selected="true" href="/hw/dev/status/">Production status</a>', html)
        self.assertIn('<a href="?c=Z00100600001" class="hc-pick" data-c="Z00100600001">Test Production Status</a>', html)
        self.assertIn('<td class="num">—</td>', html)   # not read yet: no numbers in the index
        self.assertIn(f'Not read yet — <a href="/hw/dev/status/{PTID}/">open its status page</a>', html)
        s = checklistforms.normalize(STATUS, "x")
        production.refresh("dev", PTID, PID, "PDS", production.card("Production status", s, DATA, "2026-10-08"))
        html = self.client.get("/hw/dev/status/").content.decode()
        self.assertNotIn("Not read yet", html)
        due = sum(1 for m in ("2027-03", "2026-12") if m <= timezone.localdate().strftime("%Y-%m"))   # completed-by months already passed
        self.assertIn(f'<td class="num">3</td>\n        <td>2028-05</td>\n        <td class="num">{due}</td>', html)
        self.assertIn('<button type="button" class="hc-pill" role="tab" data-c="Z00100600001" aria-selected="true">Test Production Status</button>', html)
        self.assertIn('<div class="hc-cons" data-c="Z00100600001">', html)
        self.assertIn('<th scope="row" class="cl-rowlab">Rails and cables</th>', html)   # the cached table, no HWDB call
        self.assertIn('<td class="cl-const ps-past">Oct 2022</td>', html)
        self.assertIn(f'href="/hw/dev/part/{PID}/checklist/Production%20status/"', html)
        self.assertIn("· as of 2026-10-08 · read ", html)
        self.assertIn('localStorage.setItem("hcCons", id)', html)

    def test_prod_overview_is_empty_for_now(self):
        html = self.client.get("/hw/status/").content.decode()
        self.assertIn("No consortium type yet", html)
        self.assertNotIn("hc-pill", html.split("<h1>")[1])

class PlanFeedTest(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("p", "p@p.io", "pw"))
        self.node = _node("D05800100001", tests_synced_at=timezone.now(), n_tests=1)
        HwdbTestEvent.objects.create(part_type_id="D05800100001", part_id="", test_type_name="t",
                                     created=timezone.now())
        HwdbComponentEvent.objects.create(part_type_id="D05800100001", part_id="P1", created=timezone.now())

    def test_type_page_carries_the_consortiums_plan(self):
        url = navigation.leaf_path_for("prod", "D05800100001")
        html = self.client.get(url).content.decode()
        self.assertNotIn("data-plan-url", html)
        ProductionPlan.objects.create(instance="prod", part_type_id="D05800100001", source_type_id=PTID,
                                      source_part_id=PID, component="Rails and cables", needed=1500,
                                      completed_by="2027-03", needed_by="2029-01")
        html = self.client.get(url).content.decode()
        self.assertIn('data-plan-total="1500" data-plan-done="2027-03" data-plan-need="2029-01" '
                      f'data-plan-source="Rails and cables" data-plan-url="/hw/status/{PTID}/"', html)
        self.assertIn("planFixed = true", html)


class ConsortiumTypeTest(TestCase):
    """#199 round 3 (Chao): the Detector list comes from the consortium-type
    mark — curation.yaml's ``consortium_types`` plus overrides set from the
    type page or automatically by saving a production-status checklist.
    The override cases run on prod (a curated FD-VD leaf), where the yaml
    lists nothing; the yaml case is dev's Z00100600001."""

    OTHER = "D05700200099"

    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("c", "c@c.io", "pw"))
        self.node = _node(self.OTHER, component_type_name="Other consortium")
        self.leaf_url = navigation.leaf_path_for("prod", self.OTHER)

    def test_union_of_yaml_and_overrides(self):
        from explore import curation
        from explore.models import ConsortiumTypeOverride
        self.assertEqual(curation.consortium_types("dev"), [PTID])
        self.assertEqual(curation.consortium_types("prod"), [])
        ConsortiumTypeOverride.objects.create(instance="prod", part_type_id=self.OTHER)
        ConsortiumTypeOverride.objects.create(instance="dev", part_type_id=PTID)   # yaml wins, no duplicate
        self.assertEqual(curation.consortium_types("dev"), [PTID])
        self.assertEqual(curation.consortium_types("prod"), [self.OTHER])
        html = self.client.get("/hw/status/").content.decode()
        self.assertIn('<h2>Other consortium <span class="mono">D05700200099</span>', html)
        self.assertIn('<td class="num">—</td>', html)   # not read yet: no numbers in the index

    def test_type_page_class_dropdown(self):
        from explore.models import ActivityEvent, ConsortiumTypeOverride, ShippingTypeOverride
        url = f"/hw/type-class/{self.OTHER}/"
        with mock.patch("explore.views._is_architect", return_value=True):
            html = self.client.get(self.leaf_url).content.decode()
            self.assertIn('<select name="class" title=', html)
            self.assertIn('<option value="none" selected>no classification</option>', html)
            self.assertNotIn("<dt>Status</dt>", html)
            resp = self.client.post(url, {"next": self.leaf_url, "class": "consortium"})
            self.assertEqual(resp["Location"], self.leaf_url)
            self.assertTrue(ConsortiumTypeOverride.objects.filter(instance="prod", part_type_id=self.OTHER).exists())
            html = self.client.get(self.leaf_url).content.decode()
            self.assertIn('<option value="consortium" selected>consortium type</option>', html)
            self.assertIn('<dt>Status</dt><dd class="span"><a href="/hw/status/D05700200099/"', html)   # its own line
            self.client.post(url, {"next": self.leaf_url, "class": "shipping"})   # switching clears the other mark
            self.assertFalse(ConsortiumTypeOverride.objects.exists())
            self.assertTrue(ShippingTypeOverride.objects.filter(instance="prod", part_type_id=self.OTHER).exists())
            self.client.post(url, {"next": self.leaf_url, "class": "none"})
            self.assertFalse(ShippingTypeOverride.objects.exists())
            self.assertEqual(self.client.post(url, {"next": self.leaf_url, "class": "x"}).status_code, 400)
            # yaml-curated (dev): the dropdown is disabled, a POST is refused
            r = self.client.post(f"/hw/dev/type-class/{PTID}/", {"next": self.leaf_url, "class": "none"})
            html = self.client.get(r["Location"]).content.decode()
            self.assertIn("is curated in curation.yaml", html)
        self.assertEqual(ActivityEvent.objects.filter(kind="curation").count(), 4)   # +cons, −cons +ship, −ship
        with mock.patch("explore.views._is_architect", return_value=False):
            ConsortiumTypeOverride.objects.create(instance="prod", part_type_id=self.OTHER)
            html = self.client.get(self.leaf_url).content.decode()
            self.assertNotIn('<select name="class"', html)
            self.assertIn("<span class=\"sep\">·</span> consortium type</dd>", html)
            self.assertIn("<dt>Status</dt>", html)
            self.assertEqual(self.client.post(url, {"next": self.leaf_url, "class": "none"}).status_code, 403)

    def test_saving_a_status_checklist_marks_the_type(self):
        from explore.models import ConsortiumTypeOverride
        api = _api()
        api.post_component_type_image.return_value = {"status": "OK", "image_id": "new"}
        m1, m2 = _mocked(api)
        with m1, m2:
            self.client.post(f"/hw/checklist-config/{self.OTHER}/", {
                "cl_name": "Plain", "config_json": json.dumps({"name": "P", "test_type_name": "T", "sections": []})})
            self.assertFalse(ConsortiumTypeOverride.objects.exists())
            r = self.client.post(f"/hw/checklist-config/{self.OTHER}/", {
                "cl_name": "Production status", "config_json": json.dumps(STATUS)})
            self.assertTrue(ConsortiumTypeOverride.objects.filter(instance="prod", part_type_id=self.OTHER).exists())
            html = self.client.get(r["Location"]).content.decode()
            self.assertIn("is now a consortium type", html)
            # saving again doesn't duplicate; a yaml-listed type isn't overridden
            self.client.post(f"/hw/checklist-config/{self.OTHER}/", {
                "cl_name": "Production status", "config_json": json.dumps(STATUS)})
            self.client.post(f"/hw/dev/checklist-config/{PTID}/", {
                "cl_name": "Production status", "config_json": json.dumps(STATUS)})
        self.assertEqual(ConsortiumTypeOverride.objects.count(), 1)

    def test_status_read_without_a_status_checklist_unmarks_an_override(self):
        from explore.models import ConsortiumTypeOverride
        ConsortiumTypeOverride.objects.create(instance="prod", part_type_id=self.OTHER)
        api = _api()
        api.get_component_type_images.return_value = {"data": []}
        m1, m2 = _mocked(api)
        with m1, m2:
            self.client.get(f"/hw/status/{self.OTHER}/")
        self.assertFalse(ConsortiumTypeOverride.objects.exists())


class TextPreviewTest(TestCase):
    def test_renders_with_the_status_pages_filter(self):
        self.client.force_login(get_user_model().objects.create_user("t", "t@t.io", "pw"))
        r = self.client.post("/hw/dev/text-preview/", {"text": "**bold** <green>ok</green>\n\n- a"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content.decode(), '<p><strong>bold</strong> <span class="clmd-green">ok</span></p>\n<ul>\n<li>a</li>\n</ul>\n')
        self.assertEqual(self.client.get("/hw/dev/text-preview/").status_code, 405)
        self.client.logout()
        self.assertEqual(self.client.post("/hw/dev/text-preview/", {"text": "x"}).status_code, 302)

    def test_fill_page_dialog_has_the_preview_pane(self):
        self.client.force_login(get_user_model().objects.create_user("u", "u@u.io", "pw"))
        from explore.tests.test_checklist_forms import PAGE, _api as _forms_api, _mocked as _forms_mocked
        api = _forms_api(); m1, m2 = _forms_mocked(api)
        with m1, m2:
            html = self.client.get(PAGE).content.decode()
        self.assertIn('<div class="cl-td-panes"><textarea></textarea><div class="cl-td-prev cl-md"></div></div>', html)
        self.assertIn('fetch("/hw/dev/text-preview/", { method: "POST"', html)
        self.assertNotIn(">Production status</a>", html)   # a plain checklist has no status page

    def test_status_checklist_fill_page_links_its_rendered_table(self):
        self.client.force_login(get_user_model().objects.create_user("v", "v@v.io", "pw"))
        from explore.tests.test_checklist_forms import PAGE, PTID as FORMS_PTID, _api as _forms_api, _mocked as _forms_mocked
        api = _forms_api(schema=STATUS); m1, m2 = _forms_mocked(api)
        with m1, m2:
            html = self.client.get(PAGE).content.decode()
        self.assertIn(f'href="/hw/dev/status/{FORMS_PTID}/" title="The table as last submitted, rendered', html)
        self.assertIn(">Production status</a>", html)


class EditorRowsTest(TestCase):
    def test_rows_dialog_accepts_bare_row_names(self):
        # Chao 2026-10-08: a schema with "rows": ["Rails", …] showed blank labels in the editor's rows dialog
        self.client.force_login(get_user_model().objects.create_user("e", "e@e.io", "pw"))
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(f"/hw/dev/checklist-config/{PTID}/").content.decode()
        self.assertIn('return typeof rw === "string" ? { label: rw } : rw;', html)

    def test_plain_cells_offer_the_text_editor(self):
        # Chao 2026-10-08: a comment cell gets ✎ → textarea; computed / ranged cells don't
        s = checklistforms.normalize(STATUS, "x")
        bound = checklistforms.bind(s, {"DATA": DATA})
        f = bound["sections"][0]["fields"][0]
        from django.template.loader import render_to_string
        row = f["trows"][0]
        cells = "".join(render_to_string("explore/_checklist_cell.html", {"c": c, "f": f, "forloop": {"counter0": i}})
                        for i, c in enumerate(row["cells"]))
        self.assertEqual(cells.count('class="cl-cell-expand cl-cell-btn"'), 4)   # Type IDs, Needed, Produced and tested, Comments
        self.assertNotIn('type="month" name="f0-0-r0-c1" value="2022-10" placeholder="YYYY-MM" pattern="\\d{4}-\\d{2}" data-ci="1"><button', cells)
        cfg = json.loads(json.dumps(STATUS))
        cfg["sections"][0]["fields"][0]["columns"][2] = {"label": "Needed", "min": 0}
        cfg["sections"][0]["fields"][0]["columns"][3] = {"label": "Total", "formula": "C3 * 2"}
        f = checklistforms.bind(checklistforms.normalize(cfg, "x"), {"DATA": {}})["sections"][0]["fields"][0]
        cells = "".join(render_to_string("explore/_checklist_cell.html", {"c": c, "f": f, "forloop": {"counter0": i}})
                        for i, c in enumerate(f["trows"][0]["cells"]))
        self.assertEqual(cells.count('class="cl-cell-expand cl-cell-btn"'), 2)   # Type IDs, Comments only

    def test_multiline_text_round_trips_through_a_textarea(self):
        s = checklistforms.normalize(STATUS, "x")
        data = json.loads(json.dumps(DATA))
        data["Table"]["Components"]["Rails and cables"]["Comments"] = "line one\n\n- a\n- b"
        f = checklistforms.bind(s, {"DATA": data})["sections"][0]["fields"][0]
        from django.template.loader import render_to_string
        c = f["trows"][0]["cells"][6]
        self.assertTrue(c["multiline"])
        self.assertNotIn("multiline", f["trows"][0]["cells"][5])   # absent on a one-line cell (legacy golden)
        html = render_to_string("explore/_checklist_cell.html", {"c": c, "f": f, "forloop": {"counter0": 6}})
        self.assertIn('<textarea name="f0-0-r0-c6" rows="1" class="cl-cell-ta" data-ci="6">line one\n\n- a\n- b</textarea>', html)
        parsed = checklistforms.parse(s, {"f0-0-r0-c6": "line one\n\n- a\n- b"})
        self.assertEqual(parsed["Table"]["Components"]["Rails and cables"]["Comments"], "line one\n\n- a\n- b")
