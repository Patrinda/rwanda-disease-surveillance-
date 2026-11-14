import json

from django.urls import reverse

from forecasting.models import ApiToken, Prediction
from surveillance.models import CaseReport

from .base import ForecastTestCase, token_header


class ApiAccessTests(ForecastTestCase):
    def test_no_token_is_rejected(self):
        self.assertEqual(self.client.get("/api/v1/status/").status_code, 401)

    def test_wrong_token_is_rejected(self):
        self.assertEqual(self.client.get("/api/v1/status/", HTTP_AUTHORIZATION="Token nope").status_code, 401)

    def test_status_with_token(self):
        response = self.client.get("/api/v1/status/", **token_header(self.admin))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["model"]["version"], self.model_run.version)

    def test_browser_session_can_read_but_not_post(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get("/api/v1/status/").status_code, 200)
        self.assertEqual(self.client.post("/api/v1/reports/", "{}", content_type="application/json").status_code, 401)

    def test_wrong_method(self):
        self.assertEqual(self.client.post("/api/v1/status/", **token_header(self.admin)).status_code, 405)

    def test_token_user_without_role_is_refused(self):
        from django.contrib.auth.models import User

        nobody = User.objects.create_user("norole", password="x")
        self.assertEqual(self.client.get("/api/v1/status/", **token_header(nobody)).status_code, 403)


class ApiReadTests(ForecastTestCase):
    def test_predictions_are_limited_to_the_users_district(self):
        body = self.client.get("/api/v1/predictions/?limit=500", **token_header(self.officer)).json()
        self.assertTrue(body["count"] > 0)
        self.assertEqual({r["district"] for r in body["results"]}, {"Kayonza"})

    def test_admin_sees_all_districts(self):
        body = self.client.get("/api/v1/predictions/?limit=500", **token_header(self.admin)).json()
        self.assertEqual(body["count"], 60)

    def test_prediction_filters(self):
        body = self.client.get("/api/v1/predictions/?district=Huye&disease=TST", **token_header(self.admin)).json()
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["results"][0]["disease_code"], "TST")

    def test_reports_paging(self):
        body = self.client.get("/api/v1/reports/?limit=5", **token_header(self.admin)).json()
        self.assertEqual(len(body["results"]), 5)
        self.assertEqual(body["next_offset"], 5)

    def test_reporter_only_reads_own_district_reports(self):
        body = self.client.get("/api/v1/reports/?limit=500", **token_header(self.reporter)).json()
        self.assertEqual({r["district"] for r in body["results"]}, {"Huye"})

    def test_weather_endpoint_answers(self):
        self.assertEqual(self.client.get("/api/v1/weather/", **token_header(self.admin)).status_code, 200)


class ApiSendTests(ForecastTestCase):
    def post(self, user, payload):
        return self.client.post("/api/v1/reports/", json.dumps(payload), content_type="application/json", **token_header(user))

    def valid(self, **extra):
        data = {"patient_name": "Aline Uwase", "age": 29, "gender": "F", "district": "Huye", "disease": "TST",
                "date_onset": str(self.end), "date_reported": str(self.end)}
        data.update(extra)
        return data

    def test_valid_report_is_created(self):
        before = CaseReport.objects.count()
        response = self.post(self.admin, self.valid())
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(CaseReport.objects.count(), before + 1)
        report = CaseReport.objects.latest("id")
        self.assertEqual(report.reported_by, self.admin)
        self.assertEqual(report.patient.full_name, "Aline Uwase")

    def test_forecast_changes_after_a_report_arrives(self):
        before = Prediction.objects.get(district=self.huye, disease=self.fever, as_of=self.end)
        for i in range(4):
            self.assertEqual(self.post(self.admin, self.valid(patient_name=f"Test Person {chr(97 + i)}")).status_code, 201)
        after = Prediction.objects.get(district=self.huye, disease=self.fever, as_of=self.end)
        self.assertGreater(after.recent_cases, before.recent_cases)

    def test_bad_values_return_all_errors(self):
        response = self.post(self.admin, {"patient_name": "T", "age": 200, "district": "Nowhere", "disease": "XXX", "date_onset": str(self.end)})
        self.assertEqual(response.status_code, 400)
        errors = response.json()["errors"]
        for field in ("patient_name", "age", "district", "disease"):
            self.assertIn(field, errors)

    def test_model_rules_are_applied(self):
        response = self.post(self.admin, self.valid(date_onset="2999-01-01"))
        self.assertEqual(response.status_code, 400)

    def test_officer_cannot_send_for_another_district(self):
        response = self.post(self.officer, self.valid(district="Huye"))
        self.assertEqual(response.status_code, 400)
        self.assertIn("district", response.json()["errors"])

    def test_officer_can_send_for_own_district(self):
        self.assertEqual(self.post(self.officer, self.valid(district="Kayonza")).status_code, 201)

    def test_existing_patient_by_code(self):
        first = self.post(self.admin, self.valid()).json()["report"]
        second = self.post(self.admin, {"patient_code": first["patient_code"], "district": "Huye", "disease": "TSC",
                                        "date_onset": str(self.end), "date_reported": str(self.end)})
        self.assertEqual(second.status_code, 201, second.content)

    def test_same_active_disease_twice_is_refused(self):
        first = self.post(self.admin, self.valid()).json()["report"]
        again = self.post(self.admin, {"patient_code": first["patient_code"], "district": "Huye", "disease": "TST",
                                       "date_onset": str(self.end), "date_reported": str(self.end)})
        self.assertEqual(again.status_code, 400)

    def test_patient_needs_details_or_a_code(self):
        response = self.post(self.admin, {"district": "Huye", "disease": "TST", "date_onset": str(self.end)})
        self.assertEqual(response.status_code, 400)

    def test_body_must_be_json(self):
        response = self.client.post("/api/v1/reports/", "not json", content_type="application/json", **token_header(self.admin))
        self.assertEqual(response.status_code, 400)


class TokenViewTests(ForecastTestCase):
    def test_guide_needs_login(self):
        self.assertEqual(self.client.get(reverse("api_guide")).status_code, 302)

    def test_user_can_make_and_replace_a_key(self):
        self.client.force_login(self.reporter)
        self.client.post(reverse("api_token"))
        first = ApiToken.objects.get(user=self.reporter).key
        self.client.post(reverse("api_token"))
        self.assertNotEqual(ApiToken.objects.get(user=self.reporter).key, first)
        self.assertContains(self.client.get(reverse("api_guide")), ApiToken.objects.get(user=self.reporter).key)

    def test_token_view_does_not_accept_get(self):
        self.client.force_login(self.reporter)
        self.assertEqual(self.client.get(reverse("api_token")).status_code, 405)
