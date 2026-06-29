"""Tests for /hwdb/dashboard/ (issue #23). Covers the HwdbChip mirror,
the sync_family() engine, the dashboard GET, and the streaming sync view.

    python manage.py test hwdb.tests.test_dashboard
"""

from __future__ import annotations

from datetime import datetime, timezone as dt_tz
from types import SimpleNamespace
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from cets.testutils import make_cets_user
from core.models import LArASIC
from hwdb import sync as sync_mod
from hwdb.fnal.bearer import FnalLinkRequired, FnalUnavailable
from hwdb.models import HwdbChip, HwdbSyncState
from hwdb.views import _larasic_consistency_delta


def _list_page(serials, pages=1, part_ids=None):
    """Build one page of the components-listing response shape."""
    part_ids = part_ids or {}
    return {
        "data": [
            {"serial_number": sn, "part_id": part_ids.get(sn, f"PID{sn}")}
            for sn in serials
        ],
        "pagination": {"pages": pages},
    }


def _deep_body(date=None, time="00:00", created=None, env_id=1):
    """Build a deep-endpoint response (``/components/{id}/tests/{type_id}``).

    Pass ``date="YYYY/MM/DD"`` for a normal lab-time record. Pass ``created``
    instead for a placeholder record with empty ``test_data`` (ADR-0009).
    """
    if not date and not created:
        return {"data": []}
    entry = {"id": 100 + env_id, "test_type": {"id": env_id, "name": "x"}}
    entry["test_data"] = {"Test Date": date, "Test Time": time} if date else {}
    if created:
        entry["created"] = created
    return {"data": [entry]}


def _test_type_catalog():
    """Resolver response for /component-types/{pt}/test-types."""
    return {"data": [
        {"id": 36, "name": "RoomT QC Test"},
        {"id": 35, "name": "CryoT QC Test"},
    ]}


def _tests_body(rt=None, ln=None, rt_created=None, ln_created=None):
    """Convenience: build a {(part_id, test_type_id): body} fixture for the
    deep endpoint. ``rt``/``ln`` are ``(date, time)`` tuples; ``*_created``
    is an ISO string for the empty-test_data fallback.
    """
    return {
        36: _deep_body(date=rt[0] if rt else None,
                       time=rt[1] if rt else "00:00",
                       created=rt_created, env_id=36),
        35: _deep_body(date=ln[0] if ln else None,
                       time=ln[1] if ln else "00:00",
                       created=ln_created, env_id=35),
    }


class HwdbChipModelTest(TestCase):
    def test_unique_per_family_and_serial(self):
        from django.db import IntegrityError, transaction

        now = datetime(2026, 6, 1, 10, 0, tzinfo=dt_tz.utc)
        HwdbChip.objects.create(
            family="coldadc", serial_number="2502-00001",
            part_id="PID1", part_type_id="D08100200002", last_seen_at=now,
        )
        # Same serial under a different family is fine.
        HwdbChip.objects.create(
            family="coldata", serial_number="2502-00001",
            part_id="PID1", part_type_id="D08100300003", last_seen_at=now,
        )
        # Same family+serial collides.
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                HwdbChip.objects.create(
                    family="coldadc", serial_number="2502-00001",
                    part_id="PID2", part_type_id="D08100200002", last_seen_at=now,
                )


class SyncFamilyTest(TestCase):
    """Unit-test the engine. Patches FnalDbApiClient so no network is touched."""

    def _patched_client(self, listing_pages, tests_by_part_id):
        """Build a fake FnalDbApiClient.

        - ``_make_request`` returns successive listing pages (one per call).
        - ``get_test_types`` returns the standard RT/LN catalog.
        - ``get_tests`` is called with ``(part_id, test_type_id=…)`` and
          returns a body keyed by ``tests_by_part_id[part_id][test_type_id]``.
        """
        listing_iter = iter(listing_pages)

        def _make_request(method, endpoint, data=None, params=None):
            return next(listing_iter)

        def _get_tests(part_id, test_type_id=None, history=False):
            by_type = tests_by_part_id.get(part_id, {})
            return by_type.get(test_type_id, {"data": []})

        client = mock.MagicMock()
        client._make_request.side_effect = _make_request
        client.get_test_types.return_value = _test_type_catalog()
        client.get_tests.side_effect = _get_tests
        return client

    def test_new_chips_inserted_with_test_dates(self):
        listing = [_list_page(["2502-00001", "2502-00002"], pages=1)]
        tests = {
            "PID2502-00001": _tests_body(rt=("2026/03/01", "10:30:00")),
            "PID2502-00002": _tests_body(rt=("2026/03/05", "11:00:00"),
                                         ln=("2026/04/01", "14:00:00")),
        }
        fake = self._patched_client(listing, tests)
        with mock.patch("hwdb.sync.FnalDbApiClient", return_value=fake):
            list(sync_mod.sync_family(
                "coldadc",
                part_type_id="D08100200002",
                api_base_url="https://x",
                bearer="b",
                workers=2,
            ))
        self.assertEqual(HwdbChip.objects.filter(family="coldadc").count(), 2)
        c1 = HwdbChip.objects.get(serial_number="2502-00001")
        self.assertIsNotNone(c1.latest_rt_test_at)
        self.assertIsNone(c1.latest_ln_test_at)
        c2 = HwdbChip.objects.get(serial_number="2502-00002")
        self.assertIsNotNone(c2.latest_rt_test_at)
        self.assertIsNotNone(c2.latest_ln_test_at)
        # Sync-state row is populated.
        state = HwdbSyncState.for_family("coldadc")
        self.assertEqual(state.chips_total, 2)
        self.assertEqual(state.chips_new, 2)
        self.assertIsNotNone(state.finished_at)

    def test_known_chips_skip_get_tests(self):
        # Pre-populate one chip.
        now = datetime(2026, 5, 1, 0, 0, tzinfo=dt_tz.utc)
        HwdbChip.objects.create(
            family="coldadc", serial_number="2502-00001",
            part_id="PID2502-00001", part_type_id="D08100200002", last_seen_at=now,
        )
        listing = [_list_page(["2502-00001", "2502-00002"], pages=1)]
        tests = {
            "PID2502-00002": _tests_body(rt=("2026/03/05", "11:00:00")),
            # PID2502-00001 must NOT be queried.
        }
        fake = self._patched_client(listing, tests)
        with mock.patch("hwdb.sync.FnalDbApiClient", return_value=fake):
            list(sync_mod.sync_family(
                "coldadc", part_type_id="D08100200002",
                api_base_url="https://x", bearer="b", workers=2,
            ))
        # get_tests called only for the new chip — twice (once per env);
        # the known chip is skipped entirely.
        called_part_ids = {c.args[0] for c in fake.get_tests.call_args_list}
        self.assertEqual(called_part_ids, {"PID2502-00002"})
        # last_seen_at advanced for the known chip too.
        c1 = HwdbChip.objects.get(serial_number="2502-00001")
        self.assertGreater(c1.last_seen_at, now)
        state = HwdbSyncState.for_family("coldadc")
        self.assertEqual(state.chips_new, 1)
        self.assertEqual(state.chips_total, 2)

    def test_force_full_refetches_known_chips(self):
        now = datetime(2026, 5, 1, 0, 0, tzinfo=dt_tz.utc)
        HwdbChip.objects.create(
            family="coldadc", serial_number="2502-00001",
            part_id="PID2502-00001", part_type_id="D08100200002",
            last_seen_at=now,
        )
        listing = [_list_page(["2502-00001"], pages=1)]
        tests = {
            "PID2502-00001": _tests_body(
                rt=("2026/03/01", "10:30:00"),
                ln=("2026/04/01", "14:00:00"),
            )
        }
        fake = self._patched_client(listing, tests)
        with mock.patch("hwdb.sync.FnalDbApiClient", return_value=fake):
            list(sync_mod.sync_family(
                "coldadc", part_type_id="D08100200002",
                api_base_url="https://x", bearer="b",
                force_full=True, workers=1,
            ))
        called_part_ids = {c.args[0] for c in fake.get_tests.call_args_list}
        self.assertEqual(called_part_ids, {"PID2502-00001"})
        c1 = HwdbChip.objects.get(serial_number="2502-00001")
        self.assertIsNotNone(c1.latest_rt_test_at)
        self.assertIsNotNone(c1.latest_ln_test_at)

    def test_empty_test_data_falls_back_to_created(self):
        """ADR-0009: a recognized test with empty test_data uses the top-level
        ``created`` timestamp instead of dropping the chip from the chart.
        """
        listing = [_list_page(["2417-02192"], pages=1)]
        tests = {
            "PID2417-02192": _tests_body(
                rt_created="2026-05-27T14:10:33.115371-05:00"
            ),
        }
        fake = self._patched_client(listing, tests)
        with mock.patch("hwdb.sync.FnalDbApiClient", return_value=fake):
            list(sync_mod.sync_family(
                "coldata", part_type_id="D08100300003",
                api_base_url="https://x", bearer="b", workers=1,
            ))
        c = HwdbChip.objects.get(serial_number="2417-02192")
        self.assertIsNotNone(c.latest_rt_test_at)
        self.assertEqual(c.latest_rt_test_at.year, 2026)
        self.assertEqual(c.latest_rt_test_at.month, 5)
        self.assertEqual(c.latest_rt_test_at.day, 27)
        self.assertIsNone(c.latest_ln_test_at)

    def test_lab_time_preferred_over_created(self):
        """When both Test Date and ``created`` are present, Test Date wins."""
        listing = [_list_page(["SN1"], pages=1)]
        tests = {
            "PIDSN1": {36: {"data": [{
                "id": 1,
                "test_data": {"Test Date": "2026/03/01", "Test Time": "10:30:00"},
                "created": "2026-05-27T14:10:33-05:00",
            }]}},
        }
        fake = self._patched_client(listing, tests)
        with mock.patch("hwdb.sync.FnalDbApiClient", return_value=fake):
            list(sync_mod.sync_family(
                "coldadc", part_type_id="D08100200002",
                api_base_url="https://x", bearer="b", workers=1,
            ))
        c = HwdbChip.objects.get(serial_number="SN1")
        self.assertEqual(c.latest_rt_test_at.month, 3)  # lab time, not May upload.

    def test_hh_mm_time_format_accepted(self):
        """COLDATA records use HH:MM (no seconds) — we ignore Test Time anyway,
        but the parse must not crash on the shorter format.
        """
        listing = [_list_page(["SN1"], pages=1)]
        tests = {"PIDSN1": {36: _deep_body(date="2026/05/20", time="20:01", env_id=36)}}
        fake = self._patched_client(listing, tests)
        with mock.patch("hwdb.sync.FnalDbApiClient", return_value=fake):
            list(sync_mod.sync_family(
                "coldata", part_type_id="D08100300003",
                api_base_url="https://x", bearer="b", workers=1,
            ))
        c = HwdbChip.objects.get(serial_number="SN1")
        self.assertEqual(c.latest_rt_test_at.month, 5)
        self.assertEqual(c.latest_rt_test_at.day, 20)

    def test_chunked_persistence_survives_mid_run_abort(self):
        """If the streaming worker is killed mid-fetch (gunicorn timeout in
        prod), the chips we've already flushed must persist so a re-click
        resumes via skip-known-serials. Simulated by aborting the generator
        partway through.
        """
        # 500 chips to fetch; FLUSH_EVERY is 200 so we expect persisted
        # rows even if we abort after consuming ~half the progress stream.
        listing = [_list_page([f"SN{i:04d}" for i in range(500)], pages=1)]
        tests = {
            f"PIDSN{i:04d}": {36: _deep_body(date="2026/03/01", env_id=36)}
            for i in range(500)
        }
        fake = self._patched_client(listing, tests)
        with mock.patch("hwdb.sync.FnalDbApiClient", return_value=fake):
            gen = sync_mod.sync_family(
                "coldadc", part_type_id="D08100200002",
                api_base_url="https://x", bearer="b", workers=4,
            )
            for line in gen:
                if "300/500" in line:
                    gen.close()
                    break
        # At least one flush boundary (200) must have landed before close().
        persisted = HwdbChip.objects.filter(family="coldadc").count()
        self.assertGreaterEqual(persisted, 200)

    def test_disappeared_chips_counted_but_not_deleted(self):
        now = datetime(2026, 5, 1, 0, 0, tzinfo=dt_tz.utc)
        HwdbChip.objects.create(
            family="coldadc", serial_number="2502-OLD",
            part_id="x", part_type_id="D08100200002", last_seen_at=now,
        )
        listing = [_list_page([], pages=1)]
        fake = self._patched_client(listing, {})
        with mock.patch("hwdb.sync.FnalDbApiClient", return_value=fake):
            list(sync_mod.sync_family(
                "coldadc", part_type_id="D08100200002",
                api_base_url="https://x", bearer="b", workers=1,
            ))
        # Row preserved.
        self.assertTrue(HwdbChip.objects.filter(serial_number="2502-OLD").exists())
        state = HwdbSyncState.for_family("coldadc")
        self.assertEqual(state.chips_disappeared, 1)


class DashboardViewTest(TestCase):
    def setUp(self):
        self.client.force_login(make_cets_user("g"))

    def test_dashboard_renders_with_no_data(self):
        resp = self.client.get(reverse("hwdb:dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "ColdADC")
        self.assertContains(resp, "COLDATA")
        self.assertContains(resp, "Never synced")

    def test_dashboard_card_numbers_reflect_hwdb_chip(self):
        now = datetime(2026, 5, 1, 0, 0, tzinfo=dt_tz.utc)
        HwdbChip.objects.create(
            family="coldadc", serial_number="A",
            part_id="x", part_type_id="D08100200002", last_seen_at=now,
            latest_ln_test_at=now,
        )
        HwdbChip.objects.create(
            family="coldadc", serial_number="B",
            part_id="x", part_type_id="D08100200002", last_seen_at=now,
        )
        resp = self.client.get(reverse("hwdb:dashboard"))
        # 2 total, 1 LN-tested.
        self.assertContains(resp, ">2<")  # in-HWDB count
        self.assertContains(resp, ">1<")  # LN-tested count


class LarasicConsistencyDeltaTest(TestCase):
    """The Δ pill on the LArASIC card (issue #27). Counts BNL-tested chips
    that the HwdbChip mirror has not seen as tested — the upload backlog.
    """
    def setUp(self):
        self.client.force_login(make_cets_user("g"))

    def _make_chip(self, sn, *, warm=None, cold=None):
        from datetime import datetime, timezone as dt_tz
        return LArASIC.objects.create(
            serial_number=sn,
            warm_tested_at=datetime(2026, 5, 1, tzinfo=dt_tz.utc) if warm else None,
            cold_tested_at=datetime(2026, 5, 2, tzinfo=dt_tz.utc) if cold else None,
        )

    def _make_mirror(self, sn, *, rt=None, ln=None):
        now = datetime(2026, 5, 10, tzinfo=dt_tz.utc)
        return HwdbChip.objects.create(
            family="larasic", serial_number=sn, part_id="x",
            part_type_id="D08100100003", last_seen_at=now,
            latest_rt_test_at=now if rt else None,
            latest_ln_test_at=now if ln else None,
        )

    def test_delta_counts_unmirrored_tests(self):
        # Chip A: warm + cold locally, mirror knows both → no delta.
        self._make_chip("A", warm=True, cold=True)
        self._make_mirror("A", rt=True, ln=True)
        # Chip B: warm + cold locally, mirror missing both → contributes 1 to each.
        self._make_chip("B", warm=True, cold=True)
        # Chip C: warm-only locally, mirror has RT → no delta.
        self._make_chip("C", warm=True)
        self._make_mirror("C", rt=True)
        # Chip D: cold locally, mirror has nothing → delta_ln += 1, delta_rt unchanged.
        self._make_chip("D", cold=True)
        d = _larasic_consistency_delta()
        self.assertEqual(d, {"delta_rt": 1, "delta_ln": 2})

    def test_toggle_button_renders_on_larasic_card(self):
        """The 3 cards have the same default layout. LArASIC additionally has
        a 'Show consistency check' toggle that reveals the pills on click.
        """
        resp = self.client.get(reverse("hwdb:dashboard"))
        # Toggle button is on the LArASIC card only.
        self.assertContains(resp, 'class="btn btn-sm btn-ghost consistency-toggle"')
        self.assertContains(resp, 'data-card="larasic"')
        # The pill container exists but is hidden by default.
        self.assertContains(resp, 'class="consistency-pills"')
        self.assertContains(resp, 'style="display: none;')

    def test_pill_values_reflect_backlog(self):
        """Pills carry the right counts whether they're displayed or not —
        the JS toggle is purely cosmetic. The values must be correct.
        """
        self._make_chip("B", warm=True, cold=True)
        resp = self.client.get(reverse("hwdb:dashboard"))
        body = resp.content.decode()
        self.assertIn("Δ 1 warm not in HWDB", body)
        self.assertIn("Δ 1 cold not in HWDB", body)

    def test_no_toggle_on_coldadc_or_coldata_cards(self):
        """Only LArASIC has the consistency-check toggle — ColdADC and COLDATA
        have no BNL-local test data to compare against.
        """
        resp = self.client.get(reverse("hwdb:dashboard"))
        body = resp.content.decode()
        # The toggle button is rendered only for LArASIC.
        self.assertEqual(body.count('class="btn btn-sm btn-ghost consistency-toggle"'), 1)
        self.assertNotIn('data-card="coldadc" style="font-size: 11px', body)
        self.assertNotIn('data-card="coldata" style="font-size: 11px', body)


class DashboardSyncViewTest(TestCase):
    def setUp(self):
        self.client.force_login(make_cets_user("g"))
        self.url = reverse("hwdb:dashboard_sync", args=["coldadc"])

    def test_dev_session_is_a_noop_redirect(self):
        self.client.post(reverse("hwdb:set_instance"), {"instance": "dev"})
        with mock.patch("hwdb.views.mint_for") as mint, mock.patch(
            "hwdb.sync.sync_family"
        ) as sf:
            resp = self.client.post(self.url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("hwdb:dashboard"), resp["Location"])
        mint.assert_not_called()
        sf.assert_not_called()

    def test_unlinked_redirects_to_link_returning_to_dashboard(self):
        with mock.patch("hwdb.views.mint_for", side_effect=FnalLinkRequired()):
            resp = self.client.post(self.url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("hwdb:link"), resp["Location"])
        self.assertIn("dashboard", resp["Location"])

    def test_vault_unavailable_renders_error(self):
        with mock.patch("hwdb.views.mint_for", side_effect=FnalUnavailable()):
            resp = self.client.post(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "unavailable")

    def test_unknown_family_redirects(self):
        url = reverse("hwdb:dashboard_sync", args=["nonsense"])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)

    def test_force_full_flag_propagates_to_engine(self):
        """POSTing ``force=full`` should call ``sync_family(force_full=True)``."""
        captured = {}

        def _spy(family, **kwargs):
            captured.update(kwargs)
            return iter([])

        with mock.patch("hwdb.views.mint_for", return_value="bearer"), mock.patch(
            "hwdb.views.sync_family", side_effect=_spy
        ):
            resp = self.client.post(self.url, {"force": "full"})
            b"".join(resp.streaming_content)
        self.assertTrue(captured["force_full"])

    def test_default_sync_keeps_skip_policy(self):
        """Without ``force=full``, ``force_full`` is False so known chips skip."""
        captured = {}

        def _spy(family, **kwargs):
            captured.update(kwargs)
            return iter([])

        with mock.patch("hwdb.views.mint_for", return_value="bearer"), mock.patch(
            "hwdb.views.sync_family", side_effect=_spy
        ):
            resp = self.client.post(self.url)
            b"".join(resp.streaming_content)
        self.assertFalse(captured["force_full"])

    def test_coldata_sync_uses_coldata_part_type(self):
        """The same engine is reused for COLDATA — the only difference is the
        part_type_id pulled from HWDB_PROFILES.
        """
        captured = {}

        def _spy(family, **kwargs):
            captured.update(kwargs)
            captured["family"] = family
            return iter([f"sync {family}: stubbed\n"])

        url = reverse("hwdb:dashboard_sync", args=["coldata"])
        with mock.patch("hwdb.views.mint_for", return_value="bearer"), mock.patch(
            "hwdb.views.sync_family", side_effect=_spy
        ):
            resp = self.client.post(url)
            self.assertEqual(resp.status_code, 200)
            b"".join(resp.streaming_content)
        self.assertEqual(captured["family"], "coldata")
        self.assertEqual(captured["part_type_id"], "D08100300003")

    def test_linked_sync_streams_progress(self):
        # Consume the generator body INSIDE the patch context — the streaming
        # response is lazy, so unwinding the mock before reading streaming_content
        # would let the real sync_family run.
        with mock.patch("hwdb.views.mint_for", return_value="bearer"), mock.patch(
            "hwdb.views.sync_family",
            return_value=iter(["line-1\n", "line-2\n"]),
        ):
            resp = self.client.post(self.url)
            self.assertEqual(resp.status_code, 200)
            body = b"".join(resp.streaming_content).decode()
        self.assertIn("line-1", body)
        self.assertIn("line-2", body)
