import csv
import io
import json
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from surveillance.models import CaseReport, Disease, Outbreak, Patient

from .helpers import district, make_disease, make_patient, make_report, make_user

PASSWORD = "Test@12345"


class BaseViewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.kayonza = district("Kayonza")
        cls.huye = district("Huye")
        cls.admin = make_user("adm", "admin")
        cls.officer = make_user("off", "officer", cls.kayonza)
        cls.reporter = make_user("rep", "reporter", cls.kayonza)
        cls.other_officer = make_user("off2", "officer", cls.huye)
        cls.disease = make_disease("Test Fever", "TST")
        cls.p_kay = make_patient(cls.kayonza, "Kay Patient")
        cls.p_huye = make_patient(cls.huye, "Huye Patient")
        cls.r_kay = make_report(cls.p_kay, cls.disease, cls.kayonza, days_ago=1, reported_by=cls.reporter)
        cls.r_huye = make_report(cls.p_huye, cls.disease, cls.huye, days_ago=1)

    def login(self, user):
        self.client.login(username=user.username, password=PASSWORD)


class AnonymousAccessTests(BaseViewTest):
    def test_protected_pages_redirect_to_login(self):
        names = ["dashboard", "outbreak_map", "disease_list", "patient_list", "report_list", "outbreak_list",
                 "report_add", "patient_add", "report_export"]
        for name in names:
            url = reverse(name)
            response = self.client.get(url)
            self.assertRedirects(response, f"{reverse('login')}?next={url}", msg_prefix=name)

    def test_json_endpoints_refuse_anonymous(self):
        self.assertEqual(self.client.get(reverse("map_data")).status_code, 403)
        self.assertEqual(self.client.get(reverse("chart_data")).status_code, 403)

    def test_public_pages(self):
        self.assertEqual(self.client.get(reverse("home")).status_code, 200)
        self.assertEqual(self.client.get(reverse("login")).status_code, 200)

    def test_404_page(self):
        response = self.client.get("/no/such/page/")
        self.assertEqual(response.status_code, 404)


class AuthFlowTests(BaseViewTest):
    def test_login_and_logout(self):
        response = self.client.post(reverse("login"), {"username": "adm", "password": PASSWORD})
        self.assertRedirects(response, reverse("dashboard"))
        response = self.client.post(reverse("logout"))
        self.assertRedirects(response, reverse("home"))
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 302)

    def test_wrong_password(self):
        response = self.client.post(reverse("login"), {"username": "adm", "password": "wrong"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Wrong username or password")

    def test_every_main_page_loads_for_every_role(self):
        names = ["dashboard", "outbreak_map", "disease_list", "patient_list", "report_list", "outbreak_list",
                 "report_add", "patient_add"]
        for user in (self.admin, self.officer, self.reporter):
            self.client.logout()
            self.login(user)
            for name in names:
                self.assertEqual(self.client.get(reverse(name)).status_code, 200, f"{user.username} {name}")


class PermissionTests(BaseViewTest):
    def test_reporter_cannot_delete_or_export(self):
        self.login(self.reporter)
        self.assertEqual(self.client.get(reverse("report_delete", args=[self.r_kay.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("report_export")).status_code, 403)
        self.assertEqual(self.client.get(reverse("outbreak_declare")).status_code, 403)

    def test_officer_cannot_manage_diseases(self):
        self.login(self.officer)
        self.assertEqual(self.client.get(reverse("disease_list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("disease_add")).status_code, 403)
        self.assertEqual(self.client.get(reverse("disease_edit", args=[self.disease.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("disease_delete", args=[self.disease.pk])).status_code, 403)

    def test_district_scoping(self):
        self.login(self.officer)
        response = self.client.get(reverse("report_list"))
        self.assertContains(response, "Kay Patient")
        self.assertNotContains(response, "Huye Patient")
        self.assertEqual(self.client.get(reverse("report_detail", args=[self.r_huye.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("patient_detail", args=[self.p_huye.pk])).status_code, 404)

    def test_reporter_edits_only_own_report(self):
        self.login(self.reporter)
        self.assertEqual(self.client.get(reverse("report_edit", args=[self.r_kay.pk])).status_code, 200)
        other = make_report(make_patient(self.kayonza, "Another One"), self.disease, self.kayonza, days_ago=2)
        self.assertIn(self.client.get(reverse("report_edit", args=[other.pk])).status_code, (403, 404))

    def test_admin_sees_everything(self):
        self.login(self.admin)
        response = self.client.get(reverse("report_list"))
        self.assertContains(response, "Kay Patient")
        self.assertContains(response, "Huye Patient")


class CrudTests(BaseViewTest):
    def test_disease_crud_cycle(self):
        self.login(self.admin)
        data = {"name": "Brand New", "code": "BNW", "category": "other", "reporting": "weekly",
                "alert_multiplier": "2.0", "min_cases_for_alert": "3", "is_active": "on", "description": ""}
        response = self.client.post(reverse("disease_add"), data)
        self.assertEqual(response.status_code, 302)
        disease = Disease.objects.get(name="Brand New")
        data["min_cases_for_alert"] = "5"
        self.client.post(reverse("disease_edit", args=[disease.pk]), data)
        disease.refresh_from_db()
        self.assertEqual(disease.min_cases_for_alert, 5)
        self.assertContains(self.client.get(reverse("disease_delete", args=[disease.pk])), "Brand New")
        self.client.post(reverse("disease_delete", args=[disease.pk]))
        self.assertFalse(Disease.objects.filter(pk=disease.pk).exists())

    def test_invalid_disease_form_shows_errors(self):
        self.login(self.admin)
        response = self.client.post(reverse("disease_add"), {"name": "", "code": "", "alert_multiplier": "0.2"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "is-invalid")

    def test_delete_of_used_disease_is_blocked_with_message(self):
        self.login(self.admin)
        response = self.client.post(reverse("disease_delete", args=[self.disease.pk]), follow=True)
        self.assertTrue(Disease.objects.filter(pk=self.disease.pk).exists())
        self.assertContains(response, "cannot be deleted")

    def test_patient_create_sets_code_and_scopes_district(self):
        self.login(self.officer)
        response = self.client.post(reverse("patient_add"), {
            "full_name": "New Person", "age": "40", "gender": "F", "phone": "", "district": self.kayonza.pk})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Patient.objects.get(full_name="New Person").patient_code.startswith("P-"))
        response = self.client.post(reverse("patient_add"), {
            "full_name": "Wrong District", "age": "40", "gender": "F", "phone": "", "district": self.huye.pk})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Patient.objects.filter(full_name="Wrong District").exists())

    def test_report_create_records_reporter(self):
        self.login(self.reporter)
        today = timezone.localdate()
        response = self.client.post(reverse("report_add"), {
            "patient": self.p_kay.pk, "disease": self.disease.pk, "district": self.kayonza.pk,
            "case_type": "suspected", "status": "active", "date_onset": today.isoformat(),
            "date_reported": today.isoformat(), "notes": "test"})
        self.assertEqual(response.status_code, 302)
        report = CaseReport.objects.get(notes="test")
        self.assertEqual(report.reported_by, self.reporter)

    def test_report_future_date_shows_error(self):
        self.login(self.reporter)
        future = (timezone.localdate() + timedelta(days=3)).isoformat()
        response = self.client.post(reverse("report_add"), {
            "patient": self.p_kay.pk, "disease": self.disease.pk, "district": self.kayonza.pk,
            "case_type": "suspected", "status": "active", "date_onset": future, "date_reported": future})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(CaseReport.objects.filter(date_reported=future).exists())

    def test_report_delete_needs_confirmation_and_admin(self):
        self.login(self.admin)
        url = reverse("report_delete", args=[self.r_huye.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertTrue(CaseReport.objects.filter(pk=self.r_huye.pk).exists())
        self.client.post(url)
        self.assertFalse(CaseReport.objects.filter(pk=self.r_huye.pk).exists())


class DashboardAndJsonTests(BaseViewTest):
    def test_dashboard_numbers(self):
        self.login(self.admin)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.context["numbers"]["total"], 2)

    def test_chart_data_structure(self):
        self.login(self.admin)
        data = self.client.get(reverse("chart_data")).json()
        for key in ("by_district", "by_disease", "trend", "age_gender"):
            self.assertIn(key, data)

    def test_chart_data_filter_by_disease(self):
        self.login(self.admin)
        other = make_disease("Other One", "OTH")
        make_report(self.p_kay, other, self.kayonza, days_ago=3)
        data = self.client.get(reverse("chart_data"), {"disease": other.pk}).json()
        self.assertEqual(sum(data["by_district"]["data"]), 1)

    def test_map_data(self):
        self.login(self.admin)
        data = self.client.get(reverse("map_data")).json()
        self.assertEqual(len(data["districts"]), 30)
        kay = next(d for d in data["districts"] if d["name"] == "Kayonza")
        self.assertEqual(kay["total"], 1)
        self.assertEqual(data["total_cases"], 2)

    def test_geojson_matches_database_districts(self):
        from django.conf import settings
        path = settings.BASE_DIR / "static" / "geo" / "rwanda_districts.geojson"
        names = {f["properties"]["name"] for f in json.loads(path.read_text(encoding="utf-8"))["features"]}
        from locations.models import District
        self.assertEqual(names, set(District.objects.values_list("name", flat=True)))


class ExportTests(BaseViewTest):
    def test_csv_export_has_no_personal_data_and_is_scoped(self):
        self.login(self.officer)
        response = self.client.get(reverse("report_export"))
        self.assertEqual(response["Content-Type"], "text/csv")
        text = response.content.decode()
        self.assertNotIn("Kay Patient", text)
        rows = list(csv.reader(io.StringIO(text)))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][5], "Kayonza")


class OutbreakFlowTests(BaseViewTest):
    def test_declare_and_close(self):
        self.login(self.officer)
        today = timezone.localdate()
        for _ in range(3):
            make_report(make_patient(self.kayonza, "Flow Person"), self.disease, self.kayonza, days_ago=2)
        response = self.client.post(reverse("outbreak_declare"), {
            "disease": self.disease.pk, "district": self.kayonza.pk, "level": "alert",
            "start_date": today.isoformat(), "notes": "flow"})
        self.assertEqual(response.status_code, 302)
        outbreak = Outbreak.objects.get(notes="flow")
        self.assertEqual(outbreak.declared_by, self.officer)
        self.assertGreaterEqual(outbreak.cases.count(), 4)
        self.assertEqual(self.client.get(reverse("outbreak_detail", args=[outbreak.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("outbreak_close", args=[outbreak.pk])).status_code, 404)
        self.client.post(reverse("outbreak_close", args=[outbreak.pk]))
        outbreak.refresh_from_db()
        self.assertEqual(outbreak.status, "closed")
        self.assertEqual(outbreak.end_date, today)

    def test_duplicate_open_outbreak_rejected_by_form(self):
        self.login(self.officer)
        today = timezone.localdate().isoformat()
        data = {"disease": self.disease.pk, "district": self.kayonza.pk, "level": "alert", "start_date": today, "notes": "a"}
        self.client.post(reverse("outbreak_declare"), data)
        response = self.client.post(reverse("outbreak_declare"), {**data, "notes": "b"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Outbreak.objects.count(), 1)


class StaticFileTests(TestCase):
    def test_files_used_by_templates_exist(self):
        from django.conf import settings
        root = settings.BASE_DIR / "static"
        for rel in ("vendor/adminlte/css/adminlte.min.css", "vendor/adminlte/js/adminlte.min.js",
                    "vendor/bootstrap/bootstrap.bundle.min.js", "vendor/bootstrap-icons/bootstrap-icons.min.css",
                    "vendor/chartjs/chart.umd.js", "vendor/leaflet/leaflet.js", "vendor/leaflet/leaflet.css",
                    "css/app.css", "js/dashboard.js", "js/map.js", "geo/rwanda_districts.geojson", "img/logo.svg"):
            self.assertTrue((root / rel).exists(), rel)
