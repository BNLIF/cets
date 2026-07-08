"""Tests for the Docs page: curated external HWDB documentation links.

    python manage.py test explore
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class DocsViewTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("dc", "d@d.io", "pw")
        self.client.force_login(self.user)

    def test_renders_key_links(self):
        html = self.client.get(reverse("explore:docs")).content.decode()
        self.assertIn("https://dune.github.io/computing-HWDB/index.html", html)
        self.assertIn("/apidoc/redoc", html)
        self.assertIn("https://edms.cern.ch/document/3416341", html)
        # navbar entry present and highlighted; Browse must not be
        self.assertIn(">Docs</a>", html)
        self.assertNotIn('active" href="/hw/browse/"', html)

    def test_api_doc_links_follow_instance(self):
        prod = self.client.get(reverse("explore:docs")).content.decode()
        self.assertIn("/cdb/apidoc/redoc", prod)
        dev = self.client.get("/hw/dev/docs/").content.decode()
        self.assertIn("/cdbdev/apidoc/redoc", dev)

    def test_anonymous_is_redirected_to_login(self):
        self.client.logout()
        resp = self.client.get(reverse("explore:docs"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("login", resp["Location"])
