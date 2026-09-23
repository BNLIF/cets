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

    def test_mobile_drawer_scaffolding_renders(self):
        # #93: the aside doubles as the small-screen drawer — it carries a
        # mobile copy of the main nav and a scrim, and a page WITH a tree
        # must not be marked bare.
        html = self.client.get(reverse("explore:docs")).content.decode()
        self.assertIn('id="ex-scrim"', html)
        self.assertIn('class="ex-side-nav"', html)
        self.assertIn('<aside class="ex-side" id="ex-side"', html)

    def test_a_page_without_a_tree_marks_the_drawer_bare(self):
        # #93 safety net: a view that passes no sidebar still gets the nav
        # drawer on phones — the aside renders bare (hidden on desktop).
        from django.template.loader import render_to_string
        html = render_to_string("explore/base.html", {})
        self.assertIn('<aside class="ex-side ex-side-bare"', html)
        self.assertIn('class="ex-side-nav"', html)

    def test_anonymous_is_redirected_to_login(self):
        self.client.logout()
        resp = self.client.get(reverse("explore:docs"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("login", resp["Location"])


class PlotsGuideTest(TestCase):
    """The Plots page guide: the page's panes first, the Draw syntax as one
    section; the "? syntax" popover links it at #draw; the Docs page lists it."""
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("dg", "g@g.io", "pw"))

    def test_guide_renders_every_section(self):
        html = self.client.get(reverse("explore:docs_plots")).content.decode()
        for anchor in ("data", "cuts", "series", "chart", "share", "draw"):
            self.assertIn(f'<h2 id="{anchor}">', html)
        for anchor in ("expr", "keys", "index", "values", "ops", "funcs", "lists", "select", "bins", "option", "examples", "root"):
            self.assertIn(f'<h3 id="{anchor}">', html)
        self.assertIn("<code>00120..06000</code>", html)
        self.assertIn("<code>TTree::Draw(expression, selection, option)</code>", html)
        self.assertIn("<code>V[][2]</code> or <code>V[*][2]</code>", html)
        self.assertIn("<code>expr &gt;&gt; hpk(50, 30, 60)</code>", html)
        self.assertIn('class="eh-nav-item active" href="/hw/docs/"', html)

    def test_docs_page_and_popover_link_the_guide(self):
        url = reverse("explore:docs_plots")
        self.assertEqual(url, "/hw/docs/plots/")
        docs = self.client.get(reverse("explore:docs")).content.decode()
        self.assertIn(f'<a class="dc-row" href="{url}">', docs)
        self.assertIn("Plots page", docs)

    def test_anonymous_is_redirected_to_login(self):
        self.client.logout()
        resp = self.client.get(reverse("explore:docs_plots"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("login", resp["Location"])


class ChecklistEditorGuideTest(TestCase):
    """The checklist editor's header links a full guide page; the Docs page
    lists it under HWDB Explorer."""
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("cg", "c@c.io", "pw"))

    def test_guide_renders_every_section(self):
        html = self.client.get(reverse("explore:docs_checklist_editor")).content.decode()
        for anchor in ("checklist", "sections", "placing", "types", "number", "table", "steps", "static", "pid", "plot", "assembly", "text", "json", "fill"):
            self.assertIn(f'<h2 id="{anchor}">', html)
        self.assertIn("<code>Total = C1 + C2*(C3/C4)</code>", html)
        self.assertIn("<pre>Board 1 @ 4.5, 8\n", html)
        self.assertIn('class="eh-nav-item active" href="/hw/docs/"', html)

    def test_docs_page_links_the_guide(self):
        url = reverse("explore:docs_checklist_editor")
        self.assertEqual(url, "/hw/docs/checklist-editor/")
        docs = self.client.get(reverse("explore:docs")).content.decode()
        self.assertIn(f'<a class="dc-row" href="{url}">', docs)
        self.assertIn("Checklist editor", docs)

    def test_anonymous_is_redirected_to_login(self):
        self.client.logout()
        resp = self.client.get(reverse("explore:docs_checklist_editor"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("login", resp["Location"])
