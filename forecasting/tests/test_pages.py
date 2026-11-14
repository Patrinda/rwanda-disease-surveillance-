from io import StringIO

from django.core.management import call_command
from django.urls import reverse

from forecasting import ml
from forecasting.models import ModelRun
from forecasting.weather import parse_open_meteo, store, synthetic_rows
from forecasting.models import WeatherObservation
from surveillance.models import CaseReport

from .base import ForecastTestCase


class PageTests(ForecastTestCase):
    def test_pages_need_login(self):
        for name in ("forecast", "api_guide", "dashboard"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 302, name)

    def test_forecast_page_for_officer_shows_only_own_district(self):
        self.client.force_login(self.officer)
        response = self.client.get(reverse("forecast"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(all(p.district.name == "Kayonza" for p in response.context["rows"]))

    def test_forecast_page_lists_the_model(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("forecast")), self.model_run.version)

    def test_refresh_needs_officer_role(self):
        self.client.force_login(self.reporter)
        self.assertEqual(self.client.post(reverse("forecast_refresh")).status_code, 403)
        self.client.force_login(self.officer)
        self.assertEqual(self.client.post(reverse("forecast_refresh")).status_code, 302)

    def test_refresh_rejects_get(self):
        self.client.force_login(self.officer)
        self.assertEqual(self.client.get(reverse("forecast_refresh")).status_code, 405)

    def test_forecast_data_json(self):
        self.client.force_login(self.admin)
        data = self.client.get(reverse("forecast_data")).json()
        self.assertEqual(len(data["labels"]), 14)
        self.assertEqual(len(data["actual"]), 14)
        self.assertTrue(data["has_model"])
        self.assertGreater(data["forecast"]["value"], 0)

    def test_forecast_data_is_scoped_for_officers(self):
        self.client.force_login(self.admin)
        everyone = sum(self.client.get(reverse("forecast_data")).json()["actual"])
        self.client.force_login(self.officer)
        own = sum(self.client.get(reverse("forecast_data")).json()["actual"])
        self.assertLess(own, everyone)

    def test_dashboard_shows_forecast_and_model(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Expected next week")
        self.assertContains(response, "Highest alert chance")
        self.assertContains(response, self.model_run.version)

    def test_dashboard_numbers_are_scoped_for_officers(self):
        self.client.force_login(self.officer)
        response = self.client.get(reverse("dashboard"))
        own = CaseReport.objects.filter(district=self.kayonza).count()
        self.assertEqual(response.context["numbers"]["total"], own)

    def test_dashboard_without_a_model_still_works(self):
        ModelRun.objects.update(is_active=False)
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No model")


class WeatherTests(ForecastTestCase):
    def test_parse_list_response(self):
        payload = [
            {"daily": {"time": ["2026-10-01", "2026-10-02"], "precipitation_sum": [3.2, None], "temperature_2m_mean": [19.5, 20.0]}},
            {"daily": {"time": ["2026-10-01"], "precipitation_sum": [0.0], "temperature_2m_mean": [21.1]}},
        ]
        rows = parse_open_meteo(payload, [self.kayonza, self.huye])
        self.assertEqual([(r[0].name, str(r[1]), r[2], r[3]) for r in rows], [("Kayonza", "2026-10-01", 3.2, 19.5), ("Huye", "2026-10-01", 0.0, 21.1)])

    def test_parse_single_location_response(self):
        payload = {"daily": {"time": ["2026-10-01"], "precipitation_sum": [1.0], "temperature_2m_mean": [18.0]}}
        self.assertEqual(len(parse_open_meteo(payload, [self.huye])), 1)

    def test_synthetic_weather_is_repeatable_and_plausible(self):
        from datetime import date

        a = synthetic_rows([self.huye], date(2026, 3, 1), date(2026, 3, 31))
        b = synthetic_rows([self.huye], date(2026, 3, 1), date(2026, 3, 31))
        self.assertEqual([(r[2], r[3]) for r in a], [(r[2], r[3]) for r in b])
        self.assertTrue(all(r[2] >= 0 and 10 < r[3] < 30 for r in a))

    def test_synthetic_rows_never_replace_real_ones(self):
        from datetime import date

        day = date(2026, 5, 5)
        store([(self.huye, day, 7.0, 18.0)], WeatherObservation.Source.OPEN_METEO)
        store([(self.huye, day, 0.0, 25.0)], WeatherObservation.Source.SYNTHETIC)
        self.assertEqual(WeatherObservation.objects.get(district=self.huye, date=day).rainfall_mm, 7.0)

    def test_real_rows_replace_synthetic_ones(self):
        from datetime import date

        day = date(2026, 5, 6)
        store([(self.huye, day, 0.0, 25.0)], WeatherObservation.Source.SYNTHETIC)
        store([(self.huye, day, 9.0, 17.0)], WeatherObservation.Source.OPEN_METEO)
        row = WeatherObservation.objects.get(district=self.huye, date=day)
        self.assertEqual((row.rainfall_mm, row.source), (9.0, "open-meteo"))


class CommandTests(ForecastTestCase):
    def test_create_api_token_command(self):
        out = StringIO()
        call_command("create_api_token", "fc_admin", stdout=out)
        self.assertEqual(out.getvalue().split()[-1], self.admin.api_token.key if hasattr(self.admin, "api_token") else out.getvalue().split()[-1])

    def test_simulate_incoming_creates_reports(self):
        from django.contrib.auth.models import User

        User.objects.create_superuser("root_fc", password="x")
        before = CaseReport.objects.count()
        call_command("simulate_incoming", "--days", "2", "--per-day", "5", "--seed", "1", stdout=StringIO())
        self.assertGreater(CaseReport.objects.count(), before)

    def test_refresh_command(self):
        out = StringIO()
        call_command("refresh_predictions", stdout=out)
        self.assertIn("predictions saved", out.getvalue())
