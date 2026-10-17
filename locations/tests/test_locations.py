from django.test import TestCase
from django.urls import reverse

from locations.models import District
from surveillance.tests.helpers import district, make_user


class DistrictViewTests(TestCase):
    def test_login_required(self):
        self.assertEqual(self.client.get(reverse("district_list")).status_code, 302)

    def test_list_and_detail(self):
        make_user("a", "admin")
        self.client.login(username="a", password="Test@12345")
        response = self.client.get(reverse("district_list"))
        self.assertContains(response, "Kayonza")
        d = district("Ngoma")
        self.assertEqual(self.client.get(reverse("district_detail", args=[d.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("district_detail", args=[99999])).status_code, 404)

    def test_province_filter(self):
        make_user("a", "admin")
        self.client.login(username="a", password="Test@12345")
        d = District.objects.get(name="Huye")
        response = self.client.get(reverse("district_list"), {"province": d.province_id})
        self.assertContains(response, "Huye")
        self.assertNotContains(response, "Kayonza")
