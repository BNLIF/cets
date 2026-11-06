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
    files = {"l1": lst, "org": {"name": "Organizer", "organizer": True, "sections": []},
             "wf": {"name": "Workflow", "organizer": True, "sections": []}, "plain": {"name": "Plain", "sections": []}}
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
                          "p6_completed_id": "", "p6_needed_id": "", "first_completed_by": "", "first_needed_by": "",
                          "p6_first_completed_id": "", "p6_first_needed_id": "", "updated_by": "c", "updated": ""})
        self.assertEqual(production.normalize_plan(None)["needed"], None)
        self.assertEqual(production.normalize_list({"rows": [SIPM.lower(), {"type": PDS, "label": " PDS "}, {"type": "nope"}, 3]}),
                         [{"type": SIPM, "label": "", "level": 0, "plan_of": ""}, {"type": PDS, "label": "PDS", "level": 0, "plan_of": ""}])
        self.assertEqual(production.months_between("2026-12", "2028-05"), 17)
        self.assertEqual(production.months_between("2027-03-20", "2029-01"), 22)
        self.assertEqual(production.month_label("2027-03"), "Mar 2027")

    def test_levels_and_lines(self):
        # #211: a level at most one under the row above; plan_of a well-formed type id; the text form both ways
        rows = production.normalize_list({"rows": [{"type": SIPM, "level": 3}, {"type": PDS, "level": "2", "plan_of": PTID.lower()},
                                                   {"type": SIPM, "level": 9}, {"type": PDS, "level": -1, "plan_of": "x"}]})
        self.assertEqual([(r["level"], r["plan_of"]) for r in rows], [(0, ""), (1, PTID), (2, ""), (0, "")])
        rows, bad = production.parse_lines(f"{SIPM}  SiPM boards\n\n    {PDS.lower()}@{PTID}  PDS modules\n\t{SIPM} x\nnope here\n {PDS}")
        self.assertEqual(rows, [{"type": SIPM, "label": "SiPM boards", "level": 0},
                                {"type": PDS, "label": "PDS modules", "level": 1, "plan_of": PTID},   # 4 spaces asks for 2, clamped to 1
                                {"type": SIPM, "label": "x", "level": 1},
                                {"type": PDS, "label": "", "level": 1}])   # one space rounds to a level
        self.assertEqual(bad, ["nope here"])
        self.assertEqual(production.to_lines(rows), f"{SIPM}  SiPM boards\n  {PDS}@{PTID}  PDS modules\n  {SIPM}  x\n  {PDS}")
        self.assertEqual(production.plan_key(rows[1]), f"{PDS}@{PTID}")

    def test_read_plan_and_list_take_the_newest_version(self):
        api = _api()
        plan, vs = production.read_plan(api, SIPM)
        self.assertEqual(plan["needed_by"], "2028-05")
        self.assertEqual([v["image_id"] for v in vs], [f"p-{SIPM}-new", f"p-{SIPM}-old"])
        self.assertEqual(production.plan_history(api, vs)[1]["plan"]["needed_by"], "2028-01")
        self.assertEqual(production.read_plan(api, PDS), (None, []))
        rows, lvs = production.read_list(api, PTID)
        self.assertEqual(rows, [{"type": SIPM, "label": "SiPM boards (6 SiPMs)", "level": 0, "plan_of": ""},
                                {"type": PDS, "label": "", "level": 0, "plan_of": ""}])
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
        self.assertEqual([(r["level"], r["has_children"], r["dep_warn"]) for r in t], [(0, False, ""), (0, False, "")])

    def test_tree_rows_plan_of_and_the_dependency_mark(self):
        # #211: CRP › FEMB › ASIC; the FEMB row shows another consortium's plan; a part finishing after its assembly is marked
        crp, femb, asic, other = "D08100400001", "D08100500001", "D08100100001", "Z00100600003"
        rows = [{"type": crp, "label": "Inst. CRP", "level": 0, "plan_of": ""},
                {"type": femb, "label": "", "level": 1, "plan_of": other},
                {"type": asic, "label": "LArASIC", "level": 2, "plan_of": ""},
                {"type": PDS, "label": "CRU", "level": 1, "plan_of": ""}]
        plans = {crp: production.normalize_plan({"needed": 160, "completed_by": "2027-08", "first_completed_by": "2027-01"}),
                 femb: production.normalize_plan({"needed": 1, "completed_by": "2029-01"}),   # the plain plan, not shown
                 f"{femb}@{other}": production.normalize_plan({"needed": 1920, "completed_by": "2027-06", "first_completed_by": "2027-03"}),
                 asic: production.normalize_plan({"needed": 4000, "completed_by": "2027-10-05"})}
        t = production.table(rows, plans, production.counts("dev", [crp, femb, asic, PDS]), {femb: "FEMB"}, today=date(2027, 1, 15))
        self.assertEqual([(r["label"], r["level"], r["has_children"], r["plan_of"]) for r in t],
                         [("Inst. CRP", 0, True, ""), ("FEMB", 1, True, other), ("LArASIC", 2, False, ""), ("CRU", 1, False, "")])
        self.assertEqual((t[1]["needed"], t[1]["completed_by"], t[1]["has_plan"]), ("1,920", "Jun 2027", True))
        self.assertEqual(t[1]["dep_warn"], "")   # Jun 2027 before the CRP's Aug 2027
        self.assertEqual(t[1]["first_dep_warn"], "First completed by Mar 2027 is after Inst. CRP’s Jan 2027")
        self.assertEqual(t[2]["dep_warn"], "Last completed by Oct 2027 is after FEMB’s Jun 2027")   # against its own parent, the FEMB
        self.assertEqual((t[3]["dep_warn"], t[3]["has_plan"]), ("", False))
        self.assertEqual(production.summary(rows, plans, today=date(2027, 1, 15)), {"n": 4, "needed_by": "", "due": 0})
        # the overview's cached plans by row: the plan_of consortium's over the plain
        production.cache_plan("dev", femb, plans[femb])
        production.cache_plan("dev", femb, plans[f"{femb}@{other}"], consortium=other)
        production.cache_plan("dev", crp, plans[crp])
        rp = production.row_plans("dev", rows, PTID)
        self.assertEqual((rp[femb]["needed"], rp[f"{femb}@{other}"]["needed"], rp[crp]["needed"]), (1, 1920, 160))
        # the optional column: no comment anywhere
        self.assertEqual(production.columns(t), {"comment": False, "ticks": production.TICKS[:-1]})
        self.assertEqual(production.columns([]), {"comment": False, "ticks": production.TICKS[:-1]})
        # a table whose row shows another's plan does not share the type (Chao 2026-11-04: the type page keeps its two plans)
        production.cache_list("dev", PTID, rows)
        production.cache_list("dev", other, [{"type": femb, "label": "", "level": 0, "plan_of": ""}])
        production.cache_list("dev", "Z00100600002", [{"type": femb, "label": "", "level": 0, "plan_of": ""}])
        self.assertEqual(production.shared_by("dev", femb), ["Z00100600002", other])
        self.assertEqual(production.shared_by("dev", crp), [PTID])

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
        self.assertIn(f'<table class="cl-table cl-gridlines ps-table" data-table="{PTID}">', html)   # the fill page's table look
        self.assertIn('<th>Component</th><th data-col="type">Type ID</th><th data-col="needed">Needed</th><th data-col="n">In HWDB</th><th data-col="fdone">First completed by</th><th data-col="fneed">First needed by</th><th data-col="done">Last completed by</th><th data-col="need">Last needed by</th><th data-col="float">Float (months)</th><th data-col="comment">Comment</th></tr>', html)
        self.assertNotIn('class="ps-fold-btn"', html)   # a flat list: no fold controls, no toggles
        self.assertNotIn('class="ps-tog', html)
        self.assertIn(f'<tr data-level="0" data-t="{SIPM}">\n    <th scope="row" class="cl-rowlab"><a href="/hw/dev/?node={SIPM}" title="the type’s page">SiPM boards (6 SiPMs)</a>'
                      f'<a class="ps-plan" href="/hw/dev/plan/{SIPM}/?for={PTID}" title="Edit the plan — set 2026-10-08 by chaoz">&#9998;</a></th>', html)   # Chao 2026-10-27: a pencil by the name, the Type ID cell bare
        self.assertIn(f'<td data-col="type" class="cl-const ps-types">{SIPM}</td>', html)
        self.assertIn('<td data-col="needed" class="cl-const ps-num">48,000</td>', html)
        self.assertIn('<td data-col="n" class="cl-const ps-num" title="3 available">3</td>', html)
        self.assertIn('<td data-col="need" class="cl-const">May 2028</td>', html)
        self.assertIn('<td data-col="float" class="cl-const ps-num">17</td>', html)
        self.assertIn('<span class="clmd-green"><strong>Near completion</strong></span>', html)   # Markdown + colours
        self.assertIn("<li>HPK all tested</li>", html)
        # the type without a plan: its name, dashes, a "set plan" link for the architect
        self.assertIn('title="the type’s page">PDS module</a><a class="ps-plan"', html)
        self.assertIn(f'<a class="ps-plan" href="/hw/dev/plan/{PDS}/?for={PTID}" title="No plan on this type yet — set one">&#9998;</a>', html)
        self.assertIn('<td data-col="needed" class="cl-const ps-num ps-none">—</td>', html)
        self.assertIn('<td data-col="n" class="cl-const ps-num" title="no items in the mirror">0</td>', html)
        self.assertIn(f'href="/hw/dev/plan-list/{PTID}/?next=', html)   # ✎ Component list
        self.assertIn(f'<a class="es-btn quiet" style="margin-left:auto; text-decoration:none;" href="/hw/dev/status/{PTID}/links/"', html)   # #213
        self.assertNotIn("ps-rev", html)   # no Submission picker: the history is per plan
        self.assertEqual(ProductionList.for_instance("dev").get(part_type_id=PTID).rows, production.normalize_list(LIST))
        self.assertEqual(ProductionPlan.for_instance("dev").get(part_type_id=SIPM).needed, 48000)
        self.assertFalse(ProductionPlan.for_instance("dev").filter(part_type_id=PDS).exists())
        # one listing per type read, one fetch per newest file
        self.assertEqual(api.get_component_type_images.call_count, 3)
        self.assertEqual(api.get_image_response.call_count, 2)

    def test_tree_and_plan_of(self):
        # #211: nested rows fold, a row reads the named consortium's plan
        other = "Z00100600003"
        lst = {"rows": [{"type": PDS, "label": "PDS modules", "level": 0}, {"type": SIPM, "level": 1, "plan_of": other}]}
        api = _api(lst=lst, plans={SIPM: PLAN})
        api.get_component_type_images.side_effect = None
        files = {"l1": lst, "p-plain": PLAN, "p-other": {**PLAN, "needed": 7, "completed_by": "2029-06"}}
        listing = {PTID: [{"image_id": "l1", "image_name": f"Production_list_{PTID}.json", "created": "2026-10-08T10:00:00"}],
                   SIPM: [{"image_id": "p-plain", "image_name": f"Production_plan_{SIPM}.json", "created": "2026-10-08T10:00:00"},
                          {"image_id": "p-other", "image_name": f"Production_plan_{SIPM}_{other}.json", "created": "2026-10-09T10:00:00"},
                          {"image_id": "c1", "image_name": f"Checklist_{SIPM}_QC.json", "created": "2026-10-01T00:00:00"},
                          {"image_id": "c2", "image_name": f"Checklist_{SIPM}_Old.json", "created": "2026-10-01T00:00:00", "comments": "[retired]"}],
                   PDS: [{"image_id": "c3", "image_name": f"Checklist_{PDS}_Receiving.json", "created": "2026-10-01T00:00:00"}]}
        api.get_component_type_images.side_effect = lambda t: {"data": listing.get(t, [])}
        api.get_image_response.side_effect = lambda iid: mock.Mock(content=json.dumps(files[iid]).encode())
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(self.URL).content.decode()
        self.assertIn('<div class="ps-bar"><button type="button" class="ps-fold-btn" data-fold="open">Expand all</button>', html)
        self.assertIn('<span class="ps-cols" title="Columns to show — remembered in this browser"><label><input type="checkbox" data-col="type" autocomplete="off"> Type ID</label><label><input type="checkbox" data-col="needed" autocomplete="off" checked> Needed</label>', html)
        self.assertIn('<th data-col="float">Float (months)</th><th data-col="comment">Comment</th></tr>', html)
        self.assertIn('localStorage.setItem("psCols:" + tableOf(bar).dataset.table', html)
        self.assertIn(f'<tr data-level="0" data-t="{PDS}">\n    <th scope="row" class="cl-rowlab"><button type="button" class="ps-tog" aria-expanded="true" title="Fold its rows"></button><a href="/hw/dev/?node={PDS}"', html)
        self.assertIn(f'<tr data-level="1" data-t="{SIPM}">\n    <th scope="row" class="cl-rowlab" style="padding-left:18px;"><span class="ps-tog ps-tog-none"></span><a href="/hw/dev/?node={SIPM}"', html)
        self.assertIn(f'<a class="ps-plan" href="/hw/dev/plan/{SIPM}/?for={other}" title="Edit the plan — set 2026-10-08 by chaoz ({other}’s)">', html)
        self.assertIn('<td data-col="needed" class="cl-const ps-num">7</td>', html)   # the other consortium's plan, not the plain one
        self.assertIn('<td data-col="done" class="cl-const">Jun 2029</td>', html)
        self.assertIn('<th data-col="float">Float (months)</th><th data-col="comment">Comment</th></tr>', html)
        self.assertIn('localStorage.setItem("psFold:" + tbl.dataset.table', html)
        cached = ProductionList.for_instance("dev").get(part_type_id=PTID).rows
        self.assertEqual([(r["level"], r["plan_of"]) for r in cached], [(0, ""), (1, other)])
        self.assertEqual(ProductionPlan.for_instance("dev").get(part_type_id=SIPM, consortium=other).needed, 7)
        self.assertEqual(ProductionPlan.for_instance("dev").get(part_type_id=SIPM, consortium="").needed, 48000)
        # the overview draws the same tree from the caches
        ConsortiumTypeOverride.objects.create(instance="dev", part_type_id=PTID)
        html = self.client.get("/hw/dev/status/").content.decode()
        self.assertIn('data-fold="close">Collapse all</button>', html)
        self.assertIn('<td data-col="needed" class="cl-const ps-num">7</td>', html)

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
        with self.settings(HWDB_WRITE_INSTANCES=["prod"]), m1, m2:
            html = self.client.get(self.URL).content.decode()
        self.assertIn("No component list on this type yet.", html)   # a read-only instance: no link


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
        self.assertIn('<tr class="cur">\n      <td class="num">2</td>\n      <td style="white-space:nowrap;">2026-10-08 10:00</td>\n      <td>chaoz</td>\n      <td class="num">48000</td>\n      <td>—</td>\n      <td>—</td>\n      <td>2026-12</td>\n      <td>2028-05</td>', html)
        self.assertIn('<td class="num">1</td>\n      <td style="white-space:nowrap;">2026-10-01 09:00</td>\n      <td>hajime3</td>\n      <td class="num">48000</td>\n      <td>—</td>\n      <td>—</td>\n      <td>2026-12</td>\n      <td>2028-01</td>', html)
        self.assertIn('<td class="pl-dim">schedule moved</td>', html)
        self.assertIn('<td class="pl-dim">initial</td>', html)
        self.assertNotIn("banner-warn", html)
        # the type's HWDB roles gate the edit, flags or not (dev 2026-10-08: "Not authorized"; Chao 2026-10-09: no architect gate)
        api.get_component_type.return_value = {"data": {"roles": [{"id": 34, "name": "SiPM_test"}]}}
        with mock.patch("explore.views._my_roles", return_value=[{"id": 9, "name": "builder"}]), m1, m2:
            html = self.client.get(self.URL).content.decode()
            self.assertEqual(self.client.post(self.URL, {"needed": "1"}).status_code, 403)
        self.assertIn("Saving onto this type needs one of its HWDB roles <b>SiPM_test</b>. Your account holds <b>builder</b>, so the plan cannot be edited here.", html)
        self.assertNotIn('<form method="post">', html)
        self.assertIn("<dt>Needed</dt><dd>48000</dd>", html)   # the values and the history stay readable

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
                                "p6_completed_id": "", "p6_needed_id": "", "first_completed_by": "", "first_needed_by": "",
                                "p6_first_completed_id": "", "p6_first_needed_id": "",
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
            self.assertIn("Last completed by must be a month (YYYY-MM).", html)
            api.post_component_type_image.assert_not_called()
            # a blank form clears the plan (an empty version, the history keeps the old values)
            r = self.client.post(self.URL, {})
            self.assertEqual(json.loads(api.post_component_type_image.call_args.args[1].getvalue())["needed"], None)
            self.assertIsNone(ProductionPlan.for_instance("dev").get(part_type_id=SIPM).needed)
            # a type without a plan
            html = self.client.get(f"/hw/dev/plan/{PDS}/").content.decode()
            self.assertIn('<form method="post">', html)   # roles unreadable in the mock = no gate; HWDB has the last word
            self.assertIn('name="needed" min="0" step="1" value=""', html)
            self.assertNotIn("History", html.split("</style>")[1])
            self.assertIn(f"Production_plan_{PDS}.json</span> on the type in HWDB</p>", html)   # no versions yet
        # not a write instance: no form, no roles asked
        with self.settings(HWDB_WRITE_INSTANCES=["prod"]), m1, m2:
            html = self.client.get(self.URL).content.decode()
        self.assertNotIn('<form method="post">', html)
        self.assertIn("<dt>Needed</dt>", html)
        self.assertIn("<h2", html)   # History


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
            self.assertIn('<textarea class="pl-rows" name="rows" id="pl-rows" spellcheck="false" hidden placeholder="', html)
            self.assertIn(f">{SIPM}  SiPM boards (6 SiPMs)\n{PDS}</textarea>", html)
            self.assertIn(f"Production_list_{PTID}.json</span> on the type in HWDB · 1 version · last saved 2026-10-08 10:00", html)
            # #211: the row editor's data — the rows with their mirror names, the other tables (for "whose plan"), the endpoints
            self.assertIn('<script id="pl-data" type="application/json">', html)
            data = json.loads(html.split('<script id="pl-data" type="application/json">')[1].split("</script>")[0])
            self.assertEqual(data["rows"][0], {"type": SIPM, "label": "SiPM boards (6 SiPMs)", "level": 0, "plan_of": "", "name": "SiPM board"})
            self.assertEqual((data["tables"], data["search"], data["positions"], data["summary"]),
                             ([], "/hw/dev/search/api/", "/hw/dev/type-positions/X00000000000/", "/hw/dev/hierarchy/summary/"))
            self.assertIn('<button type="button" class="pl-ib pl-mode" id="pl-text">Text</button>', html)
            self.assertIn('data-do="sub" title="Add the types its positions take, under it">+ sub-components</button>', html)
            r = self.client.post(self.URL, {"rows": f"{PDS}  PDS modules\n\n  {SIPM.lower()}@Z00100600003 SiPM boards\n", "reason": "reordered"})
            self.assertEqual(r["Location"], f"/hw/dev/status/{PTID}/")
        a = api.post_component_type_image.call_args
        self.assertEqual((a.args[0], a.args[2], a.kwargs["comments"]), (PTID, f"Production_list_{PTID}.json", "reordered"))
        self.assertEqual(json.loads(a.args[1].getvalue()), {"rows": [{"type": PDS, "label": "PDS modules", "level": 0},
                                                                     {"type": SIPM, "label": "SiPM boards", "level": 1, "plan_of": "Z00100600003"}]})
        self.assertEqual(ProductionList.for_instance("dev").get(part_type_id=PTID).rows[0]["type"], PDS)

    def test_editor_lists_the_other_tables(self):
        # #211: a row may show another table's plan of its type — the editor is told which tables list each type
        production.cache_list("dev", "Z00100600003", [{"type": SIPM, "label": "", "level": 0, "plan_of": ""}])
        _node("Z00100600003", instance="dev", component_type_name="FDVD CE")
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(self.URL).content.decode()
        data = json.loads(html.split('<script id="pl-data" type="application/json">')[1].split("</script>")[0])
        self.assertEqual(data["tables"], [{"id": "Z00100600003", "name": "FDVD CE", "types": [SIPM]}])

    def test_bad_line_and_gates(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            r = self.client.post(self.URL, {"rows": f"{SIPM}\nSiPM boards without an id"})
            html = self.client.get(r["Location"]).content.decode()
            self.assertIn("Each line starts with a type id (a letter and 11 digits): SiPM boards without an id", html)
            api.post_component_type_image.assert_not_called()
            api.get_component_type.return_value = {"data": {"roles": []}}   # a role-less consortium type: nobody may write
            with mock.patch("explore.views._my_roles", return_value=[{"id": 9, "name": "builder"}]):
                html = self.client.get(self.URL).content.decode()
                self.assertEqual(self.client.post(self.URL, {"rows": SIPM}).status_code, 403)
            self.assertIn("This type lists no HWDB roles, so HWDB refuses every write onto it.", html)
            self.assertNotIn('<form method="post">', html)
            self.assertIn(f'<tr><td class="mono">{SIPM}</td><td>SiPM boards (6 SiPMs)</td><td class="">SiPM board</td><td class="mono"></td></tr>', html)
            self.assertIn(f'<tr><td class="mono">{PDS}</td><td>—</td><td class="pl-dim">not in the mirror</td><td class="mono"></td></tr>', html)

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
        self.assertIn('<a class="hc-tab" aria-selected="false" href="/hw/dev/schedule/">P6 schedule</a>', html)
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
        self.assertIn(f'<a href="{navigation.leaf_path_for("dev", PTID)}" title="the table’s type page">Test Production Status</a>', html)   # Chao: the index names the type page
        self.assertIn('<td class="num">—</td>', html)   # not read yet: no numbers in the index
        self.assertIn(f'Not read yet — <a href="/hw/dev/status/{PTID}/">open its status page</a>', html)
        production.cache_list("dev", PTID, production.normalize_list(LIST))
        production.cache_plan("dev", SIPM, production.normalize_plan(PLAN))
        html = self.client.get("/hw/dev/status/").content.decode()
        self.assertNotIn("Not read yet", html)
        due = 1 if "2026-12" <= timezone.localdate().strftime("%Y-%m") else 0
        self.assertIn(f'<td class="num">2</td>\n        <td>2028-05</td>\n        <td class="num">{due}</td>', html)
        self.assertIn('<a class="hc-pill" role="tab" href="?c=Z00100600001" data-c="Z00100600001" data-d="other" aria-selected="true">Test Production Status</a>', html)
        self.assertIn('<div class="hc-cons" data-c="Z00100600001">', html)
        self.assertIn('title="the type’s page">SiPM boards (6 SiPMs)</a><a class="ps-plan"', html)   # the cached table, no HWDB call
        self.assertIn('<td data-col="needed" class="cl-const ps-num">48,000</td>', html)
        self.assertIn(f'<a class="ps-plan" href="/hw/dev/plan/{PDS}/?for={PTID}" title="No plan on this type yet — set one">&#9998;</a>', html)   # Chao 2026-11-04: a ✎ on a row without a plan, here too
        self.assertIn('<span class="hc-read">read ', html)
        self.assertIn(f'<a class="hc-cons-open" href="/hw/dev/plan-list/{PTID}/?next=/hw/dev/status/%3Fc%3D{PTID}" title="The rows of this table — the component types, nested">&#9998; Edit table</a>', html)   # Chao 2026-11-04: not "Refresh"
        self.assertIn(f'<a class="hc-cons-open" href="/hw/dev/status/{PTID}/links/" title="The component list as a table of links — each type’s page, checklists and executive summaries">Related links</a>', html)   # Chao 2026-11-06
        self.assertIn('localStorage.setItem("hcCons", id)', html)
        production.cache_list("dev", PTID, [])
        html = self.client.get("/hw/dev/status/").content.decode()
        self.assertIn(f'No component list on this type yet — <a href="/hw/dev/plan-list/{PTID}/">add the component types</a>', html)

    def test_overview_hd_vd_sub_tabs(self):
        # Chao 2026-10-22: trackers grouped by detector off their hierarchy path, sub-tabs only when they span more than one
        for f, want in (("Z.Sandbox.Test Production Status.FDHD CE", "HD"), ("D.FD-VD PDS.x.VD PDS tracker", "VD"),
                        ("D.FD2-VD Top CRP.x.y", "VD"), ("D.FD1-HD TPC_Elec. and FD2-VD Bottom_Elec..FEMB.z", ""),
                        ("Z.Sandbox.Test Production Status.Test Production Status", ""), ("D.HVD.x", ""), ("", "")):
            self.assertEqual(production.detector_of(f), want, f)
        _node(PTID, instance="dev", component_type_name="FDHD PDS", full_name="Z.Sandbox.Test Production Status.FDHD PDS")
        ConsortiumTypeOverride.objects.create(instance="dev", part_type_id=PTID)
        html = self.client.get("/hw/dev/status/").content.decode()
        self.assertNotIn('<div class="hc-sub"', html)   # one detector: no sub-tabs
        self.assertIn(f'<tr data-d="HD"><td><a href="{navigation.leaf_path_for("dev", PTID)}"', html)
        _node("Z00100600003", instance="dev", component_type_name="FDVD CE", full_name="Z.Sandbox.Test Production Status.FDVD CE")
        ConsortiumTypeOverride.objects.create(instance="dev", part_type_id="Z00100600003")
        _node("Z00100600004", instance="dev", component_type_name="Common", full_name="Z.Sandbox.Test Production Status.Common")
        ConsortiumTypeOverride.objects.create(instance="dev", part_type_id="Z00100600004")
        html = self.client.get("/hw/dev/status/").content.decode()
        self.assertIn('<div class="hc-sub" role="tablist"><a role="tab" href="?d=HD" data-d="HD" aria-selected="true">HD</a>'
                      '<a role="tab" href="?d=VD" data-d="VD" aria-selected="false">VD</a>'
                      '<a role="tab" href="?d=other" data-d="other" aria-selected="false">Other</a></div>', html)
        self.assertIn('href="?c=Z00100600003" data-c="Z00100600003" data-d="VD"', html)
        self.assertIn('href="?c=Z00100600004" data-c="Z00100600004" data-d="other"', html)
        self.assertIn('history.replaceState(null, "", location.pathname + "?" + p.toString())', html)
        self.assertIn('localStorage.setItem("hcDet", d)', html)

    def test_prod_overview_is_empty_for_now(self):
        html = self.client.get("/hw/status/").content.decode()
        self.assertIn("No consortium type yet", html)
        self.assertNotIn("hc-pill", html.split("<h1>")[1])


class OrganizerPageTest(TestCase):
    """#213: the list as a generated organizer — a Markdown table — and the hand-off to the editor as a draft."""
    URL = f"/hw/dev/status/{PTID}/links/"
    LIST3 = {"rows": [{"type": SIPM, "label": "SiPM boards", "level": 0}, {"type": PDS, "level": 1},
                      {"type": SIPM, "label": "Deep", "level": 2}, {"type": PDS, "label": "Deeper", "level": 3}]}

    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("o", "o@o.io", "pw"))
        _node(PTID, instance="dev", component_type_name="FDVD CRP")
        _node(SIPM, instance="dev", component_type_name="SiPM board")
        _node(PDS, instance="dev", component_type_name="PDS module")

    OWN = [{"image_id": "l1", "image_name": f"Production_list_{PTID}.json", "created": "2026-10-08T10:00:00"}]

    def _api(self, lst=LIST3, own=None):
        api = _api(lst=lst, plans={}, images={
            **({PTID: own} if own is not None else {}),
            SIPM: [{"image_id": "c1", "image_name": f"Checklist_{SIPM}_QC.json", "created": "2026-10-01T00:00:00"},
                   {"image_id": "c4", "image_name": f"Checklist_{SIPM}_Burn-in.json", "created": "2026-10-01T00:00:00"},
                   {"image_id": "c2", "image_name": f"Checklist_{SIPM}_Old.json", "created": "2026-10-01T00:00:00", "comments": "[retired]"}],
            PDS: [{"image_id": "c3", "image_name": f"Checklist_{PDS}_Receiving.json", "created": "2026-10-01T00:00:00"}]})
        return api

    def test_markdown_table(self):
        rows = production.normalize_list(self.LIST3)
        md = production.organizer_markdown(rows, {PDS: "PDS module"}, {SIPM: ["QC", "Burn-in"]},
                                           lambda t: f"/t/{t}", lambda t: f"/es/{t}", lambda t, c: f"/c/{t}/{c}")
        self.assertEqual(md.splitlines(), [
            "| Component | Type ID | Checklists | Exec summaries |", "|---|---|---|---|",
            f"| **SiPM boards** | [`{SIPM}`](/t/{SIPM}) | [QC](/c/{SIPM}/QC) | [all items](/es/{SIPM}) |",
            f"| | | [Burn-in](/c/{SIPM}/Burn-in) | |",   # a checklist per line: its own row under the component
            f"| &nbsp;&nbsp;&nbsp;&nbsp;↳ **PDS module** | [`{PDS}`](/t/{PDS}) | — | [all items](/es/{PDS}) |",
            f"| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;↳ **Deep** | [`{SIPM}`](/t/{SIPM}) | [QC](/c/{SIPM}/QC) | [all items](/es/{SIPM}) |",
            f"| | | [Burn-in](/c/{SIPM}/Burn-in) | |",
            f"| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;↳ **Deeper** | [`{PDS}`](/t/{PDS}) | — | [all items](/es/{PDS}) |"])
        self.assertEqual(production.organizer_draft("x"), {"name": "Organizer", "organizer": True, "sections": [
            {"title": "Components", "fields": [{"type": "static", "label": "", "note": "x"}]}]})

    def test_page_renders_the_table(self):
        api = self._api()
        m1, m2 = _mocked(api)
        with m1, m2:
            r = self.client.get(self.URL)
            html = r.content.decode()
        self.assertEqual(r.status_code, 200)
        self.assertTemplateUsed(r, "explore/production_organizer.html")
        self.assertIn("<h1>Links <span", html)
        self.assertIn('id="links-copy"', html)   # Copy Markdown, for an organizer already saved
        # the fixture's Organizer exists: the hand-off hides (it would supersede the edited one), its editor link shows
        self.assertNotIn("Edit as organizer checklist", html)
        self.assertIn(f'href="/hw/dev/checklist-config/{PTID}/?name=Organizer&amp;next=%2Fhw%2Fdev%2Fstatus%2F{PTID}%2Flinks%2F" title="Open this organizer checklist in the editor — paste the copied Markdown over its note">&#9998; Edit Organizer</a>', html)
        self.assertIn(f'The organizer checklist <a href="/hw/dev/checklist/{PTID}/Organizer/">Organizer</a> does not follow the list — paste the copied Markdown over the note in the editor.', html)
        self.assertIn('data-title="Components"', html)   # drawn as the organizer it becomes: one section, the table as a static note
        self.assertIn('<div class="cl-note cl-md"><table>', html)
        self.assertIn("<th>Component</th>\n<th>Type ID</th>\n<th>Checklists</th>\n<th>Exec summaries</th>", html)
        self.assertIn("<td><strong>SiPM boards</strong></td>", html)
        self.assertIn("↳ <strong>PDS module</strong></td>", html)   # no label: the mirror's name; indented
        self.assertIn(f'<td><a href="/hw/dev/?node={SIPM}" target="_blank" rel="noopener"><code>{SIPM}</code></a></td>', html)
        self.assertIn(f'<td><a href="/hw/dev/checklist/{SIPM}/Burn-in/" target="_blank" rel="noopener">Burn-in</a></td>', html)   # the retired one left out
        self.assertNotIn("Old", html.split('id="cl-org"')[1])
        self.assertIn(f'<td><a href="/hw/dev/checklist/{PDS}/Receiving/" target="_blank" rel="noopener">Receiving</a></td>', html)
        self.assertIn(f'<td><a href="/hw/dev/exec-summary/{SIPM}/" target="_blank" rel="noopener">all items</a></td>', html)
        self.assertIn(f'<td><a href="/hw/dev/exec-summary/{PDS}/" target="_blank" rel="noopener">all items</a></td>', html)
        self.assertNotIn("Submit to HWDB", html)
        self.assertEqual(api.get_component_type_images.call_count, 3)   # the type's own listing, one per distinct listed type
        self.assertEqual(api.get_image_response.call_count, 2)   # the list and the type's own checklist (for the organizer flag); none of the listed types' checklists

    def test_organizers_by_flag_not_name(self):
        # a renamed organizer still counts, a plain checklist on the type does not; with none the hand-off shows
        api = self._api(own=self.OWN + [
            {"image_id": "wf", "image_name": f"Checklist_{PTID}_Workflow.json", "created": "2026-10-08T00:00:00"},
            {"image_id": "plain", "image_name": f"Checklist_{PTID}_Plain.json", "created": "2026-10-08T00:00:00"}])
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(self.URL).content.decode()
        self.assertNotIn("Edit as organizer checklist", html)
        self.assertIn("&#9998; Edit Workflow</a>", html)
        self.assertNotIn("Edit Plain", html)
        self.assertIn(f'The organizer checklist <a href="/hw/dev/checklist/{PTID}/Workflow/">Workflow</a> does not follow the list', html)
        api = self._api(own=self.OWN)
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(self.URL).content.decode()
        self.assertIn('<button type="submit" class="es-btn quiet" title="Open the checklist editor with this table as an unsaved draft — nothing is saved until Save to HWDB">&#9998; Edit as organizer checklist</button>', html)
        self.assertNotIn("does not follow the list", html)

    def test_no_list_and_read_only(self):
        api = self._api(lst={"rows": []})
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(self.URL).content.decode()
            self.assertIn("No component list on this type yet — <a href=", html)
            self.assertNotIn("Edit as organizer checklist", html)
            with self.settings(HWDB_WRITE_INSTANCES=["prod"]):
                self.assertEqual(self.client.post(self.URL).status_code, 403)

    def test_draft_goes_to_the_editor_unsaved(self):
        api = self._api()
        m1, m2 = _mocked(api)
        with m1, m2:
            r = self.client.post(self.URL)
            self.assertEqual(r["Location"], f"/hw/dev/checklist-config/{PTID}/?name=Organizer&draft=1&next=%2Fhw%2Fdev%2Fstatus%2F{PTID}%2Flinks%2F")
            api.post_component_type_image.assert_not_called()   # nothing written
            draft = self.client.session[f"cl_draft:{PTID}"]
            self.assertEqual((draft["name"], draft["organizer"], draft["sections"][0]["title"]), ("Organizer", True, "Components"))
            self.assertTrue(draft["sections"][0]["fields"][0]["note"].startswith("| Component | Type ID | Checklists | Exec summaries |"))
            html = self.client.get(r["Location"]).content.decode()
        initial = json.loads(html.split('<script id="clc-initial" type="application/json">')[1].split("</script>")[0])
        self.assertEqual(initial, draft)   # the editor opens on the draft, not the stored Organizer
        self.assertIn('<input id="f-name" value="Organizer"', html)
        self.assertIn(f"A draft generated from the component list — nothing is saved until Save to HWDB, which adds a version of Checklist_{PTID}_Organizer.json.", html)
        api.post_component_type_image.assert_not_called()
        # without ?draft=1 the editor shows the stored schema as before
        with m1, m2:
            html = self.client.get(f"/hw/dev/checklist-config/{PTID}/?name=Organizer").content.decode()
        self.assertNotIn("A draft generated from the component list", html)


class TypEsPageTest(TestCase):
    """#213: the type's items, each linking to its executive summary."""
    URL = f"/hw/dev/exec-summary/{SIPM}/"

    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("e", "e@e.io", "pw"))
        _node(SIPM, instance="dev", component_type_name="SiPM board")
        for i in range(3):
            HwdbComponentEvent.objects.create(instance="dev", part_type_id=SIPM, part_id=f"{SIPM}-0000{i}", serial_number=f"S{i}", status="available")

    def test_lists_the_items(self):
        api = _api(plans={})
        m1, m2 = _mocked(api)
        with m1, m2:
            r = self.client.get(self.URL)
            html = r.content.decode()
        self.assertEqual(r.status_code, 200)
        self.assertIn("<h1>Executive summaries <span", html)
        self.assertIn("no ES config on this type", html)
        self.assertIn(f'<td class="mono"><a href="/hw/dev/part/{SIPM}-00000/exec-summary/" onclick="event.stopPropagation()">{SIPM}-00000</a></td>', html)
        self.assertIn('<td class="mono">S2</td>', html)
        self.assertEqual(html.count('class="ship-row"'), 3)
        api = _api(plans={}, images={SIPM: [{"image_id": "e1", "image_name": f"ES_{SIPM}_20261001.json", "created": "2026-10-01T00:00:00"}]})
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(self.URL).content.decode()
        self.assertNotIn("no ES config on this type", html)
        self.assertEqual(api.get_image_response.call_count, 0)   # nothing loaded: one listing, the mirror for the rest


class TypePageTest(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("t", "t@t.io", "pw"))
        self.node = _node(SIPM, tests_synced_at=timezone.now(), n_tests=1)
        HwdbTestEvent.objects.create(part_type_id=SIPM, part_id="", test_type_name="t", created=timezone.now())
        HwdbComponentEvent.objects.create(part_type_id=SIPM, part_id="P1", created=timezone.now())
        self.url = navigation.leaf_path_for("prod", SIPM)

    def test_organizer_and_es_links(self):
        # #213: a type's Manage row links its executive-summaries page; a consortium type's Status line its generated organizer
        html = self.client.get(self.url).content.decode()
        self.assertIn(f'<dt>Exec summaries</dt><dd class="span"><a href="/hw/exec-summary/{SIPM}/" title="Every item of the type with a link to its executive summary">by item</a></dd>', html)
        self.assertNotIn("/links/", html)
        ConsortiumTypeOverride.objects.create(instance="prod", part_type_id=SIPM)
        html = self.client.get(self.url).content.decode()
        self.assertIn(f'<a href="/hw/status/{SIPM}/links/" title="The component list as a table of links — each type’s page, checklists and executive summaries — built on each visit">Links</a></dd>', html)
        self.assertNotIn("Exec summaries", html)

    def test_plan_line_and_dashboard_feed(self):
        html = self.client.get(self.url).content.decode()
        self.assertNotIn("data-plan-url", html)
        self.assertNotIn('class="chart-plan-use"', html)   # no HWDB plan: the browser-stored plan as before, no box
        self.assertIn(f'<tr><td colspan="5" class="pl-none">no plan</td><td><a href="/hw/plan/{SIPM}/?next=', html)   # no plan yet: anyone on a write instance may set one
        self.assertIn('>Set plan</a></td></tr>', html)
        production.cache_plan("prod", SIPM, production.normalize_plan(PLAN))
        html = self.client.get(self.url).content.decode()
        self.assertIn('data-plan-total="48000" data-plan-done="2026-12" data-plan-need="2028-05" '
                      f'data-plan-url="/hw/plan/{SIPM}/"', html)
        self.assertIn('<input type="checkbox" class="chart-plan-use" checked> production plan</label>', html)   # Hajime: a default, not a lock
        self.assertEqual(html.count('data-plan-total="48000"'), 2)   # Chao 2026-10-22: the tests chart too
        self.assertEqual(html.count('class="chart-plan-use"'), 2)
        self.assertIn("untick “production plan” to set your own", html)
        self.assertIn("from the production plan", html)
        # Chao 2026-10-27: the Plan row is a small table — needed, the first batch's two dates, the last batch's, the link
        self.assertIn('<dt>Plan</dt><dd class="span"><table class="pl-mini">\n          <thead><tr><th>Needed</th><th>First completed</th><th>First needed</th><th>Last completed</th><th>Last needed</th><th></th></tr></thead>', html)
        self.assertIn(f'<tr><td>48000</td><td>—</td><td>—</td><td>2026-12</td><td>2028-05</td><td><a href="/hw/plan/{SIPM}/?next=', html)
        self.assertIn('title="The plan and its history — last set 2026-10-08 by chaoz">Edit</a></td></tr>', html)   # anyone on a write instance; the plan page applies the roles
        production.cache_plan("prod", SIPM, {**production.normalize_plan(PLAN), "first_completed_by": "2026-03", "first_needed_by": "2026-09"})
        self.assertIn('<tr><td>48000</td><td>2026-03</td><td>2026-09</td><td>2026-12</td><td>2028-05</td>', self.client.get(self.url).content.decode())
        production.cache_plan("prod", SIPM, None)
        html = self.client.get(self.url).content.decode()
        self.assertIn(f'<tr><td colspan="5" class="pl-none">no plan</td><td><a href="/hw/plan/{SIPM}/?next=', html)
        self.assertIn('>Set plan</a></td></tr>', html)
        self.assertNotIn("data-plan-url", html)
        with self.settings(HWDB_WRITE_INSTANCES=["dev"]):
            html = self.client.get(self.url).content.decode()
            self.assertNotIn("<dt>Plan</dt>", html)   # read-only instance, no plan: no line
            production.cache_plan("prod", SIPM, production.normalize_plan(PLAN))
            self.assertIn('by chaoz">History</a></td></tr>', self.client.get(self.url).content.decode())


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
