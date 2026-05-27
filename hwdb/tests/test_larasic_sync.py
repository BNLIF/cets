"""Tests for the LArASIC HWDB sync (issue #14). HWDB fetch is mocked.

    python manage.py test hwdb
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import LArASIC
from hwdb import views
from hwdb.fnal.bearer import FnalLinkRequired, FnalUnavailable
from hwdb.models import LarasicSyncState


def _fake_client(pages):
    """Client whose _make_request returns successive page payloads."""
    return SimpleNamespace(_make_request=mock.Mock(side_effect=pages))


class SyncLogicTest(TestCase):
    def setUp(self):
        for sn in ("002-00001", "002-00002", "002-00003"):
            LArASIC.objects.create(serial_number=sn)

    def test_marks_chips_in_and_out_of_hwdb(self):
        client = _fake_client([
            {
                "data": [
                    {"serial_number": "002-00001"},
                    {"serial_number": "002-00002"},
                    {"serial_number": "TEST", "part_id": "x"},  # no real serial elsewhere
                ],
                "pagination": {"pages": 1},
            }
        ])
        total, in_hwdb, to_upload, hwdb_only = views._sync_larasic(client, "D08100100003")
        self.assertEqual((total, in_hwdb, to_upload), (3, 2, 1))
        # "TEST" is in HWDB but not local -> hwdb_only = 1, persisted.
        self.assertEqual(hwdb_only, 1)
        self.assertEqual(LarasicSyncState.get().hwdb_only_count, 1)
        self.assertTrue(LArASIC.objects.get(serial_number="002-00001").is_in_hwdb)
        self.assertFalse(LArASIC.objects.get(serial_number="002-00003").is_in_hwdb)
        # All chips stamped with a check time.
        self.assertEqual(LArASIC.objects.filter(hwdb_checked_at__isnull=True).count(), 0)

    def test_pages_through_all_results(self):
        client = _fake_client([
            {"data": [{"serial_number": "002-00001"}], "pagination": {"pages": 2}},
            {"data": [{"serial_number": "002-00003"}], "pagination": {"pages": 2}},
        ])
        total, in_hwdb, to_upload, hwdb_only = views._sync_larasic(client, "pt")
        self.assertEqual(client._make_request.call_count, 2)
        self.assertEqual((total, in_hwdb, to_upload, hwdb_only), (3, 2, 1, 0))


class LarasicViewTest(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("guest", password="x"))
        LArASIC.objects.create(serial_number="002-00001", is_in_hwdb=True)
        LArASIC.objects.create(serial_number="002-00002", is_in_hwdb=False)

    def test_summary_counts(self):
        resp = self.client.get(reverse("hwdb:larasic"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["total"], 2)
        self.assertEqual(resp.context["in_hwdb"], 1)
        self.assertEqual(resp.context["to_upload"], 1)

    def test_default_shows_to_upload(self):
        resp = self.client.get(reverse("hwdb:larasic"))
        chips = list(resp.context["page_obj"])
        self.assertEqual([c.serial_number for c in chips], ["002-00002"])

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
        self.client.force_login(get_user_model().objects.create_user("guest", password="x"))
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

    def test_linked_sync_updates_flags_and_redirects(self):
        LArASIC.objects.create(serial_number="002-00001")
        LArASIC.objects.create(serial_number="002-00009")
        page = {"data": [{"serial_number": "002-00001"}], "pagination": {"pages": 1}}
        with mock.patch("hwdb.views.mint_for", return_value="bearer"), mock.patch(
            "hwdb.api_client.FnalDbApiClient._make_request", return_value=page
        ):
            resp = self.client.post(self.url)
        self.assertRedirects(resp, reverse("hwdb:larasic"))
        self.assertTrue(LArASIC.objects.get(serial_number="002-00001").is_in_hwdb)
        self.assertFalse(LArASIC.objects.get(serial_number="002-00009").is_in_hwdb)

    def test_sync_on_dev_is_a_noop(self):
        # is_in_hwdb tracks PROD; a dev session must not touch it.
        chip = LArASIC.objects.create(serial_number="002-00001", is_in_hwdb=True)
        self.client.post(reverse("hwdb:set_instance"), {"instance": "dev"})
        with mock.patch("hwdb.views.mint_for") as mint, mock.patch(
            "hwdb.api_client.FnalDbApiClient._make_request"
        ) as req:
            resp = self.client.post(self.url)
        self.assertRedirects(resp, reverse("hwdb:larasic"))
        mint.assert_not_called()
        req.assert_not_called()
        chip.refresh_from_db()
        self.assertTrue(chip.is_in_hwdb)  # untouched


class LarasicSyncButtonGatingTest(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("guest", password="x"))

    def test_sync_button_on_prod(self):
        resp = self.client.get(reverse("hwdb:larasic"))
        self.assertContains(resp, "Sync with HWDB")

    def test_no_sync_button_on_dev(self):
        self.client.post(reverse("hwdb:set_instance"), {"instance": "dev"})
        resp = self.client.get(reverse("hwdb:larasic"))
        self.assertNotContains(resp, "Sync with HWDB")
        self.assertContains(resp, "Switch to")
