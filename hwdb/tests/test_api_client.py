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
