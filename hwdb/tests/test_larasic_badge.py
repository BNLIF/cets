"""The 'in HWDB' badge on the core LArASIC pages (issue #15). Local-only —
reads the is_in_hwdb flag, no FNAL call.

    python manage.py test hwdb
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import ColdADC, LArASIC


class LarasicBadgeTest(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("guest", password="x"))

    def test_list_shows_in_hwdb_column(self):
        LArASIC.objects.create(serial_number="002-00001", is_in_hwdb=True)
        LArASIC.objects.create(serial_number="002-00002", is_in_hwdb=False)
        resp = self.client.get(reverse("larasic"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "In HWDB")
        self.assertContains(resp, ">yes<")
        self.assertContains(resp, ">no<")

    def test_coldadc_list_has_no_in_hwdb_column(self):
        ColdADC.objects.create(serial_number="2502-00001")
        resp = self.client.get(reverse("coldadc"))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "In HWDB")

    def test_detail_shows_in_hwdb(self):
        LArASIC.objects.create(serial_number="002-00001", is_in_hwdb=True)
        resp = self.client.get(reverse("larasic_detail", args=["002-00001"]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "In HWDB")
        self.assertContains(resp, "yes")
