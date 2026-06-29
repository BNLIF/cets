"""Tests for the LArASIC HWDB sync (issue #14, rewired in #25 to flow
through hwdb.sync.sync_family). HWDB fetch is mocked.

    python manage.py test hwdb
"""

from __future__ import annotations

from unittest import mock

from django.test import TestCase
from django.urls import reverse

from cets.testutils import make_cets_user
from core.models import LArASIC
from hwdb import sync as sync_mod
from hwdb.fnal.bearer import FnalLinkRequired, FnalUnavailable
from hwdb.models import HwdbChip, LarasicSyncState


def _fake_sync_client(listing_pages):
    """Build a fake FnalDbApiClient: listing pages on ``_make_request``, no
    test types defined, no tests per chip. Suitable for asserting the
    legacy ``is_in_hwdb`` / ``LarasicSyncState`` behavior without exercising
    the deep test-fetch path.
    """
    listing_iter = iter(listing_pages)

    def _make_request(method, endpoint, data=None, params=None):
        return next(listing_iter)

    client = mock.MagicMock()
    client._make_request.side_effect = _make_request
    # Empty test-type catalog → sync_family bails after listing, but the
    # legacy LArASIC-flag stamper has already run (it doesn't depend on
    # deep fetches).
    client.get_test_types.return_value = {"data": [
        {"id": 1, "name": "RoomT QC Test"},
        {"id": 2, "name": "CryoT QC Test"},
    ]}
    client.get_tests.return_value = {"data": []}
    return client


class LarasicLegacyFlagsTest(TestCase):
    """Confirms the pre-HwdbChip behavior is preserved when sync_family
    handles family="larasic": is_in_hwdb, hwdb_checked_at, and
    LarasicSyncState.hwdb_only_count all still update.
    """
    def setUp(self):
        for sn in ("002-00001", "002-00002", "002-00003"):
            LArASIC.objects.create(serial_number=sn)

    def _run_sync(self, client):
        with mock.patch("hwdb.sync.FnalDbApiClient", return_value=client):
            list(sync_mod.sync_family(
                "larasic",
                part_type_id="D08100100003",
                api_base_url="https://x",
                bearer="b",
                workers=1,
            ))

    def test_marks_chips_in_and_out_of_hwdb(self):
        client = _fake_sync_client([{
            "data": [
                {"serial_number": "002-00001", "part_id": "P1"},
                {"serial_number": "002-00002", "part_id": "P2"},
                {"serial_number": "TEST", "part_id": "PT"},  # in HWDB, not local
            ],
            "pagination": {"pages": 1},
        }])
        self._run_sync(client)
        self.assertTrue(LArASIC.objects.get(serial_number="002-00001").is_in_hwdb)
        self.assertTrue(LArASIC.objects.get(serial_number="002-00002").is_in_hwdb)
        self.assertFalse(LArASIC.objects.get(serial_number="002-00003").is_in_hwdb)
        self.assertEqual(LarasicSyncState.get().hwdb_only_count, 1)
        # Every local chip got a hwdb_checked_at stamp.
        self.assertEqual(LArASIC.objects.filter(hwdb_checked_at__isnull=True).count(), 0)

    def test_pages_through_all_results(self):
        client = _fake_sync_client([
            {"data": [{"serial_number": "002-00001", "part_id": "P1"}],
             "pagination": {"pages": 2}},
            {"data": [{"serial_number": "002-00003", "part_id": "P3"}],
             "pagination": {"pages": 2}},
        ])
        self._run_sync(client)
        # Both pages of the listing consumed.
        self.assertEqual(client._make_request.call_count, 2)
        self.assertTrue(LArASIC.objects.get(serial_number="002-00001").is_in_hwdb)
        self.assertTrue(LArASIC.objects.get(serial_number="002-00003").is_in_hwdb)
        self.assertFalse(LArASIC.objects.get(serial_number="002-00002").is_in_hwdb)

    def test_sync_populates_hwdb_chip_rows(self):
        client = _fake_sync_client([{
            "data": [{"serial_number": "002-00001", "part_id": "P1"}],
            "pagination": {"pages": 1},
        }])
        self._run_sync(client)
        # The same sync writes the new HwdbChip mirror — that's the
        # rewire #25 is checking for.
        self.assertTrue(
            HwdbChip.objects.filter(family="larasic", serial_number="002-00001").exists()
        )


class LarasicViewTest(TestCase):
    def setUp(self):
        from datetime import datetime, timezone
        self.client.force_login(make_cets_user())
        LArASIC.objects.create(
            serial_number="002-00001", tray_id="B005T0011", is_in_hwdb=True,
            warm_tested_at=datetime(2025, 9, 24, 16, 59, 20, tzinfo=timezone.utc),
            cold_tested_at=datetime(2025, 9, 25, 10, 0, 0, tzinfo=timezone.utc),
        )
        LArASIC.objects.create(
            serial_number="002-00002", tray_id="B005T0011", is_in_hwdb=False,
            warm_tested_at=datetime(2025, 9, 24, 17, 0, 0, tzinfo=timezone.utc),
        )

    def test_summary_counts(self):
        resp = self.client.get(reverse("hwdb:larasic"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["total"], 2)
        self.assertEqual(resp.context["in_hwdb"], 1)
        self.assertEqual(resp.context["to_upload"], 1)

    def test_default_view_is_tray_grouping(self):
        resp = self.client.get(reverse("hwdb:larasic"))
        self.assertEqual(resp.context["view"], "tray")
        rows = list(resp.context["page_obj"])
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["tray_id"], "B005T0011")
        self.assertEqual(row["chip_count"], 2)
        self.assertEqual(row["rt_tested"], 2)
        self.assertEqual(row["ln_tested"], 1)
        # last_activity = max across all chips on the tray.
        self.assertEqual(row["last_activity"].day, 25)

    def test_femb_view_groups_by_femb(self):
        from core.models import FEMB
        f = FEMB.objects.create(version="IO-1865-1L", serial_number="00039")
        LArASIC.objects.filter(serial_number="002-00001").update(femb=f)
        resp = self.client.get(reverse("hwdb:larasic") + "?view=femb")
        self.assertEqual(resp.context["view"], "femb")
        rows = list(resp.context["page_obj"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["chip_count"], 1)

    def test_view_is_not_fnal_gated(self):
        # Reads the local flag only; no redirect to link.
        resp = self.client.get(reverse("hwdb:larasic"))
        self.assertEqual(resp.status_code, 200)

    def test_in_hwdb_only_card_shows_persisted_count(self):
        state = LarasicSyncState.get()
        state.hwdb_only_count = 7
        state.save()
        resp = self.client.get(reverse("hwdb:larasic"))
        self.assertEqual(resp.context["hwdb_only"], 7)
        self.assertContains(resp, "In HWDB only")


class LarasicSyncViewTest(TestCase):
    def setUp(self):
        self.client.force_login(make_cets_user())
        self.url = reverse("hwdb:larasic_sync")

    def test_get_not_allowed(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_unlinked_redirects_to_link_returning_to_summary(self):
        with mock.patch("hwdb.views.mint_for", side_effect=FnalLinkRequired()):
            resp = self.client.post(self.url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("hwdb:link"), resp["Location"])
        self.assertIn("larasic", resp["Location"])  # next = summary (url-encoded)

    def test_vault_unavailable_shows_error(self):
        with mock.patch("hwdb.views.mint_for", side_effect=FnalUnavailable()):
            resp = self.client.post(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "unavailable")

    def test_linked_sync_streams_and_updates_flags(self):
        LArASIC.objects.create(serial_number="002-00001")
        LArASIC.objects.create(serial_number="002-00009")
        with mock.patch("hwdb.views.mint_for", return_value="bearer"), mock.patch(
            "hwdb.views.sync_family",
            return_value=iter(["sync larasic: stub line\n"]),
        ) as sf:
            resp = self.client.post(self.url)
            self.assertEqual(resp.status_code, 200)
            body = b"".join(resp.streaming_content).decode()
        # Engine invoked with the expected family + part_type for prod.
        self.assertEqual(sf.call_args.args, ("larasic",))
        self.assertEqual(sf.call_args.kwargs["part_type_id"], "D08100100003")
        self.assertIn("stub line", body)

    def test_sync_on_dev_is_a_noop(self):
        # is_in_hwdb tracks PROD; a dev session must not touch it.
        chip = LArASIC.objects.create(serial_number="002-00001", is_in_hwdb=True)
        self.client.post(reverse("hwdb:set_instance"), {"instance": "dev"})
        with mock.patch("hwdb.views.mint_for") as mint, mock.patch(
            "hwdb.views.sync_family"
        ) as sf:
            resp = self.client.post(self.url)
        self.assertRedirects(resp, reverse("hwdb:larasic"))
        mint.assert_not_called()
        sf.assert_not_called()
        chip.refresh_from_db()
        self.assertTrue(chip.is_in_hwdb)  # untouched


class LarasicSyncButtonGatingTest(TestCase):
    def setUp(self):
        self.client.force_login(make_cets_user())

    def test_sync_button_on_prod(self):
        resp = self.client.get(reverse("hwdb:larasic"))
        self.assertContains(resp, "Sync HWDB")

    def test_no_sync_button_on_dev(self):
        self.client.post(reverse("hwdb:set_instance"), {"instance": "dev"})
        resp = self.client.get(reverse("hwdb:larasic"))
        self.assertNotContains(resp, "Sync HWDB")
        self.assertContains(resp, "Switch to")
