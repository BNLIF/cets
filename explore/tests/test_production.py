"""#199/#200: the production status per consortium — a plan on each
component type (``Production_plan_<type>.json``), a component list on the
consortium type (``Production_list_<type>.json``), the table generated
from both plus the mirror's counts; the plan and list pages, the type
page's Plan line and plan feed, the Detector area's pages; the ``month``
/ ``date`` column kinds and the cell text editor that stay from #199.
HWDB mocked — no network.

    python manage.py test explore.tests.test_production
"""

import json
from datetime import date
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from explore import checklistforms, navigation, production
from explore.models import ConsortiumTypeOverride, HwdbComponentEvent, HwdbTestEvent, ProductionList, ProductionPlan
from explore.tests.test_events import _node

PTID = "Z00100600001"           # the consortium's virtual type (dev; marked from its type page)
SIPM, PDS = "D00400300001", "Z10400100001"
LIST = {"rows": [{"type": SIPM, "label": "SiPM boards (6 SiPMs)"}, {"type": PDS}]}
PLAN = {"needed": 48000, "completed_by": "2026-12", "needed_by": "2028-05",
        "comment": "<green>**Near completion**</green>\n\n- HPK all tested\n- FBK 90% tested",
        "updated_by": "chaoz", "updated": "2026-10-08"}
TABLE_SCHEMA = {
    "name": "Dates", "test_type_name": "Dates",
    "sections": [{"title": "Table", "fields": [
        {"type": "table", "label": "Components",
         "columns": ["Type IDs", {"label": "PRR date", "month": True}, "Needed",
                     {"label": "Completed by", "month": True}, {"label": "Received", "date": True}],
         "rows": ["Rails and cables"]},
    ]}],
}


def _api(lst=LIST, plans=None, images=None):
    """A mocked client: the consortium type carries the list, each type in
    ``plans`` its plan (newest of two versions), everything by image id."""
    plans = {SIPM: PLAN} if plans is None else plans
    api = mock.MagicMock()
    files = {"l1": lst}
    listing = {PTID: [{"image_id": "l1", "image_name": f"Production_list_{PTID}.json",
                       "created": "2026-10-08T10:00:00", "comments": "first list"},
                      {"image_id": "org", "image_name": f"Checklist_{PTID}_Organizer.json",
                       "created": "2026-10-08T00:00:00"}]}
    for tid, p in plans.items():
        old = {**p, "needed_by": "2028-01", "updated_by": "hajime3", "updated": "2026-10-01"}
        files[f"p-{tid}-new"], files[f"p-{tid}-old"] = p, old
        listing[tid] = [{"image_id": f"p-{tid}-old", "image_name": f"Production_plan_{tid}.json",
                         "created": "2026-10-01T09:00:00", "comments": "initial"},
                        {"image_id": f"p-{tid}-new", "image_name": f"Production_plan_{tid}.json",
                         "created": "2026-10-08T10:00:00", "comments": "schedule moved"}]
    for tid, rows in (images or {}).items():
        listing[tid] = rows
    api.get_component_type_images.side_effect = lambda t: {"data": listing.get(t, [])}
    api.get_image_response.side_effect = lambda iid: mock.Mock(content=json.dumps(files[iid]).encode())
    api.post_component_type_image.return_value = {"status": "OK", "image_id": "new"}
    api.whoami.return_value = {"data": {"architect": True, "username": "chaoz"}}
    return api


def _mocked(api):
    return (mock.patch("explore.views.mint_for", return_value="bearer"),
            mock.patch("explore.views.FnalDbApiClient", return_value=api))


def _forget_role(client):
    """Drop the session-cached architect flag so the next request asks whoami again."""
    s = client.session
    for k in [k for k in s.keys() if k.startswith("hwdb_architect_")]:
        del s[k]
    s.save()


class ColumnKindsTest(TestCase):
    """The ``month`` and ``date`` column kinds of #199 stay (Chao)."""

    def test_month_and_date_columns(self):
        s = checklistforms.normalize(TABLE_SCHEMA, "x")
        self.assertNotIn("status", s)   # the status flag is gone (#200)
        f = s["sections"][0]["fields"][0]
        self.assertEqual(f["months"], ["PRR date", "Completed by"])
        self.assertEqual(f["dates"], ["Received"])
        self.assertFalse(f["to_spec"])   # nothing forces → Specs any more
        data = {"Table": {"Components": {"Rails and cables": {"PRR date": "2022-10", "Received": "2026-09-15"}}}}
        b = checklistforms.bind(s, {"DATA": data})["sections"][0]["fields"][0]
        prr, rec = b["trows"][0]["cells"][1], b["trows"][0]["cells"][4]
        self.assertTrue(prr["month"]); self.assertEqual(prr["value"], "2022-10")
        self.assertTrue(rec["date"]); self.assertNotIn("month", rec)
        from django.template.loader import render_to_string
        html = render_to_string("explore/_checklist_cell.html", {"c": rec, "f": b, "forloop": {"counter0": 4}})
        self.assertIn('<input type="date" name="f0-0-r0-c4" value="2026-09-15" placeholder="YYYY-MM-DD"', html)
        parsed = checklistforms.parse(s, {"f0-0-r0-c1": "2027-05", "f0-0-r0-c2": "1500", "f0-0-r0-c4": "2026-09-15"})
        self.assertEqual(parsed["Table"]["Components"]["Rails and cables"],
                         {"PRR date": "2027-05", "Needed": 1500, "Received": "2026-09-15"})

    def test_editor_has_no_status_checkbox(self):
        self.client.force_login(get_user_model().objects.create_user("e", "e@e.io", "pw"))
        m1, m2 = _mocked(_api())
        with m1, m2:
            html = self.client.get(f"/hw/dev/checklist-config/{PTID}/").content.decode()
        self.assertNotIn("f-status", html)
        self.assertIn('return typeof rw === "string" ? { label: rw } : rw;', html)   # bare-string rows still work


class RetiredChecklistTest(TestCase):
    """Chao 2026-10-08: a ``retired`` checklist stays in HWDB (type images are
    never deleted) but is left off item pages and choosers; the editor
    still lists it so it can come back."""

    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("r", "r@r.io", "pw"))

    def test_flag_listing_and_editor(self):
        self.assertTrue(checklistforms.normalize({"name": "x", "retired": True, "sections": []}, "x")["retired"])
        self.assertFalse(checklistforms.normalize({"name": "x", "sections": []}, "x")["retired"])
        api = _api(images={PTID: [
            {"image_id": "a", "image_name": f"Checklist_{PTID}_Old.json", "created": "2026-10-01T00:00:00",
             "comments": "Consortium checklist schema (Explorer editor)"},
            {"image_id": "b", "image_name": f"Checklist_{PTID}_Old.json", "created": "2026-10-08T00:00:00",
             "comments": "Consortium checklist schema (Explorer editor) [retired]"},
            {"image_id": "c", "image_name": f"Checklist_{PTID}_Live.json", "created": "2026-10-08T00:00:00",
             "comments": "Consortium checklist schema (Explorer editor)"}]})
        self.assertEqual([(r["name"], r["retired"]) for r in checklistforms.available(api, PTID)], [("Live", False), ("Old", True)])
        self.assertEqual([r["name"] for r in checklistforms.active(api, PTID)], ["Live"])
        m1, m2 = _mocked(api)
        with m1, m2:
            self.assertEqual(self.client.get(f"/hw/dev/checklist-names/{PTID}/").json(), {"checklists": ["Live"]})
            html = self.client.get(f"/hw/dev/checklist-config/{PTID}/").content.decode()
            self.assertIn('<input type="checkbox" id="f-retired"> hidden from item pages', html)
            self.assertIn('class="ec-retired" title="Retired — not shown on item pages">Old ✎</a>', html)
            self.assertIn(">Live ✎</a>", html)
            # saving a retired schema marks the HWDB comment so listings know without loading it
            self.client.post(f"/hw/dev/checklist-config/{PTID}/", {
                "cl_name": "Old", "config_json": json.dumps({"name": "Old", "test_type_name": "T", "retired": True, "sections": []})})
            self.assertEqual(api.post_component_type_image.call_args.kwargs["comments"], "Consortium checklist schema (Explorer editor) [retired]")
            self.client.post(f"/hw/dev/checklist-config/{PTID}/", {
                "cl_name": "Old", "config_json": json.dumps({"name": "Old", "test_type_name": "T", "sections": []})})
            self.assertEqual(api.post_component_type_image.call_args.kwargs["comments"], "Consortium checklist schema (Explorer editor)")


class EngineTest(TestCase):
    def test_normalize_plan_and_list(self):
        self.assertEqual(production.normalize_plan({"needed": "1,500", "completed_by": "2027-03-20", "needed_by": "bad",
                                                    "comment": " x ", "updated_by": "c"}),
                         {"needed": 1500, "completed_by": "2027-03", "needed_by": "", "comment": "x",
                          "updated_by": "c", "updated": ""})
        self.assertEqual(production.normalize_plan(None)["needed"], None)
        self.assertEqual(production.normalize_list({"rows": [SIPM.lower(), {"type": PDS, "label": " PDS "}, {"type": "nope"}, 3]}),
                         [{"type": SIPM, "label": ""}, {"type": PDS, "label": "PDS"}])
        self.assertEqual(production.months_between("2026-12", "2028-05"), 17)
        self.assertEqual(production.months_between("2027-03-20", "2029-01"), 22)
        self.assertEqual(production.month_label("2027-03"), "Mar 2027")

    def test_read_plan_and_list_take_the_newest_version(self):
        api = _api()
        plan, vs = production.read_plan(api, SIPM)
        self.assertEqual(plan["needed_by"], "2028-05")
        self.assertEqual([v["image_id"] for v in vs], [f"p-{SIPM}-new", f"p-{SIPM}-old"])
        self.assertEqual(production.plan_history(api, vs)[1]["plan"]["needed_by"], "2028-01")
        self.assertEqual(production.read_plan(api, PDS), (None, []))
        rows, lvs = production.read_list(api, PTID)
        self.assertEqual(rows, [{"type": SIPM, "label": "SiPM boards (6 SiPMs)"}, {"type": PDS, "label": ""}])
        self.assertEqual(lvs[0]["comments"], "first list")

    def test_table_and_summary(self):
        _node(SIPM, instance="dev", component_type_name="SiPM board")
        _node(PDS, instance="dev", component_type_name="PDS module")
        for i, st in enumerate(["available", "available", "rejected"]):
            HwdbComponentEvent.objects.create(instance="dev", part_type_id=SIPM, part_id=f"{SIPM}-{i}", status=st)
        rows = production.normalize_list(LIST)
        plans = {SIPM: production.normalize_plan(PLAN)}
        t = production.table(rows, plans, production.counts("dev", [SIPM, PDS]), production.names("dev", [SIPM, PDS]),
                             today=date(2027, 1, 15))
        self.assertEqual(t[0]["label"], "SiPM boards (6 SiPMs)")
        self.assertEqual(t[1]["label"], "PDS module")   # no label: the mirror's name
        self.assertEqual((t[0]["needed"], t[0]["n"], t[0]["by_status"]), ("48,000", "3", "2 available, 1 rejected"))
        self.assertEqual((t[0]["completed_by"], t[0]["completed_past"], t[0]["needed_by"], t[0]["needed_past"], t[0]["float"]),
                         ("Dec 2026", True, "May 2028", False, "17"))
        self.assertEqual((t[1]["has_plan"], t[1]["needed"], t[1]["n"], t[1]["float"]), (False, "", "0", ""))
        self.assertEqual(production.summary(rows, plans, today=date(2027, 1, 15)), {"n": 2, "needed_by": "2028-05", "due": 1})
        self.assertEqual(production.summary(rows, plans, today=date(2026, 6, 1))["due"], 0)

    def test_caches(self):
        production.cache_plan("dev", SIPM, production.normalize_plan(PLAN))
        production.cache_plan("dev", SIPM, {**production.normalize_plan(PLAN), "needed": 100})
        self.assertEqual(ProductionPlan.objects.get().needed, 100)   # one row per type
        self.assertEqual(production.cached_plans("dev", [SIPM])[SIPM]["updated_by"], "chaoz")
        production.cache_plan("dev", SIPM, None)
        self.assertFalse(ProductionPlan.objects.exists())
        production.cache_list("dev", PTID, production.normalize_list(LIST))
        production.cache_list("dev", PTID, [])
        self.assertEqual(ProductionList.objects.get().rows, [])
        production.cache_list("dev", PTID, None)
        self.assertFalse(ProductionList.objects.exists())

    def test_write_plan_posts_the_json_with_the_reason(self):
        api = _api()
        production.write_plan(api, SIPM, {**PLAN, "needed": 100}, "orders placed")
        (tid, fileobj, fname), kw = api.post_component_type_image.call_args.args, api.post_component_type_image.call_args.kwargs
        self.assertEqual((tid, fname, kw["comments"]), (SIPM, f"Production_plan_{SIPM}.json", "orders placed"))
        self.assertEqual(json.loads(fileobj.getvalue())["needed"], 100)
        production.write_list(api, PTID, [{"type": SIPM, "label": "x"}], "")
        a = api.post_component_type_image.call_args
        self.assertEqual((a.args[0], a.args[2], a.kwargs["comments"]), (PTID, f"Production_list_{PTID}.json", "Component list (Explorer)"))
        self.assertEqual(json.loads(a.args[1].getvalue()), {"rows": [{"type": SIPM, "label": "x"}]})


class StatusPageTest(TestCase):
    URL = f"/hw/dev/status/{PTID}/"

    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("s", "s@s.io", "pw"))
        _node(PTID, instance="dev", system_id=1, system_name="Sandbox", subsystem_id=6,
              subsystem_name="Test Production Status", component_type_name="Test Production Status",
              full_name="Z.Sandbox.Test Production Status.Test Production Status")
        _node(PDS, instance="dev", component_type_name="PDS module")
        for i in range(3):
            HwdbComponentEvent.objects.create(instance="dev", part_type_id=SIPM, part_id=f"{SIPM}-{i}", status="available")

    def test_generates_the_table_and_fills_the_caches(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            r = self.client.get(self.URL)
            html = r.content.decode()
        self.assertEqual(r.status_code, 200)
        self.assertIn("<h1>Test Production Status</h1>", html)
        self.assertIn('<table class="cl-table cl-gridlines ps-table">', html)   # the fill page's table look
        self.assertIn("<th>Component</th><th>Type ID</th><th>Needed</th><th>In HWDB</th><th>Completed by</th><th>Needed by</th><th>Float (months)</th><th>Comment</th>", html)
        self.assertIn(f'<th scope="row" class="cl-rowlab"><a href="/hw/dev/?node={SIPM}" title="the type’s page">SiPM boards (6 SiPMs)</a></th>', html)
        self.assertIn(f'{SIPM}<a class="ps-plan" href="/hw/dev/plan/{SIPM}/" title="The plan and its history — set 2026-10-08 by chaoz">plan</a>', html)
        self.assertIn('<td class="cl-const ps-num">48,000</td>', html)
        self.assertIn('<td class="cl-const ps-num" title="3 available">3</td>', html)
        self.assertIn('<td class="cl-const">May 2028</td>', html)
        self.assertIn('<td class="cl-const ps-num">17</td>', html)
        self.assertIn('<span class="clmd-green"><strong>Near completion</strong></span>', html)   # Markdown + colours
        self.assertIn("<li>HPK all tested</li>", html)
        # the type without a plan: its name, dashes, a "set plan" link for the architect
        self.assertIn('title="the type’s page">PDS module</a></th>', html)
        self.assertIn(f'<a class="ps-plan" href="/hw/dev/plan/{PDS}/" title="No plan on this type yet">set plan</a>', html)
        self.assertIn('<td class="cl-const ps-num ps-none">—</td>', html)
        self.assertIn('<td class="cl-const ps-num" title="no items in the mirror">0</td>', html)
        self.assertIn(f'href="/hw/dev/plan-list/{PTID}/?next=', html)   # ✎ Component list
        self.assertNotIn("ps-rev", html)   # no Submission picker: the history is per plan
        self.assertEqual(ProductionList.for_instance("dev").get(part_type_id=PTID).rows, production.normalize_list(LIST))
        self.assertEqual(ProductionPlan.for_instance("dev").get(part_type_id=SIPM).needed, 48000)
        self.assertFalse(ProductionPlan.for_instance("dev").filter(part_type_id=PDS).exists())
        # one listing per type read, one fetch per newest file
        self.assertEqual(api.get_component_type_images.call_count, 3)
        self.assertEqual(api.get_image_response.call_count, 2)

    def test_no_list_says_so_and_keeps_the_mark(self):
        ConsortiumTypeOverride.objects.create(instance="prod", part_type_id="D05700200099")
        api = _api(images={PTID: [], "D05700200099": []})
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(self.URL).content.decode()
            self.assertIn("No component list on this type yet — <a href=", html)
            self.assertIn("add the component types</a> it reports.", html)
            self.client.get("/hw/status/D05700200099/")
        self.assertFalse(ProductionList.objects.exists())
        self.assertTrue(ConsortiumTypeOverride.objects.exists())   # Chao: only the type page sets or unsets the mark
        api.whoami.return_value = {"data": {"architect": False}}
        _forget_role(self.client)
        with m1, m2:
            html = self.client.get(self.URL).content.decode()
        self.assertIn("No component list on this type yet.", html)   # no link for a non-architect


class PlanPageTest(TestCase):
    URL = f"/hw/dev/plan/{SIPM}/"

    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("p", "p@p.io", "pw"))
        _node(SIPM, instance="dev", component_type_name="SiPM board")

    def test_shows_the_plan_its_history_and_the_form(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(self.URL + "?next=/hw/dev/status/Z00100600001/").content.decode()
        self.assertIn("<h1>Production plan", html)
        self.assertIn('<input type="number" id="pl-needed" name="needed" min="0" step="1" value="48000"', html)
        self.assertIn('<input type="month" id="pl-done" name="completed_by" value="2026-12"', html)
        self.assertIn('<input type="month" id="pl-need" name="needed_by" value="2028-05"', html)
        self.assertIn("&lt;green&gt;**Near completion**&lt;/green&gt;", html)   # the comment, raw in the textarea
        self.assertIn('<input type="hidden" name="next" value="/hw/dev/status/Z00100600001/">', html)
        self.assertIn(f'<span class="mono">Production_plan_{SIPM}.json</span> on the type in HWDB · 2 versions · last set 2026-10-08 by chaoz', html)
        # the history: every version, newest first, with its values and the reason
        self.assertIn('<tr class="cur">\n      <td class="num">2</td>\n      <td style="white-space:nowrap;">2026-10-08 10:00</td>\n      <td>chaoz</td>\n      <td class="num">48000</td>\n      <td>2026-12</td>\n      <td>2028-05</td>', html)
        self.assertIn('<td class="num">1</td>\n      <td style="white-space:nowrap;">2026-10-01 09:00</td>\n      <td>hajime3</td>\n      <td class="num">48000</td>\n      <td>2026-12</td>\n      <td>2028-01</td>', html)
        self.assertIn('<td class="pl-dim">schedule moved</td>', html)
        self.assertIn('<td class="pl-dim">initial</td>', html)
        self.assertNotIn("banner-warn", html)
        # the type's HWDB roles gate the save, architect or not (dev 2026-10-08: "Not authorized")
        api.get_component_type.return_value = {"data": {"roles": [{"id": 34, "name": "SiPM_test"}]}}
        with mock.patch("explore.views._my_roles", return_value=[{"id": 9, "name": "builder"}]), m1, m2:
            html = self.client.get(self.URL).content.decode()
        self.assertIn("Saving onto this type needs one of its HWDB roles <b>SiPM_test</b>. Your account holds <b>builder</b>, so HWDB will refuse the save.", html)
        self.assertIn('<form method="post">', html)   # the form stays: HWDB has the last word

    def test_save_posts_a_version_caches_and_logs(self):
        from explore.models import ActivityEvent
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            r = self.client.post(self.URL, {"needed": "50,000", "completed_by": "2027-02", "needed_by": "2028-05",
                                            "comment": "orders placed", "reason": "FBK batch late",
                                            "next": "/hw/dev/status/Z00100600001/"})
            self.assertEqual(r["Location"], "/hw/dev/status/Z00100600001/")
        a = api.post_component_type_image.call_args
        self.assertEqual((a.args[0], a.args[2], a.kwargs["comments"]), (SIPM, f"Production_plan_{SIPM}.json", "FBK batch late"))
        body = json.loads(a.args[1].getvalue())
        self.assertEqual(body, {"needed": 50000, "completed_by": "2027-02", "needed_by": "2028-05", "comment": "orders placed",
                                "updated_by": body["updated_by"], "updated": timezone.localdate().isoformat()})
        p = ProductionPlan.for_instance("dev").get(part_type_id=SIPM)
        self.assertEqual((p.needed, p.completed_by, p.comment), (50000, "2027-02", "orders placed"))
        ev = ActivityEvent.objects.get(kind="curation")
        self.assertEqual(ev.summary, f"Production plan of {SIPM}: needed 48000 → 50000, completed by 2026-12 → 2027-02, comment — FBK batch late")
        with m1, m2:
            html = self.client.get(self.URL).content.decode()
        self.assertIn("Plan saved — version 3 of", html)

    def test_validation_and_gates(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            r = self.client.post(self.URL, {"needed": "ten", "completed_by": "2027-13-01"})
            html = self.client.get(r["Location"]).content.decode()
            self.assertIn("Needed must be a whole number.", html)
            self.assertIn("Completed by must be a month (YYYY-MM).", html)
            api.post_component_type_image.assert_not_called()
            # a blank form clears the plan (an empty version, the history keeps the old values)
            r = self.client.post(self.URL, {})
            self.assertEqual(json.loads(api.post_component_type_image.call_args.args[1].getvalue())["needed"], None)
            self.assertIsNone(ProductionPlan.for_instance("dev").get(part_type_id=SIPM).needed)
            # not an architect: the values and the history, no form, a POST refused
            api.whoami.return_value = {"data": {"architect": False}}
            _forget_role(self.client)
            html = self.client.get(self.URL).content.decode()
            self.assertNotIn('<form method="post">', html)
            self.assertIn("<dt>Needed</dt><dd>48000</dd>", html)
            self.assertIn("<h2", html)   # History
            self.assertEqual(self.client.post(self.URL, {"needed": "1"}).status_code, 403)
            # a type without a plan
            html = self.client.get(f"/hw/dev/plan/{PDS}/").content.decode()
            self.assertIn("No plan on this type yet.", html)
            self.assertNotIn("History", html.split("</style>")[1])
        # not a write instance: no form even for an architect
        api.whoami.return_value = {"data": {"architect": True}}
        _forget_role(self.client)
        with self.settings(HWDB_WRITE_INSTANCES=["prod"]), m1, m2:
            html = self.client.get(self.URL).content.decode()
        self.assertNotIn('<form method="post">', html)
        self.assertIn("<dt>Needed</dt>", html)


class ListPageTest(TestCase):
    URL = f"/hw/dev/plan-list/{PTID}/"

    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("l", "l@l.io", "pw"))
        _node(PTID, instance="dev", component_type_name="Test Production Status")
        _node(SIPM, instance="dev", component_type_name="SiPM board")

    def test_shows_and_saves_the_list(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(self.URL).content.decode()
            self.assertIn('<textarea class="pl-rows" name="rows" spellcheck="false" placeholder="', html)
            self.assertIn(f">{SIPM}  SiPM boards (6 SiPMs)\n{PDS}</textarea>", html)
            self.assertIn(f"Production_list_{PTID}.json</span> on the type in HWDB · 1 version · last saved 2026-10-08 10:00", html)
            api.get_component_type.return_value = {"data": {"roles": []}}
            with mock.patch("explore.views._my_roles", return_value=[{"id": 9, "name": "builder"}]):
                self.assertIn("This type lists no HWDB roles, so HWDB refuses every write onto it.", self.client.get(self.URL).content.decode())
            r = self.client.post(self.URL, {"rows": f"{PDS}  PDS modules\n\n{SIPM.lower()} SiPM boards\n", "reason": "reordered"})
            self.assertEqual(r["Location"], f"/hw/dev/status/{PTID}/")
        a = api.post_component_type_image.call_args
        self.assertEqual((a.args[0], a.args[2], a.kwargs["comments"]), (PTID, f"Production_list_{PTID}.json", "reordered"))
        self.assertEqual(json.loads(a.args[1].getvalue()), {"rows": [{"type": PDS, "label": "PDS modules"}, {"type": SIPM, "label": "SiPM boards"}]})
        self.assertEqual(ProductionList.for_instance("dev").get(part_type_id=PTID).rows[0]["type"], PDS)

    def test_bad_line_and_gates(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            r = self.client.post(self.URL, {"rows": f"{SIPM}\nSiPM boards without an id"})
            html = self.client.get(r["Location"]).content.decode()
            self.assertIn("Each line starts with a type id (a letter and 11 digits): SiPM boards without an id", html)
            api.post_component_type_image.assert_not_called()
            api.whoami.return_value = {"data": {"architect": False}}
            _forget_role(self.client)
            html = self.client.get(self.URL).content.decode()
            self.assertNotIn('<form method="post">', html)
            self.assertIn(f'<tr><td class="mono">{SIPM}</td><td>SiPM boards (6 SiPMs)</td><td class="">SiPM board</td></tr>', html)
            self.assertIn(f'<tr><td class="mono">{PDS}</td><td>—</td><td class="pl-dim">not in the mirror</td></tr>', html)
            self.assertEqual(self.client.post(self.URL, {"rows": SIPM}).status_code, 403)

    def test_saving_a_list_does_not_mark_the_type(self):
        # Chao 2026-10-08: the consortium mark (type page) shows the list link, not the other way round
        other = "D05700200099"
        _node(other, component_type_name="Other consortium")
        api = _api(images={other: [{"image_id": "l1", "image_name": f"Production_list_{other}.json", "created": "2026-10-08T11:00:00"}]})
        m1, m2 = _mocked(api)
        with m1, m2:
            r = self.client.post(f"/hw/plan-list/{other}/", {"rows": SIPM})
            html = self.client.get(r["Location"]).content.decode()   # the status page
        self.assertIn("Component list saved — 1 types.", html)
        self.assertIn("is not a consortium type — set it in the Category dropdown", html)
        self.assertFalse(ConsortiumTypeOverride.objects.exists())


class DetectorPagesTest(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("d", "d@d.io", "pw"))

    def test_detector_pages_link_each_other(self):
        html = self.client.get("/hw/dev/hierarchy/").content.decode()
        self.assertIn('<a class="hc-tab" aria-selected="true" href="/hw/dev/hierarchy/">Hierarchy chart</a>', html)
        self.assertIn('<a class="hc-tab" aria-selected="false" href="/hw/dev/status/">Production status</a>', html)
        self.assertNotIn("hc-cons", html)
        r = self.client.get("/hw/dev/hierarchy/?tab=status")   # the old tab link
        self.assertEqual(r["Location"], "/hw/dev/status/")

    def test_overview_draws_the_cached_tables(self):
        _node(PTID, instance="dev", system_id=1, system_name="Sandbox", subsystem_id=6,
              subsystem_name="x", component_type_name="Test Production Status",
              full_name="Z.Sandbox.x.Test Production Status")
        _node(SIPM, instance="dev", component_type_name="SiPM board")
        ConsortiumTypeOverride.objects.create(instance="dev", part_type_id=PTID)
        html = self.client.get("/hw/dev/status/").content.decode()
        self.assertIn('<a class="hc-tab" aria-selected="true" href="/hw/dev/status/">Production status</a>', html)
        self.assertIn(f'<a href="{navigation.leaf_path_for("dev", PTID)}" title="the consortium type’s page">Test Production Status</a>', html)   # Chao: the index names the type page
        self.assertIn('<td class="num">—</td>', html)   # not read yet: no numbers in the index
        self.assertIn(f'Not read yet — <a href="/hw/dev/status/{PTID}/">open its status page</a>', html)
        production.cache_list("dev", PTID, production.normalize_list(LIST))
        production.cache_plan("dev", SIPM, production.normalize_plan(PLAN))
        html = self.client.get("/hw/dev/status/").content.decode()
        self.assertNotIn("Not read yet", html)
        due = 1 if "2026-12" <= timezone.localdate().strftime("%Y-%m") else 0
        self.assertIn(f'<td class="num">2</td>\n        <td>2028-05</td>\n        <td class="num">{due}</td>', html)
        self.assertIn('<button type="button" class="hc-pill" role="tab" data-c="Z00100600001" aria-selected="true">Test Production Status</button>', html)
        self.assertIn('<div class="hc-cons" data-c="Z00100600001">', html)
        self.assertIn('title="the type’s page">SiPM boards (6 SiPMs)</a></th>', html)   # the cached table, no HWDB call
        self.assertIn('<td class="cl-const ps-num">48,000</td>', html)
        self.assertIn('<span class="hc-read">read ', html)
        self.assertIn('localStorage.setItem("hcCons", id)', html)
        production.cache_list("dev", PTID, [])
        html = self.client.get("/hw/dev/status/").content.decode()
        self.assertIn(f'No component list on this type yet — <a href="/hw/dev/plan-list/{PTID}/">add the component types</a>', html)

    def test_prod_overview_is_empty_for_now(self):
        html = self.client.get("/hw/status/").content.decode()
        self.assertIn("No consortium type yet", html)
        self.assertNotIn("hc-pill", html.split("<h1>")[1])


class TypePageTest(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("t", "t@t.io", "pw"))
        self.node = _node(SIPM, tests_synced_at=timezone.now(), n_tests=1)
        HwdbTestEvent.objects.create(part_type_id=SIPM, part_id="", test_type_name="t", created=timezone.now())
        HwdbComponentEvent.objects.create(part_type_id=SIPM, part_id="P1", created=timezone.now())
        self.url = navigation.leaf_path_for("prod", SIPM)

    def test_plan_line_and_dashboard_feed(self):
        html = self.client.get(self.url).content.decode()
        self.assertNotIn("data-plan-url", html)
        self.assertNotIn("<dt>Plan</dt>", html)   # no plan, not an architect: no line
        production.cache_plan("prod", SIPM, production.normalize_plan(PLAN))
        html = self.client.get(self.url).content.decode()
        self.assertIn('data-plan-total="48000" data-plan-done="2026-12" data-plan-need="2028-05" '
                      f'data-plan-url="/hw/plan/{SIPM}/"', html)
        self.assertIn("planFixed = true", html)
        self.assertIn("from the production plan", html)
        self.assertIn('<dt>Plan</dt><dd class="span">needed 48000<span class="sep">·</span>completed by 2026-12<span class="sep">·</span>needed by 2028-05\n', html)
        self.assertIn(f'<a href="/hw/plan/{SIPM}/?next=', html)
        self.assertIn('title="The plan and its history — last set 2026-10-08 by chaoz">History</a></dd>', html)
        with mock.patch("explore.views._is_architect", return_value=True):
            html = self.client.get(self.url).content.decode()
            self.assertIn('by chaoz">Edit</a></dd>', html)
            production.cache_plan("prod", SIPM, None)
            html = self.client.get(self.url).content.decode()
            self.assertIn(f'<dt>Plan</dt><dd class="span"><a href="/hw/plan/{SIPM}/?next=', html)
            self.assertIn(">Set plan</a></dd>", html)
            self.assertNotIn("data-plan-url", html)


class ConsortiumTypeTest(TestCase):
    """#199 round 3 (Chao): the Detector list comes from the consortium-type
    mark — curation.yaml's ``consortium_types`` plus overrides set from the
    type page or automatically by saving a component list (#200)."""

    OTHER = "D05700200099"

    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("c", "c@c.io", "pw"))
        self.node = _node(self.OTHER, component_type_name="Other consortium")
        self.leaf_url = navigation.leaf_path_for("prod", self.OTHER)

    def test_union_of_yaml_and_overrides(self):
        from explore import curation
        self.assertEqual(curation.consortium_types("dev"), [])   # the yaml lists none (Chao: the dev test type must be unsettable)
        self.assertEqual(curation.consortium_types("prod"), [])
        ConsortiumTypeOverride.objects.create(instance="prod", part_type_id=self.OTHER)
        ConsortiumTypeOverride.objects.create(instance="dev", part_type_id=PTID)
        self.assertEqual(curation.consortium_types("dev"), [PTID])
        self.assertEqual(curation.consortium_types("prod"), [self.OTHER])
        with mock.patch.object(curation, "_block", return_value={"consortium_types": [PTID, "d05700200099"]}):
            self.assertEqual(curation.consortium_types("dev"), [PTID, "D05700200099"])   # yaml first, no duplicate
        html = self.client.get("/hw/status/").content.decode()
        self.assertIn('<h2>Other consortium <span class="mono">D05700200099</span>', html)
        self.assertIn('<td class="num">—</td>', html)   # not read yet: no numbers in the index

    def test_type_page_class_dropdown(self):
        from explore.models import ActivityEvent, ShippingTypeOverride
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
            self.assertIn('<a href="/hw/plan-list/D05700200099/?next=', html)                         # … with the list
            # Chao 2026-10-08: a consortium type holds no items — no sync buttons, counts, item links, charts, plan
            self.assertNotIn('data-mode="incremental"', html)   # the sync buttons (the script that binds them stays)
            self.assertNotIn("<dt>Items in HWDB</dt>", html)
            self.assertNotIn("<dt>Plan</dt>", html)
            self.assertNotIn("ES config", html)
            self.assertNotIn("New item", html)
            self.assertIn("Edit checklists", html)
            self.assertIn('id="cl-names-dd"', html)   # the organizer checklists still open from here
            self.client.post(url, {"next": self.leaf_url, "class": "shipping"})   # switching clears the other mark
            self.assertFalse(ConsortiumTypeOverride.objects.exists())
            self.assertTrue(ShippingTypeOverride.objects.filter(instance="prod", part_type_id=self.OTHER).exists())
            self.client.post(url, {"next": self.leaf_url, "class": "none"})
            self.assertFalse(ShippingTypeOverride.objects.exists())
            self.assertEqual(self.client.post(url, {"next": self.leaf_url, "class": "x"}).status_code, 400)
            # yaml-curated: the dropdown is disabled, a POST is refused
            from explore import curation
            with mock.patch.object(curation, "_block", return_value={"consortium_types": [PTID]}):
                r = self.client.post(f"/hw/dev/type-class/{PTID}/", {"next": self.leaf_url, "class": "none"})
            html = self.client.get(r["Location"]).content.decode()   # (the patched block would hide the curated tree)
            self.assertIn("is curated in curation.yaml", html)
        self.assertEqual(ActivityEvent.objects.filter(kind="curation").count(), 4)   # +cons, −cons +ship, −ship
        with mock.patch("explore.views._is_architect", return_value=False):
            ConsortiumTypeOverride.objects.create(instance="prod", part_type_id=self.OTHER)
            html = self.client.get(self.leaf_url).content.decode()
            self.assertNotIn('<select name="class"', html)
            self.assertIn("<span class=\"sep\">·</span> consortium type</dd>", html)
            self.assertIn("<dt>Status</dt>", html)
            self.assertEqual(self.client.post(url, {"next": self.leaf_url, "class": "none"}).status_code, 403)

    def test_saving_a_checklist_no_longer_marks_the_type(self):
        api = _api(images={self.OTHER: []})
        m1, m2 = _mocked(api)
        with m1, m2:
            self.client.post(f"/hw/checklist-config/{self.OTHER}/", {
                "cl_name": "Plain", "config_json": json.dumps({"name": "P", "test_type_name": "T", "status": True, "sections": []})})
        self.assertFalse(ConsortiumTypeOverride.objects.exists())


class TextEditorTest(TestCase):
    """The cell text editor with its Markdown preview stays from #199 (Chao)."""

    def test_preview_renders_with_the_tables_filter(self):
        self.client.force_login(get_user_model().objects.create_user("t", "t@t.io", "pw"))
        r = self.client.post("/hw/dev/text-preview/", {"text": "**bold** <green>ok</green>\n\n- a"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content.decode(), '<p><strong>bold</strong> <span class="clmd-green">ok</span></p>\n<ul>\n<li>a</li>\n</ul>\n')
        self.assertEqual(self.client.get("/hw/dev/text-preview/").status_code, 405)
        self.client.logout()
        self.assertEqual(self.client.post("/hw/dev/text-preview/", {"text": "x"}).status_code, 302)

    def test_fill_page_dialog_and_cells(self):
        self.client.force_login(get_user_model().objects.create_user("u", "u@u.io", "pw"))
        from explore.tests.test_checklist_forms import PAGE, _api as _forms_api, _mocked as _forms_mocked
        api = _forms_api(); m1, m2 = _forms_mocked(api)
        with m1, m2:
            html = self.client.get(PAGE).content.decode()
        self.assertIn('<div class="cl-td-panes"><textarea></textarea><div class="cl-td-prev cl-md"></div></div>', html)
        self.assertIn('fetch("/hw/dev/text-preview/", { method: "POST"', html)
        self.assertNotIn(">Production status</a>", html)   # the fill page's status button is gone (#200)
        self.assertIn('closest(".cl-cell-expand")', html)   # the ✎ cell editor
