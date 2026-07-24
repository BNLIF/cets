"""Tests for the executive summary's recursive sub-component tree (Hajime's
ES review, 2026-07-17): the ``subtree_rows`` walk (full depth, cycle-guarded,
node-capped) and the htmx-loaded partial that shows it on the ES page.

    python manage.py test explore
"""

from __future__ import annotations

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from explore.parts import subtree_rows
from hwdb.fnal.bearer import FnalLinkRequired

BOX = "D00599800007-00128"
PAGE = f"/hw/dev/part/{BOX}/es-subtree/"


def _row(pid, type_name="T", pos="P1", op="mount"):
    return {"part_id": pid, "type_name": type_name,
            "functional_position": pos, "operation": op}


def _walk_api(tree, components=None):
    """A MagicMock api whose manifests come from ``tree`` (pid → child rows)
    and whose component records come from ``components`` (pid → data)."""
    api = mock.MagicMock()
    api.get_subcomponents.side_effect = lambda pid: {"data": tree.get(pid, [])}
    api.get_component.side_effect = lambda pid: {"data": (components or {}).get(
        pid, {"status": {"id": 120, "name": "Passed"},
              "qaqc_uploaded": True, "certified_qaqc": False})}
    return api


class SubtreeWalkTest(TestCase):
    def test_three_levels_preorder_with_depth_and_statuses(self):
        api = _walk_api(
            {BOX: [_row("A"), _row("B")], "A": [_row("A1")], "A1": [_row("A1a")]},
            components={"A1": {"status": {"name": "In Repair"},
                               "qaqc_uploaded": False, "certified_qaqc": True}})
        rows, truncated = subtree_rows(api, BOX)
        self.assertFalse(truncated)
        self.assertEqual([(r["part_id"], r["depth"]) for r in rows],
                         [("A", 0), ("A1", 1), ("A1a", 2), ("B", 0)])
        a1 = rows[1]
        self.assertEqual(a1["status"], "In Repair")
        self.assertFalse(a1["uploaded"])
        self.assertTrue(a1["certified"])
        self.assertEqual(rows[0]["status"], "Passed")

    def test_unmounted_children_are_excluded(self):
        api = _walk_api({BOX: [_row("A"), _row("GONE", op="unmount")]})
        rows, _ = subtree_rows(api, BOX)
        self.assertEqual([r["part_id"] for r in rows], ["A"])

    def test_cycles_and_double_mounts_terminate(self):
        api = _walk_api({BOX: [_row("A")], "A": [_row("B")],
                         "B": [_row("A"), _row(BOX)]})
        rows, truncated = subtree_rows(api, BOX)
        self.assertFalse(truncated)
        self.assertEqual([r["part_id"] for r in rows], ["A", "B"])

    def test_node_cap_truncates_with_a_warning(self):
        api = _walk_api({BOX: [_row("A"), _row("B"), _row("C")]})
        with self.assertLogs("explore.parts", level="WARNING") as logs:
            rows, truncated = subtree_rows(api, BOX, max_nodes=2)
        self.assertTrue(truncated)
        self.assertEqual(len(rows), 2)
        self.assertTrue(any("truncated" in m for m in logs.output))

    def test_failed_record_fetch_degrades_that_row_only(self):
        api = _walk_api({BOX: [_row("A"), _row("B")]})
        good = api.get_component.side_effect

        def get_component(pid):
            if pid == "A":
                raise RuntimeError("boom")
            return good(pid)

        api.get_component.side_effect = get_component
        rows, _ = subtree_rows(api, BOX)
        self.assertEqual([r["part_id"] for r in rows], ["A", "B"])
        self.assertIsNone(rows[0]["status"])
        self.assertIsNone(rows[0]["uploaded"])
        self.assertIsNone(rows[0]["certified"])
        self.assertEqual(rows[1]["status"], "Passed")


class SubtreeCableTest(TestCase):
    """Cable-end refs in the walk (#72), mirroring Hajime's Sandbox model:
    a mounted cable row reads ``<cable PID>.<END name>:<connector #>``, and
    the cable's own manifest lists its peers as ``<PID>.<position>``."""

    FLANGE = "Z00100300064-00001"
    CABLE = "Z00100300080-00001"
    BOARD = "Z00100300069-00005"
    TRAY = "Z00100300070-00001"

    def _cable_api(self):
        return _walk_api({
            self.FLANGE: [_row(f"{self.CABLE}.FCP Flange:1",
                               "Bottom FC termination cold cable", "Cold Bottom FCT")],
            # the cable's "sub-components" are what its ends plug into —
            # connectivity (including its own parent), not contents
            self.CABLE: [_row(f"{self.FLANGE}.Cold Bottom FCT", "Bias FT flange"),
                         _row(f"{self.BOARD}.FC Term Bottom", "FC Termination board"),
                         _row(f"{self.TRAY}.Bottom FCT cables", "BDE cable tray")],
        })

    def test_cable_listed_once_by_base_pid_with_connection(self):
        rows, truncated = subtree_rows(self._cable_api(), self.FLANGE)
        self.assertFalse(truncated)
        self.assertEqual([r["part_id"] for r in rows], [self.CABLE])
        self.assertEqual(rows[0]["connection"], "FCP Flange:1")
        self.assertEqual(rows[0]["status"], "Passed")  # fetched with the base PID

    def test_peer_backrefs_do_not_become_contents(self):
        rows, _ = subtree_rows(self._cable_api(), self.FLANGE)
        listed = {r["part_id"] for r in rows}
        self.assertNotIn(self.BOARD, listed)
        self.assertNotIn(self.TRAY, listed)
        self.assertNotIn(self.FLANGE, listed)

    def test_multi_connector_cable_listed_once(self):
        # slide 12: one bundle mounted at Flange:1..8 is one physical item
        api = _walk_api({self.FLANGE: [
            _row(f"{self.CABLE}.Flange:{n}", "HVS Test Bundle", f"Pos {n}")
            for n in range(1, 9)]})
        rows, _ = subtree_rows(api, self.FLANGE)
        self.assertEqual([r["part_id"] for r in rows], [self.CABLE])


class SubtreePartialViewTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("s", "s@s.io", "pw")
        self.client.force_login(self.user)

    def _mocked(self, api):
        return (mock.patch("explore.views.mint_for", return_value="bearer"),
                mock.patch("explore.views.FnalDbApiClient", return_value=api))

    def test_partial_renders_indented_rows_with_flags(self):
        api = _walk_api({BOX: [_row("D05700300001-00012", "FEB", "FEB1")],
                         "D05700300001-00012": [_row("Z00100300001-07630", "LArASIC", "U1")]})
        m1, m2 = self._mocked(api)
        with m1, m2:
            resp = self.client.get(PAGE)
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn("D05700300001-00012", html)
        self.assertIn('href="/hw/dev/part/Z00100300001-07630/"', html)
        self.assertIn("--depth: 1;", html)                     # nested node indented
        self.assertIn('<span class="es-yes">Yes</span>', html)  # uploaded
        self.assertIn('<span class="es-no">No</span>', html)    # certified
        self.assertIn("2 sub-components", html)
        # the template's own commentary must not leak into the page ({# #}
        # is single-line only — a multi-line one renders literally)
        self.assertNotIn("swapped in by htmx", html)

    def test_empty_tree_says_so(self):
        api = _walk_api({})
        m1, m2 = self._mocked(api)
        with m1, m2:
            html = self.client.get(PAGE).content.decode()
        self.assertIn("No sub-components.", html)

    def test_expired_link_renders_a_hint_at_200(self):
        # htmx 1.x won't swap non-2xx responses — errors must land in-page.
        with mock.patch("explore.views.mint_for", side_effect=FnalLinkRequired()):
            resp = self.client.get(PAGE)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("re-link", resp.content.decode())

    def test_walk_crash_renders_a_hint_at_200(self):
        api = mock.MagicMock()
        api.get_subcomponents.side_effect = RuntimeError("down")
        m1, m2 = self._mocked(api)
        with m1, m2, mock.patch("explore.views.subtree_rows",
                                side_effect=RuntimeError("down")):
            resp = self.client.get(PAGE)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Couldn’t load the sub-component tree", resp.content.decode())
