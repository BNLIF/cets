"""#217: the installation plan — ``Installation_plan_<type>.json`` on a
type, its text form, the steps table off the mirror's test events, the
overview, the plan page and the edit page. HWDB mocked — no network.

    python manage.py test explore.tests.test_installation
"""

import json
from datetime import date, datetime, timezone as dt_timezone
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from explore import installation
from explore.models import ActivityEvent, HwdbTestEvent, InstallationMap, InstallationPlan, P6Activity
from explore.tests.test_events import _node
from hwdb.api_client import FnalDbApiClient

DET = "Z00100600001"            # the detector's virtual type, carrying the plan
SS, CRP = "D08100200001", "D08100100001"
TEXT = f"""Top drift volume
  7 | CRP support structures | after 6
    {SS} x 2 | Installation
  8 | Top CRPs | after 7 | VD.INS.1 | Two CRUs are joined | then raised.
    {CRP} x 2 | installation
    {SS} x 1
Closing
  15 | Close the TCO"""
STEPS = [
    {"n": 7, "name": "CRP support structures", "zone": "Top drift volume", "after": [6], "p6": "", "note": "", "details": "", "status": "", "status_by": "", "status_on": "",
     "parts": [{"type": SS, "count": 2, "checklist": "Installation", "before": "", "after": ""}]},
    {"n": 8, "name": "Top CRPs", "zone": "Top drift volume", "after": [7], "p6": "VD.INS.1", "note": "Two CRUs are joined | then raised.", "details": "", "status": "", "status_by": "", "status_on": "",
     "parts": [{"type": CRP, "count": 2, "checklist": "installation", "before": "", "after": ""}, {"type": SS, "count": 1, "checklist": "", "before": "", "after": ""}]},
    {"n": 15, "name": "Close the TCO", "zone": "Closing", "after": [], "p6": "", "note": "", "details": "", "status": "", "status_by": "", "status_on": "", "parts": []},
]
SUB_TEXT = f"""  1 | Join the CRUs
    {CRP} x 2 | Installation
  2 | Hang | after 1
    {CRP} x 2 | Hang"""


def _api(steps=STEPS, sub=None):
    api = mock.MagicMock(spec=FnalDbApiClient)
    files = {"plan": {"steps": steps}, "chk": {"name": "Installation", "test_type_name": "CRP installed", "sections": []},
             "sub": {"steps": sub or []}, "hang": {"name": "Hang", "test_type_name": "CRP hung", "sections": []},
             "proc": {"name": "Drawings", "sections": []}}
    listing = {DET: [{"image_id": "plan", "image_name": f"Installation_plan_{DET}.json", "created": "2026-11-13T10:00:00", "comments": "first"}] if steps is not None else [],
               SS: [{"image_id": "chk", "image_name": f"Checklist_{SS}_Installation.json", "created": "2026-11-01T00:00:00"}],
               CRP: [{"image_id": "chk", "image_name": f"Checklist_{CRP}_Installation.json", "created": "2026-11-01T00:00:00"},
                     {"image_id": "hang", "image_name": f"Checklist_{CRP}_Hang.json", "created": "2026-11-01T00:00:00"},
                     {"image_id": "proc", "image_name": f"Checklist_{CRP}_Drawings.json", "created": "2026-11-01T00:00:00", "comments": "[procedure]"},
                     {"image_id": "sub", "image_name": f"Installation_plan_{CRP}.json", "created": "2026-11-02T00:00:00"}]}
    api.get_component_type_images.side_effect = lambda t: {"data": listing.get(t, [])}
    api.get_image_response.side_effect = lambda iid: mock.Mock(content=json.dumps(files[iid]).encode())
    api.post_component_type_image.return_value = {"status": "OK", "image_id": "new"}
    return api


def _mocked(api):
    return (mock.patch("explore.views.mint_for", return_value="bearer"),
            mock.patch("explore.views.FnalDbApiClient", return_value=api))


def _record(tid, n, tt="CRP installed"):
    HwdbTestEvent.objects.create(instance="dev", part_type_id=tid, part_id=f"{tid}-{n:05d}", test_type_name=tt,
                                 created=datetime(2026, 11, 1, tzinfo=dt_timezone.utc))


class EngineTest(TestCase):
    def test_text_form_round_trips(self):
        steps, errors = installation.parse_text(TEXT)
        self.assertEqual(errors, [])
        self.assertEqual(steps, STEPS)
        self.assertEqual(installation.parse_text(installation.to_text(steps)), (steps, []))
        self.assertEqual(installation.normalize({"steps": steps}), steps)
        # the note is the short description; the details are Markdown on > lines, paragraphs and all
        got, errors = installation.parse_text("  1 | a |  |  | short\n    > First.\n    >\n    > - [drawing](https://x.y/z)\n  > stray")
        self.assertEqual((got[0]["note"], got[0]["details"], errors), ("short", "First.\n\n- [drawing](https://x.y/z)\nstray", []))
        self.assertEqual(installation.to_text(got), "  1 | a |  |  | short\n    > First.\n    >\n    > - [drawing](https://x.y/z)\n    > stray")
        self.assertEqual(installation.parse_text("> lost")[1], ["Line 1: details need a step above them."])

    def test_bad_lines_are_named(self):
        steps, errors = installation.parse_text(f"  {SS} x 2\nZone\n  1 | a\n  1 | again\n  what is this\n")
        self.assertEqual([s["n"] for s in steps], [1])
        self.assertEqual(errors, ["Line 1: a component needs a step above it.", "Line 4: step 1 is already there.",
                                  "Line 5: write a step as “number | name”, a component as “TYPEID x count | checklist”."])

    def test_table_counts_items_with_a_record(self):
        steps = [{**s, "parts": [{**p, "test_type": "CRP installed" if p["checklist"] else ""} for p in s["parts"]]} for s in STEPS]
        _record(SS, 1), _record(SS, 2), _record(SS, 2), _record(CRP, 1), _record(CRP, 9, "other test")
        P6Activity.objects.create(activity_id="VD.INS.1", kind="install", name="Install top CRPs", date=date(2028, 3, 1))
        rows = installation.table(steps, installation.installed("dev", steps), {SS: "Support structure"})
        by = {r["key"]: r for r in rows}
        self.assertEqual([r["kind"] for r in rows], ["zone", "step", "part", "step", "part", "part", "zone", "step"])
        self.assertEqual((by["7"]["n"], by["7"]["count"], by["7"]["state"]), (2, 2, "done"))   # one item recorded twice counts once
        self.assertEqual((by["8"]["n"], by["8"]["count"], by["8"]["state"], by["8"]["warn"]), (1, 3, "prog", ""))
        self.assertEqual(by["8"]["p6_date"], date(2028, 3, 1))
        self.assertEqual((by[f"8-{CRP}"]["n"], by[f"8-{CRP}"]["label"]), (1, CRP))
        self.assertEqual((by[f"8-{SS}"]["n"], by[f"8-{SS}"]["problem"]), (None, "No checklist named for this component"))
        self.assertEqual((by["15"]["n"], by["15"]["state"]), (None, "todo"))
        self.assertEqual(installation.summary(rows), {"n_steps": 3, "n_done": 1, "n_prog": 1})
        # a step started while the one before it is unfinished is marked, not locked
        HwdbTestEvent.objects.filter(part_type_id=SS).delete()
        rows = installation.table(steps, installation.installed("dev", steps), {})
        self.assertEqual(next(r for r in rows if r["key"] == "8")["warn"], "Started before step 7 is done")


class PagesTest(TestCase):
    PLAN, EDIT = f"/hw/dev/installation/{DET}/", f"/hw/dev/installation/{DET}/edit/"

    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("d", "d@d.io", "pw"))
        _node(DET, instance="dev", component_type_name="FD-VD installation")
        _node(CRP, instance="dev", component_type_name="Top CRP")

    def test_plan_page_reads_live_and_fills_the_overview(self):
        html = self.client.get("/hw/dev/installation/").content.decode()
        self.assertIn('<a class="eh-nav-item active" href="/hw/dev/installation/">Installation</a>', html)
        self.assertIn("No installation plan read yet.", html)
        _record(CRP, 1), _record(CRP, 2)
        m1, m2 = _mocked(_api())
        with m1, m2:
            html = self.client.get(self.PLAN).content.decode()
        self.assertIn("Installation plan — 3 steps, 0 done, 1 in progress.", html)
        self.assertIn('<span class="in-no">8</span>Top CRPs</th>', html)   # the table stays lean: the note and the rest are in the step's panel
        self.assertIn('<h2>8 · Top CRPs</h2>', html)
        self.assertIn('<p>Two CRUs are joined | then raised.</p>', html)
        self.assertIn('<a href="#step-7">7 · CRP support structures</a> <span class="in-state todo">Not started</span>', html)
        self.assertIn(f'<span class="in-dim">Procedures: <a href="/hw/dev/checklist/{CRP}/Drawings/">Drawings</a></span>', html)
        self.assertIn(f'<a href="/hw/dev/?node={CRP}" title="the type’s page">Top CRP</a><a class="in-own" href="/hw/dev/installation/{DET}/units/8-{CRP}/" title="Its items, stage by stage">units &#9656;</a><a class="in-own" href="/hw/dev/installation/{CRP}/"', html)   # the CRP type has a plan of its own
        self.assertIn(f'<a href="/hw/dev/items/{CRP}/" title="The type’s items and their records">2</a>', html)   # "installation" finds the checklist Installation
        self.assertIn('title="No checklist named for this component"', html)
        self.assertIn(f'href="{self.EDIT}">&#9998; Edit plan</a>', html)
        cached = InstallationPlan.objects.get(instance="dev", part_type_id=DET).steps
        self.assertEqual(cached[1]["parts"][0], {"type": CRP, "count": 2, "checklist": "installation", "before": "", "after": "", "test_type": "CRP installed",
                                                 "used": "Installation", "before_tt": "", "after_tt": "", "own_plan": True, "procedures": ["Drawings"]})
        self.assertIn(f'<a href="/hw/dev/checklist/{CRP}/Installation/" title="Choose an item and record it">Installation</a></td>', html)
        html = self.client.get("/hw/dev/installation/").content.decode()   # the overview: the cache and the mirror alone
        self.assertIn(f'<a href="{self.PLAN}" title="Read it from HWDB now">FD-VD installation</a> <span class="mono">{DET}</span>', html)
        self.assertIn('<td class="num">3</td><td class="num">0</td><td class="num">1</td>', html)
        self.assertEqual(self.client.get(f"/hw/dev/installation/?open={CRP.lower()}")["Location"], f"/hw/dev/installation/{CRP}/")
        # a type without a plan: nothing cached, a link to write one
        m1, m2 = _mocked(_api(steps=None))
        with m1, m2:
            html = self.client.get(self.PLAN).content.decode()
        self.assertIn(f'No installation plan on this type yet — <a href="{self.EDIT}">write one</a>.', html)
        self.assertFalse(InstallationPlan.objects.exists())

    def test_a_component_plan_records_its_steps_on_the_type_itself(self):
        sub, errors = installation.parse_text(SUB_TEXT)
        self.assertEqual((errors, installation.to_text(sub)), ([], SUB_TEXT))
        self.assertEqual(installation.parse_text("  2* | old mark")[0][0]["n"], 2)   # the first drafts' installed mark: read, dropped
        _record(CRP, 1), _record(CRP, 2), _record(CRP, 1, "CRP hung")
        api = _api(steps=sub)
        api.get_component_type_images.side_effect = lambda t: {"data": [
            {"image_id": "plan", "image_name": f"Installation_plan_{CRP}.json", "created": "2026-11-13T10:00:00"},
            {"image_id": "chk", "image_name": f"Checklist_{CRP}_Installation.json", "created": "2026-11-01T00:00:00"},
            {"image_id": "hang", "image_name": f"Checklist_{CRP}_Hang.json", "created": "2026-11-01T00:00:00"}]}
        m1, m2 = _mocked(api)
        with m1, m2:
            own = self.client.get(f"/hw/dev/installation/{CRP}/").content.decode()
        self.assertNotIn("own plan", own)   # no "own plan" link to itself
        self.assertIn("Installation plan — 2 steps, 1 done, 1 in progress.", own)

    def test_a_status_set_by_hand_wins_over_the_counts(self):
        steps, errors = installation.parse_text("  4 | Set up and clean\n    status: done\n  5 | b | after 4\n    status: On hold\n  6 | c\n    status: nope")
        self.assertEqual(([s["status"] for s in steps], errors), (["done", "hold", ""], ["Line 6: a status is one of Not started, In progress, Done, On hold."]))
        self.assertEqual(installation.to_text(steps[:2]), "  4 | Set up and clean\n    status: Done\n  5 | b | after 4\n    status: On hold")
        old = [{**steps[0], "status_by": "hajime3", "status_on": "2026-11-01"}, {**steps[1], "status": ""}]
        new = installation.stamp([dict(s) for s in steps], old, "chaoz", "2026-11-13")
        self.assertEqual([(s["status_by"], s["status_on"]) for s in new], [("hajime3", "2026-11-01"), ("chaoz", "2026-11-13"), ("", "")])
        rows = {r["key"]: r for r in installation.table(new, {}, {})}
        self.assertEqual([(rows[k]["state"], rows[k]["state_label"], rows[k]["auto_label"]) for k in "456"],
                         [("done", "Done", "Not started"), ("hold", "On hold", "Not started"), ("todo", "Not started", "Not started")])
        # set on the edit page alone (Chao 2026-11-13: not from the plan page, where a slip would change it); a save signs it
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            self.assertNotIn("<form", self.client.get(self.PLAN).content.decode().split('id="in-panel"')[1])
            r = self.client.post(self.EDIT, {"plan": TEXT + "\n    status: Done", "reason": "closed"})
        self.assertEqual(r["Location"], self.PLAN)
        body = json.loads(api.post_component_type_image.call_args[0][1].getvalue())["steps"]
        self.assertEqual((body[2]["status"], body[2]["status_by"]), ("done", "d"))
        self.assertEqual(set(body[1]["parts"][0]), {"type", "count", "checklist", "before", "after"})   # the file holds the plan alone
        self.assertEqual(InstallationPlan.objects.get(part_type_id=DET).steps[2]["status"], "done")
        html = self.client.get("/hw/dev/installation/").content.decode()
        self.assertIn('<td class="num">3</td><td class="num">1</td>', html)   # the overview counts it done

    def test_units_page_lists_a_components_items_by_stage(self):
        # #218: a component may name its QC-before and QC-after checklists
        steps, errors = installation.parse_text(f"  8 | Top CRPs\n    {CRP} x 2 | Installation | Hang | Drawings")
        p = steps[0]["parts"][0]
        self.assertEqual((errors, p["before"], p["after"]), ([], "Hang", "Drawings"))
        self.assertEqual(installation.to_text(steps), f"  8 | Top CRPs\n    {CRP} x 2 | Installation | Hang | Drawings")
        self.assertEqual(installation.spec_find([{"DATA": {"Installation": [{"Position": "TCRP R07-C2", "Readout Port": 12}]}}], installation.POSITION_KEYS), "TCRP R07-C2")
        self.assertEqual(installation.spec_find({"a": {"position": {"x": 1}}}, installation.POSITION_KEYS), "")
        when = datetime(2026, 11, 3, tzinfo=dt_timezone.utc)
        HwdbTestEvent.objects.create(instance="dev", part_type_id=CRP, part_id=f"{CRP}-00002", test_type_name="CRP installed", created=when, created_by="Hajime M")
        HwdbTestEvent.objects.create(instance="dev", part_type_id=CRP, part_id=f"{CRP}-00002", test_type_name="CRP hung", created=when)
        api = _api(steps=steps)
        api._make_request.return_value = {"data": [
            {"part_id": f"{CRP}-00001", "serial_number": "S1", "status": {"id": 100, "name": "Available"}, "location": {"id": 186, "name": "SURF"}, "specifications": [{"DATA": {}}]},
            {"part_id": f"{CRP}-00002", "serial_number": "", "status": {"id": 100, "name": "Available"}, "location": {"id": 0, "name": "x"},
             "specifications": [{"DATA": {"Installation": [{"Position": "TCRP R07-C2", "Readout port": "P12"}]}}]}],
            "pagination": {"pages": 3, "total": 120}}
        m1, m2 = _mocked(api)
        with m1, m2:
            plan = self.client.get(self.PLAN).content.decode()
            self.assertIn(f'<a class="in-tab" aria-selected="false" href="/hw/dev/installation/{DET}/units/">Units</a>', plan)
            html = self.client.get(self.PLAN + "units/").content.decode()
            rows = self.client.get(self.PLAN + f"units/?group=8-{CRP}").content.decode()
            self.assertEqual(self.client.get(self.PLAN + "units/?group=9-nope").status_code, 404)
            own = self.client.get(self.PLAN + f"units/8-{CRP}/?page=2").content.decode()
        self.assertEqual(api._make_request.call_args[1]["params"], {"page": 2, "size": 50})   # a page of the listing a call, never the whole type
        self.assertIn(f'The first 2 of 120 — <a href="/hw/dev/installation/{DET}/units/8-{CRP}/">all its items &#9656;</a>', rows)
        self.assertIn(f'<a class="in-own" href="/hw/dev/installation/{DET}/units/8-{CRP}/" title="Its items, stage by stage">units &#9656;</a>', plan)
        self.assertIn("Step 8 · Top CRPs — 2 needed, 120 in HWDB.", own)
        self.assertIn('<a href="?page=1">1</a><b>2</b><a href="?page=3">3</a>', own)
        self.assertIn('<th>QC before installation</th><th class="un-div">Installed</th>', own)
        # the component has a plan of its own: its page shows that plan's steps as the columns
        sub_steps, _e = installation.parse_text(SUB_TEXT)
        api2 = _api(steps=steps, sub=sub_steps)
        api2._make_request.return_value = api._make_request.return_value
        m1, m2 = _mocked(api2)
        with m1, m2:
            self.client.get(self.PLAN)   # the plan page marks the component's own plan
            own = self.client.get(self.PLAN + f"units/8-{CRP}/").content.decode()
        self.assertIn('<th title="Installation">1 · Join the CRUs</th><th title="Hang">2 · Hang</th><th class="un-div">Position</th>', own)
        self.assertIn(f'<a href="/hw/dev/part/{CRP}-00002/checklist/Hang/" title="Hang — open the record"><span class="un-tick">', own)
        self.assertIn(f'<tbody data-group="8-{CRP}">', html)
        self.assertIn('<span class="un-step">step 8 · Top CRPs</span>', html)
        self.assertIn('<span class="in-frac">1 / 2</span>', html)
        self.assertIn(f'<td class="un-div"><a href="/hw/dev/part/{CRP}-00002/checklist/Installation/" title="Installation — open the record"><span class="un-tick">&#10003;</span><span class="un-when">2026-11-03 · Hajime M</span></a></td>', rows)
        self.assertIn('<td>TCRP R07-C2</td>\n  <td>P12</td>', rows)
        self.assertIn('<td>In Transit</td>', rows)
        self.assertIn(f'<td class="un-div"><a href="/hw/dev/part/{CRP}-00001/checklist/Installation/" title="Installation">Record</a></td>', rows)
        self.assertIn(f'<a href="/hw/dev/part/{CRP}-00001/checklist/Hang/" title="Hang">Record</a>', rows)
        self.assertIn(f'href="/hw/dev/part/{CRP}-00001/checklist/Drawings/" title="Drawings — this checklist was not found on the type">Record</a>', rows)   # a procedure is not a record

    def test_map_links_kinds_reads_positions_and_syncs(self):
        # #219: kinds of displayed position linked to types locally, the items' positions off the live listing, Sync posts the links
        MAP = self.PLAN + "map/"
        api = _api()
        api.get_component_type.return_value = {"data": {"roles": None}}
        api._make_request.return_value = {"data": [
            {"part_id": f"{CRP}-00001", "specifications": [{"DATA": {}}]},
            {"part_id": f"{CRP}-00002", "specifications": [{"DATA": {"Position": "TCRP R07-C2"}}]}], "pagination": {"pages": 1}}
        m1, m2 = _mocked(api)
        with m1, m2:
            self.assertIn(f'href="{MAP}">3D Map</a>', self.client.get(self.PLAN).content.decode())
            html = self.client.get(MAP).content.decode()
            self.assertIn('"steps": {"7": {"name": "CRP support structures", "note": ""}', html)   # the plan's own step names, off the cache
            self.assertIn('"links": {}', html)
            self.assertFalse(InstallationMap.objects.exists())   # nothing stored, nothing made up
            self.assertEqual(self.client.post(MAP, {"action": "link", "kind": "tcrp", "type": "nope"}).status_code, 400)
            self.assertEqual(self.client.post(MAP, {"action": "link", "kind": "tcrp", "type": CRP}).json(), {"ok": True})
            self.client.post(MAP, {"action": "link", "kind": "sst", "type": SS})
            self.client.post(MAP, {"action": "link", "kind": "sst", "type": ""})   # no type: the link goes
            row = InstallationMap.objects.get(part_type_id=DET)
            self.assertEqual((row.links, row.synced), ({"tcrp": CRP}, False))
            self.assertEqual(self.client.get(MAP + "?status=1").json(), {"types": {CRP: {"TCRP R07-C2": f"{CRP}-00002"}}, "failed": []})
            html = self.client.get(MAP).content.decode()
            self.assertIn(f'"names": {{"{CRP}": "Top CRP"}}', html)
            self.assertIn('<form method="post" id="im-sync">', html)   # links changed: Sync shows
            self.assertEqual(self.client.post(MAP, {"action": "sync"}).status_code, 302)
        name, body = api.post_component_type_image.call_args[0][2], json.loads(api.post_component_type_image.call_args[0][1].getvalue())
        self.assertEqual((name, body["links"]), (f"Installation_map_{DET}.json", {"tcrp": CRP}))
        self.assertTrue(InstallationMap.objects.get(part_type_id=DET).synced)
        # no local row: restored from the newest image on the type
        InstallationMap.objects.all().delete()
        api.get_component_type_images.side_effect = lambda t: {"data": [{"image_id": "map", "image_name": f"Installation_map_{DET}.json", "created": "2026-11-13T12:00:00"}]}
        api.get_image_response.side_effect = lambda iid: mock.Mock(content=json.dumps({"links": {"cath": SS}}).encode())
        m1, m2 = _mocked(api)
        with m1, m2:
            self.client.get(MAP)
        row = InstallationMap.objects.get(part_type_id=DET)
        self.assertEqual((row.links, row.synced), ({"cath": SS}, True))
        # a type whose roles the account lacks: no linking
        api.get_component_type.return_value = {"data": {"roles": [{"id": 9, "name": "tester"}]}}
        m1, m2 = _mocked(api)
        with m1, m2, mock.patch("explore.views._my_roles", return_value=[]):
            self.assertEqual(self.client.post(MAP, {"action": "link", "kind": "tcrp", "type": CRP}).status_code, 403)

    def test_edit_saves_a_version_caches_and_logs(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(self.EDIT).content.decode()
            self.assertIn(f"    {CRP} x 2 | installation\n", html)
            self.assertIn('<div class="in-wb" id="in-wb">', html)   # the workbench over the same text
            self.assertIn("  8 | Top CRPs | after 7 | VD.INS.1 | Two CRUs are joined | then raised.\n", html)
            self.assertIn(f'"checklists": "/hw/dev/checklist-names/X00000000000/"', html)
            r = self.client.post(self.EDIT, {"plan": "Zone\n  1 | a\n  nonsense", "reason": "x"})
            self.assertIn("Line 3: write a step as", r.content.decode())
            self.assertIn("  nonsense</textarea>", r.content.decode())   # the typed text stays
            api.post_component_type_image.assert_not_called()
            r = self.client.post(self.EDIT, {"plan": TEXT, "reason": "from the 2024 document"})
        self.assertEqual(r["Location"], self.PLAN)
        args, kw = api.post_component_type_image.call_args
        self.assertEqual((args[0], args[2], kw["comments"]), (DET, f"Installation_plan_{DET}.json", "from the 2024 document"))
        body = json.loads(args[1].getvalue())
        self.assertEqual((body["steps"], body["updated_by"]), (STEPS, "d"))
        self.assertEqual(len(InstallationPlan.objects.get(part_type_id=DET).steps), 3)
        self.assertEqual(ActivityEvent.objects.get().summary, f"Installation plan of {DET}: 3 steps — from the 2024 document")
        # the type's roles gate the save
        api.get_component_type.return_value = {"data": {"roles": [{"id": 34, "name": "installer"}]}}
        with mock.patch("explore.views._my_roles", return_value=[{"id": 9, "name": "builder"}]), m1, m2:
            html = self.client.get(self.EDIT).content.decode()
            self.assertEqual(self.client.post(self.EDIT, {"plan": TEXT}).status_code, 403)
        self.assertIn("so the plan cannot be edited here", html)
        self.assertNotIn("<textarea", html)
