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
from explore.models import ActivityEvent, HwdbTestEvent, InstallationPlan, P6Activity
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
    {"n": 7, "name": "CRP support structures", "zone": "Top drift volume", "after": [6], "p6": "", "note": "",
     "parts": [{"type": SS, "count": 2, "checklist": "Installation"}]},
    {"n": 8, "name": "Top CRPs", "zone": "Top drift volume", "after": [7], "p6": "VD.INS.1", "note": "Two CRUs are joined | then raised.",
     "parts": [{"type": CRP, "count": 2, "checklist": "installation"}, {"type": SS, "count": 1, "checklist": ""}]},
    {"n": 15, "name": "Close the TCO", "zone": "Closing", "after": [], "p6": "", "note": "", "parts": []},
]


def _api(steps=STEPS):
    api = mock.MagicMock(spec=FnalDbApiClient)
    files = {"plan": {"steps": steps}, "chk": {"name": "Installation", "test_type_name": "CRP installed", "sections": []},
             "sub": {"steps": []}}
    listing = {DET: [{"image_id": "plan", "image_name": f"Installation_plan_{DET}.json", "created": "2026-11-13T10:00:00", "comments": "first"}] if steps is not None else [],
               SS: [{"image_id": "chk", "image_name": f"Checklist_{SS}_Installation.json", "created": "2026-11-01T00:00:00"}],
               CRP: [{"image_id": "chk", "image_name": f"Checklist_{CRP}_Installation.json", "created": "2026-11-01T00:00:00"},
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

    def test_bad_lines_are_named(self):
        steps, errors = installation.parse_text(f"  {SS} x 2\nZone\n  1 | a\n  1 | again\n  what is this\n")
        self.assertEqual([s["n"] for s in steps], [1])
        self.assertEqual(errors, ["Line 1: a part needs a step above it.", "Line 4: step 1 is already there.",
                                  "Line 5: write a step as “number | name”, a part as “TYPEID x count | checklist”."])

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
        self.assertEqual((by[f"8-{SS}"]["n"], by[f"8-{SS}"]["problem"]), (None, "No checklist named for this part"))
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
        self.assertIn('<span class="in-no">8</span>Top CRPs<span class="in-note">Two CRUs are joined | then raised.</span>', html)
        self.assertIn(f'<a href="/hw/dev/?node={CRP}" title="the type’s page">Top CRP</a><a class="in-own" href="/hw/dev/installation/{CRP}/"', html)   # the CRP type has a plan of its own
        self.assertIn(f'<a href="/hw/dev/items/{CRP}/" title="The type’s items and their records">2</a>', html)   # "installation" finds the checklist Installation
        self.assertIn('title="No checklist named for this part"', html)
        self.assertIn(f'href="{self.EDIT}">&#9998; Edit plan</a>', html)
        cached = InstallationPlan.objects.get(instance="dev", part_type_id=DET).steps
        self.assertEqual(cached[1]["parts"][0], {"type": CRP, "count": 2, "checklist": "installation", "test_type": "CRP installed", "own_plan": True})
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

    def test_edit_saves_a_version_caches_and_logs(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(self.EDIT).content.decode()
            self.assertIn(f"    {CRP} x 2 | installation\n", html)
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
