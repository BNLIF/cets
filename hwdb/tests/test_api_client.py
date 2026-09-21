"""Direct tests for hwdb.api_client.FnalDbApiClient.

Most callers mock at the ``_make_request`` boundary, so the client's own
plumbing (Session reuse, multipart uploads) wasn't covered by existing
tests. Adding the Session in 6f91e95 broke ``attach_test_image`` silently
because it still referenced the removed ``base_headers`` attribute and the
upload layer swallows the resulting AttributeError. These tests guard
against that class of regression.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import mock

from django.test import TestCase

from hwdb.api_client import FnalDbApiClient


class FnalDbApiClientSessionTest(TestCase):
    def test_auth_header_lives_on_session(self):
        api = FnalDbApiClient("https://example/api", "fake-bearer")
        self.assertEqual(
            api.session.headers.get("Authorization"),
            "Bearer fake-bearer",
        )
        # No leftover stateful attribute that callers might still reference.
        self.assertFalse(hasattr(api, "base_headers"))

    def test_attach_test_image_uses_session_post(self):
        """The multipart upload must go through ``self.session.post`` so the
        session's Authorization header applies. If it ever falls back to a
        bare ``requests.post`` with no auth, HWDB returns 401 and the upload
        silently drops the CSV (the orchestrator's ``except Exception`` makes
        the failure invisible).
        """
        api = FnalDbApiClient("https://example/api", "fake-bearer")
        with tempfile.TemporaryDirectory() as tmp:
            csv = Path(tmp) / "002_00001_RT.csv"
            csv.write_bytes(b"col1,col2\n1,2\n")

            fake_resp = mock.Mock()
            fake_resp.ok = True
            fake_resp.json.return_value = {"status": "OK", "image_id": 42}
            fake_resp.raise_for_status.return_value = None

            with mock.patch.object(api.session, "post", return_value=fake_resp) as post:
                body = api.attach_test_image(123, str(csv))

        self.assertEqual(body, {"status": "OK", "image_id": 42})
        post.assert_called_once()
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://example/api/component-tests/123/images")
        # files kwarg present, headers not overridden (so session auth applies).
        self.assertIn("files", kwargs)
        self.assertNotIn("headers", kwargs)

    def test_find_components_by_serial_returns_every_match(self):
        """#168: HWDB doesn't enforce unique serials — the resolver needs
        every holder; the older single-hit helper keeps its first-row rule."""
        api = FnalDbApiClient("https://example/api", "fake-bearer")
        fake_resp = mock.Mock(ok=True)
        fake_resp.json.return_value = {"data": [{"part_id": "T-1"}, {"part_id": "T-2"}]}
        with mock.patch.object(api.session, "request", return_value=fake_resp) as req:
            rows = api.find_components_by_serial("T", "HPK1")
            one = api.find_component_by_serial("T", "HPK1")
        self.assertEqual([r["part_id"] for r in rows], ["T-1", "T-2"])
        self.assertEqual(one, {"part_id": "T-1"})
        args, kwargs = req.call_args
        self.assertEqual((args[0], args[1], kwargs["params"]), ("GET", "https://example/api/component-types/T/components", {"serial_number": "HPK1"}))

    def test_patch_subcomponents_sends_vacated_positions_first(self):
        """HWDB applies the positions dict in order and refuses a PID still
        sitting in a later position ("already in use") — moving an item to
        an earlier-sorting position needs its old position vacated first
        (Hajime, dev 2026-09-20)."""
        api = FnalDbApiClient("https://example/api", "fake-bearer")
        fake_resp = mock.Mock(ok=True)
        fake_resp.json.return_value = {"status": "OK"}
        with mock.patch.object(api.session, "request", return_value=fake_resp) as req:
            api.patch_subcomponents("P-1", {"component": {"part_id": "P-1"}, "subcomponents": {
                "LAr 12": "S-4", "LAr 13": None, "LAr 14": "S-9"}})
        sent = req.call_args.kwargs["json"]
        self.assertEqual(list(sent["subcomponents"].items()), [("LAr 13", None), ("LAr 12", "S-4"), ("LAr 14", "S-9")])
        self.assertEqual(sent["component"], {"part_id": "P-1"})

    def test_post_test_type_hits_the_spec_endpoint_with_json_body(self):
        """Test-type creation (the ES auto-create) must POST the TestTypeIn
        body to ``component-types/{ptid}/test-types`` — the path is from the
        OpenAPI spec (v2.27.0RC), unwrapped by any official client."""
        api = FnalDbApiClient("https://example/api", "fake-bearer")
        payload = {"name": "ES", "specifications": {},
                   "component_type": {"part_type_id": "D00599800007"}}

        fake_resp = mock.Mock()
        fake_resp.ok = True
        fake_resp.json.return_value = {"status": "OK"}

        with mock.patch.object(api.session, "request", return_value=fake_resp) as req:
            body = api.post_test_type("D00599800007", payload)

        self.assertEqual(body, {"status": "OK"})
        args, kwargs = req.call_args
        self.assertEqual(args[0], "POST")
        self.assertEqual(args[1], "https://example/api/component-types/D00599800007/test-types")
        self.assertEqual(kwargs["json"], payload)


class FnalDbApiClientMemoTest(TestCase):
    """#172: ``memo=True`` answers a repeated type / sub-components GET from
    the client's own memo — a checklist page with four supercell tables
    read the same type eight times. Writes drop it; other GETs are never
    memoised; the caller gets its own copy."""

    def _api(self, memo=True):
        api = FnalDbApiClient("https://example/api", "b", memo=memo)
        self.calls = []

        def fake(method, url, headers=None, json=None, params=None):
            self.calls.append((method, url.split("/api/")[1]))
            r = mock.Mock(); r.ok = True
            r.json.return_value = {"status": "OK", "data": {"connectors": {"P1": "D004"}, "n": len(self.calls)}}
            return r
        api.session.request = fake
        return api

    def test_repeated_reads_hit_the_memo_and_writes_drop_it(self):
        api = self._api()
        a = api.get_component_type("Z104")
        b = api.get_component_type("Z104")
        api.get_subcomponents("Z104-00001"); api.get_subcomponents("Z104-00001")
        self.assertEqual(self.calls, [("GET", "component-types/Z104"), ("GET", "components/Z104-00001/subcomponents")])
        self.assertEqual(a, b)
        a["data"]["connectors"]["P1"] = "changed"      # the caller's copy, not the memo's
        self.assertEqual(api.get_component_type("Z104")["data"]["connectors"]["P1"], "D004")
        api.patch_subcomponents("Z104-00001", {"component": {"part_id": "Z104-00001"}, "subcomponents": {}})
        api.get_subcomponents("Z104-00001")
        self.assertEqual([c for c in self.calls if c[0] == "GET"][-1], ("GET", "components/Z104-00001/subcomponents"))
        self.assertEqual(len(self.calls), 4)                 # 2 reads, the write, the re-read

    def test_other_reads_and_memo_off_are_untouched(self):
        api = self._api()
        api.get_component("Z104-00001"); api.get_component("Z104-00001")
        self.assertEqual(len(self.calls), 2)
        api = self._api(memo=False)
        api.get_component_type("Z104"); api.get_component_type("Z104")
        self.assertEqual(len(self.calls), 2)
