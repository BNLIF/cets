"""#146: architects set the physics test-date field per type from the Type
View; the setting overrides the code registry at sync time.

    python manage.py test explore.tests.test_test_date_setting
"""

from __future__ import annotations

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from explore import events, navigation
from explore.models import HierarchyNode as H
from explore.models import HwdbTestData, TestDateSetting

PTID = "D05700200001"   # TDE AMC — not in the code registry
SIPM = "D00400100003"   # in the code registry (Test Results → Date)


def _leaf(instance="dev", ptid=PTID):
    sys, _ = H.objects.get_or_create(
        instance=instance, level=H.LEVEL_SYSTEM, system_id=81, subsystem_id=None, part_type_id="",
        defaults={"system_name": "FD CE", "name": "FD CE"})
    sub, _ = H.objects.get_or_create(
        instance=instance, level=H.LEVEL_SUBSYSTEM, system_id=81, subsystem_id=202, part_type_id="",
        defaults={"parent": sys, "system_name": "FD CE", "subsystem_name": "AMC", "name": "AMC"})
    return H.objects.create(
        instance=instance, level=H.LEVEL_TYPE, parent=sub, system_id=81, system_name="FD CE",
        subsystem_id=202, subsystem_name="AMC", name="TDE AMC", part_type_id=ptid,
        n_components=3, full_name="D.FD CE.AMC.TDE AMC", tests_synced_at=timezone.now())


class SpecOverrideTest(TestCase):
    def test_setting_wins_over_registry_and_clears_back_to_it(self):
        self.assertEqual(events.physics_date_field("prod", SIPM), "Test Results → Date")
        TestDateSetting.objects.create(instance="prod", part_type_id=SIPM,
                                       path=["Results", "When"], style="ymd")
        self.assertEqual(events.test_date_spec("prod", SIPM),
                         {"label": "Results → When", "path": ["Results", "When"],
                          "style": "ymd", "day_first": True})
        self.assertEqual(events.test_date_spec("dev", SIPM)["path"],   # the setting is per instance;
                         ["Test Results", 0, "Date"])                  # the code registry is not
        TestDateSetting.objects.all().delete()
        self.assertEqual(events.physics_date_field("prod", SIPM), "Test Results → Date")

    def test_settings_path_reads_through_lists(self):
        spec = TestDateSetting(path=["Test Results", "Date"], style="dm-or-md", day_first=True).spec()
        dt = events.extract_test_date({"Test Results": [{"Date": "20-07-2023-10:19 UTC"}]}, spec)
        self.assertEqual((dt.year, dt.month, dt.day), (2023, 7, 20))
        # the first entry CARRYING the key stands for the list
        dt = events.extract_test_date({"Test Results": [{"Other": 1}, {"Date": "2024-05-17"}]},
                                      TestDateSetting(path=["Test Results", "Date"], style="ymd").spec())
        self.assertEqual((dt.year, dt.month, dt.day), (2024, 5, 17))
        self.assertIsNone(events.extract_test_date({"Test Results": [{"Date": 5}]}, spec))

    def test_candidates_list_date_looking_fields_with_a_sample(self):
        for i, (when, d) in enumerate([("2026-01-05", "2026/01/05"), ("2026-01-06", "2026/01/06")]):
            HwdbTestData.objects.create(
                instance="dev", part_type_id=PTID, part_id=f"{PTID}-0000{i}", test_type_id=7,
                test_type_name="QC", created=f"{when}T00:00:00+00:00",
                test_data={"Test Date": d, "Operator": "Ann", "Ch": [{"V": 1.5, "Stamp": "05-17-2024-09:23"}],
                           "Comment": "ran on 2026"})
        HwdbTestData.objects.create(instance="dev", part_type_id=PTID, part_id="X", test_type_id=8,
                                    test_type_name="Burn-in", test_data={"Nothing": "here"})
        HwdbTestData.objects.create(instance="prod", part_type_id=PTID, part_id="Y", test_type_id=7,
                                    test_type_name="QC", test_data={"Prod only": "2020-01-01"})
        c = events.test_date_candidates("dev", PTID)
        self.assertEqual([x["test_type"] for x in c], ["Burn-in", "QC"])
        self.assertEqual(c[0]["keys"], [])
        self.assertEqual(c[1]["keys"], [
            {"path": ["Ch", "Stamp"], "n": 2, "sample": "05-17-2024-09:23"},
            {"path": ["Test Date"], "n": 2, "sample": "2026/01/06"}])   # newest record's value

    def test_fetch_counts_records_binned_on_the_record_date(self):
        api = mock.MagicMock()
        api.get_tests.return_value = {"data": [
            {"created": "2026-05-29T00:00:00+00:00", "test_data": {"Test Date": "2026/01/05"}},
            {"created": "2026-05-30T00:00:00+00:00", "test_data": {"Test Date": "soon"}},
            {"created": "2026-05-31T00:00:00+00:00", "test_data": {}}]}
        spec = TestDateSetting(path=["Test Date"], style="ymd").spec()
        r = events._fetch_component(api, "P1", spec, {"QC": 7}, need_detail=False, need_tests=True)
        self.assertEqual(r["date_fallbacks"], 2)
        self.assertEqual([dt.day for _n, dt in r["tests"]], [5, 30, 31])


class TypeViewTest(TestCase):
    URL = f"/hw/dev/test-date/{PTID}/"

    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("a", "a@a.io", "pw"))

    def test_endpoint_gates(self):
        with mock.patch("explore.views._is_architect", return_value=False):
            self.assertEqual(self.client.post(self.URL, {}).status_code, 403)
        self.assertEqual(self.client.post(f"/hw/test-date/{PTID}/", {}).status_code, 403)   # prod: no writes
        self.assertEqual(self.client.get(self.URL).status_code, 405)

    def test_save_and_clear(self):
        leaf = _leaf()
        page = navigation.leaf_path_for("dev", PTID)
        self.assertIsNotNone(page)
        with mock.patch("explore.views._is_architect", return_value=True):
            r = self.client.post(self.URL, {"path": '["Test Date"]', "style": "ymd", "next": page}, follow=True)
            html = r.content.decode()
        row = TestDateSetting.for_instance("dev").get(part_type_id=PTID)
        self.assertEqual((row.path, row.style, row.day_first), (["Test Date"], "ymd", False))
        self.assertIn("Test-date field set to “Test Date” — run a Full re-sync", html)
        self.assertIn('Test date field: <span class="mono">Test Date</span>', html)
        self.assertIn("Tests performed", html)                      # the chart's title follows
        self.assertIn("test_data “Test Date”", html)                # …and its caption
        with mock.patch("explore.views._is_architect", return_value=True):
            self.client.post(self.URL, {"path": "nope", "style": "ymd", "next": page})
            r = self.client.get(page)
            self.assertIn("Pick a date field and its format.", r.content.decode())
            r = self.client.post(self.URL, {"action": "clear", "next": page}, follow=True)
        self.assertFalse(TestDateSetting.objects.exists())
        self.assertIn("re-bins the Tests chart on the HWDB record date.", r.content.decode())
        self.assertIn("Tests recorded", r.content.decode())

    def test_card_is_read_only_without_the_role_and_offers_the_picker_with_it(self):
        _leaf()
        HwdbTestData.objects.create(instance="dev", part_type_id=PTID, part_id="P", test_type_id=7,
                                    test_type_name="QC", test_data={"Test Date": "2026/01/05"})
        page = navigation.leaf_path_for("dev", PTID)
        with mock.patch("explore.views._is_architect", return_value=False):
            html = self.client.get(page).content.decode()
        self.assertIn("Test date field: none", html)
        self.assertLess(html.index("Tests recorded"), html.index("Test date field: none"))   # inside that pane
        self.assertNotIn("test-date-form", html)
        with mock.patch("explore.views._is_architect", return_value=True):
            html = self.client.get(page).content.decode()
        self.assertIn('id="test-date-form"', html)
        self.assertIn('"test_type": "QC"', html)                    # candidates JSON
        self.assertIn('"sample": "2026/01/05"', html)
        self.assertIn("open on the test type whose records hold the saved field", html)
        # without mirrored records the card points at the Plot page instead of a picker
        HwdbTestData.objects.all().delete()
        with mock.patch("explore.views._is_architect", return_value=True):
            html = self.client.get(page).content.decode()
        self.assertIn("fetch test data on the Plot page", html)
        self.assertNotIn('id="td-source"', html)
