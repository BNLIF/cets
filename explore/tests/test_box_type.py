"""Tests for editing a box type's connector positions (issue #69): the
complete-envelope PATCH, continuation naming, rename/retarget/delete,
validation, and the write + architect gates. HWDB is mocked.

    python manage.py test explore
"""

from __future__ import annotations

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from explore import navigation
from explore.models import HierarchyNode as H
from explore.views import _next_position_names, _type_patch_envelope

PTID = "D00599800007"
PAGE = f"/hw/dev/box-type/{PTID}/"

TYPE_RECORD = {
    "part_type_id": PTID,
    "full_name": "Z.Sandbox.HWDBUnitTest.Test Type 007",
    "comments": "a box type",
    "connectors": {"FEB1": "D05700300001", "FEB2": "D05700300001"},
    "manufacturers": [{"id": 7, "name": "Acme"}],
    "roles": [{"id": 4, "name": "shipper"}],
    "properties": {"specifications": [
        {"datasheet": {"Color": None}, "version": 1},
        {"datasheet": {"Color": None, "Flavor": None}, "version": 2}]},
}


def _leaf():
    return H.objects.create(
        instance="dev", level=H.LEVEL_TYPE, system_id=5, system_name="Z.Sandbox",
        subsystem_id=998, subsystem_name="HWDBUnitTest", name="Test Type 007",
        part_type_id=PTID, full_name="x",
        tests_synced_at=timezone.now(), shipments_synced_at=timezone.now())


def _api():
    api = mock.MagicMock()
    api.get_component_type.return_value = {"data": TYPE_RECORD}
    api.patch_component_type.return_value = {"status": "OK", "data": "Updated"}
    api.whoami.return_value = {"data": {"architect": True}}
    return api


def _mocked(api):
    return (mock.patch("explore.views.mint_for", return_value="bearer"),
            mock.patch("explore.views.FnalDbApiClient", return_value=api))


class EngineTest(TestCase):
    def test_naming_continues_from_existing(self):
        self.assertEqual(_next_position_names({"FEB1": "x", "FEB2": "x"}, "FEB", 2),
                         ["FEB3", "FEB4"])
        self.assertEqual(_next_position_names({}, "FEMB", 2), ["FEMB1", "FEMB2"])
        # unrelated positions and non-numeric suffixes don't confuse it
        self.assertEqual(_next_position_names(
            {"FEB10": "x", "FEBX": "x", "Cam1": "y"}, "FEB", 1), ["FEB11"])

    def test_envelope_is_complete_and_echoed(self):
        env = _type_patch_envelope(TYPE_RECORD, {"FEB1": "a"})
        self.assertEqual(env, {
            "comments": "a box type",
            "connectors": {"FEB1": "a"},
            "manufacturers": [7],
            "name": "Z.Sandbox.HWDBUnitTest.Test Type 007",
            "part_type_id": PTID,
            "properties": {"specifications": {
                "datasheet": {"Color": None, "Flavor": None}}},  # the LAST entry
            "roles": [4],
        })


class BoxTypeViewTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("w", "w@w.io", "pw")
        self.client.force_login(self.user)
        _leaf()

    def test_page_lists_positions_with_edit_controls(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.get(PAGE)
        html = resp.content.decode()
        self.assertIn('value="FEB1"', html)          # editable name field
        self.assertIn("deleting or renaming", html)  # the occupied-position guardrail note

    def test_edit_renames_and_retargets_a_position(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            self.client.post(PAGE, {"action": "edit", "op": "save", "position": "FEB1",
                                    "new_name": "FEMB1", "child_type": "d05700300002"})
        payload = api.patch_component_type.call_args.args[1]
        self.assertEqual(payload["connectors"],
                         {"FEMB1": "D05700300002", "FEB2": "D05700300001"})
        self.assertEqual(payload["name"], TYPE_RECORD["full_name"])

    def test_delete_removes_a_position(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            self.client.post(PAGE, {"action": "edit", "op": "delete", "position": "FEB2"})
        payload = api.patch_component_type.call_args.args[1]
        self.assertEqual(payload["connectors"], {"FEB1": "D05700300001"})

    def test_edit_validation_blocks_bad_input(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            self.client.post(PAGE, {"action": "edit", "op": "save", "position": "FEB1",
                                    "new_name": "FEB2", "child_type": "D05700300001"})  # name collision
            self.client.post(PAGE, {"action": "edit", "op": "save", "position": "GONE",
                                    "new_name": "X1", "child_type": "D05700300001"})    # unknown position
            self.client.post(PAGE, {"action": "edit", "op": "save", "position": "FEB1",
                                    "new_name": "FEB1", "child_type": "not-a-type"})    # bad type id
            self.client.post(PAGE, {"action": "edit", "op": "save", "position": "FEB1",
                                    "new_name": "FEB1", "child_type": "D05700300001"})  # no-op
        api.patch_component_type.assert_not_called()

    def test_non_architect_is_forbidden(self):
        api = _api()
        api.whoami.return_value = {"data": {"architect": False}}
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.get(PAGE)
        self.assertEqual(resp.status_code, 403)

    def test_add_positions_patches_complete_envelope(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            self.client.post(PAGE, {"prefix": "FEMB", "count": "3",
                                    "child_type": "d05700300001"})
        payload = api.patch_component_type.call_args.args[1]
        self.assertEqual(payload["connectors"], {
            "FEB1": "D05700300001", "FEB2": "D05700300001",
            "FEMB1": "D05700300001", "FEMB2": "D05700300001",
            "FEMB3": "D05700300001"})
        self.assertEqual(payload["name"], TYPE_RECORD["full_name"])
        self.assertEqual(payload["manufacturers"], [7])

    def test_validation_blocks_bad_input(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            self.client.post(PAGE, {"prefix": "FEMB", "count": "0",
                                    "child_type": "D05700300001"})
            self.client.post(PAGE, {"prefix": "FEMB", "count": "1",
                                    "child_type": "not-a-type"})
            self.client.post(PAGE, {"prefix": "", "count": "1",
                                    "child_type": "D05700300001"})
        api.patch_component_type.assert_not_called()

    def test_hwdb_rejection_is_reported(self):
        api = _api()
        api.patch_component_type.return_value = {"status": "ERROR", "data": "no permission"}
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.post(PAGE, {"prefix": "FEMB", "count": "1",
                                           "child_type": "D05700300001"},
                                    follow=True)
        self.assertIn("no permission", resp.content.decode())

    @override_settings(HWDB_WRITE_INSTANCES=["dev"])
    def test_prod_is_forbidden(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self.client.get(f"/hw/box-type/{PTID}/")
        self.assertEqual(resp.status_code, 403)


NEW_PTID = "D00599800099"

NEW_RECORD = {
    "part_type_id": NEW_PTID,
    "full_name": "Z.Sandbox.HWDBUnitTest.Bigger Box",
    "comments": "cloned",
    "connectors": {"FEB1": "D05700300001", "FEB2": "D05700300001"},
    "manufacturers": [], "roles": [],
    "properties": None,
}


def _clone_api():
    api = _api()
    api.get_component_type.side_effect = lambda ptid: {
        "data": NEW_RECORD if ptid == NEW_PTID else TYPE_RECORD}
    api.post_component_type.return_value = {
        "status": "OK", "data": {"part_type_id": NEW_PTID}}
    return api


class CloneTypeTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("w", "w@w.io", "pw")
        self.client.force_login(self.user)
        self.leaf = _leaf()

    def _clone(self, name="Bigger Box"):
        return self.client.post(PAGE, {"action": "clone", "new_name": name,
                                       "comments": "cloned"}, follow=True)

    def test_clone_creates_under_same_subsystem(self):
        api = _clone_api()
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self._clone()
        api.post_component_type.assert_called_once_with("D", 5, 998, {
            "component_type_id": 0,  # required by the server even on create
            "name": "Bigger Box", "category": "generic", "comments": "cloned",
            "connectors": {"FEB1": "D05700300001", "FEB2": "D05700300001"}})
        self.assertIn(NEW_PTID, resp.content.decode())

    def test_clone_copies_spec_onto_new_type(self):
        api = _clone_api()
        m1, m2 = _mocked(api)
        with m1, m2:
            self._clone()
        ptid, env = api.patch_component_type.call_args.args
        self.assertEqual(ptid, NEW_PTID)
        self.assertEqual(env["properties"]["specifications"]["datasheet"],
                         {"Color": None, "Flavor": None})   # from the SOURCE
        self.assertEqual(env["manufacturers"], [7])
        self.assertEqual(env["roles"], [4])
        self.assertEqual(env["name"], NEW_RECORD["full_name"])  # the NEW identity
        self.assertEqual(env["connectors"], NEW_RECORD["connectors"])

    def test_clone_makes_a_mirror_leaf(self):
        api = _clone_api()
        m1, m2 = _mocked(api)
        with m1, m2:
            self._clone()
        node = H.for_instance("dev").get(level=H.LEVEL_TYPE, part_type_id=NEW_PTID)
        self.assertEqual(node.name, "Bigger Box")
        self.assertEqual((node.system_id, node.subsystem_id), (5, 998))
        self.assertEqual(node.parent_id, self.leaf.parent_id)

    def test_uncurated_clone_warns(self):
        api = _clone_api()
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self._clone()
        self.assertIn("curation", resp.content.decode())

    def test_clone_without_name_is_blocked(self):
        api = _clone_api()
        m1, m2 = _mocked(api)
        with m1, m2:
            self._clone(name="")
        api.post_component_type.assert_not_called()

    def test_missing_id_in_response_skips_spec_copy(self):
        api = _clone_api()
        api.post_component_type.return_value = {"status": "OK", "data": "Created"}
        m1, m2 = _mocked(api)
        with m1, m2:
            resp = self._clone()
        api.patch_component_type.assert_not_called()
        self.assertIn("didn’t return its id", resp.content.decode())


class LeafLinkTest(TestCase):
    """The component-type page offers the positions editor to architects only
    (session-cached whoami)."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("w", "w@w.io", "pw")
        self.client.force_login(self.user)
        sys = H.objects.create(
            instance="dev", level=H.LEVEL_SYSTEM, system_id=5, part_type_id="",
            system_name="Z.Sandbox", name="Z.Sandbox")
        sub = H.objects.create(
            instance="dev", level=H.LEVEL_SUBSYSTEM, parent=sys, system_id=5,
            subsystem_id=998, part_type_id="", system_name="Z.Sandbox",
            subsystem_name="HWDBUnitTest", name="HWDBUnitTest")
        H.objects.create(
            instance="dev", level=H.LEVEL_TYPE, parent=sub, system_id=5,
            system_name="Z.Sandbox", subsystem_id=998, subsystem_name="HWDBUnitTest",
            name="Test Type 007", part_type_id=PTID, full_name="x",
            tests_synced_at=timezone.now(), shipments_synced_at=timezone.now())

    def test_architect_sees_the_positions_link(self):
        api = _api()
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(navigation.leaf_path_for("dev", PTID)).content.decode()
        self.assertIn(f"/hw/dev/box-type/{PTID}/", html)

    def test_non_architect_does_not_see_the_link(self):
        api = _api()
        api.whoami.return_value = {"data": {"architect": False}}
        m1, m2 = _mocked(api)
        with m1, m2:
            html = self.client.get(navigation.leaf_path_for("dev", PTID)).content.decode()
        self.assertNotIn(f"/hw/dev/box-type/{PTID}/", html)
