"""Train the forecasting model and save it.

    python manage.py train_model
    python manage.py train_model --from-api http://127.0.0.1:8000 --token YOUR_KEY

With --from-api the case reports are read through the project's own JSON API
instead of the database, to show that the model can learn from API data.
"""
import json
import urllib.request
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from forecasting import ml
from forecasting.models import WeatherObservation
from forecasting.weather import update_weather


def read_reports_from_api(base_url, token):
    rows, offset = [], 0
    while offset is not None:
        request = urllib.request.Request(
            f"{base_url.rstrip('/')}/api/v1/reports/?limit=500&offset={offset}", headers={"Authorization": f"Token {token}"}
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            page = json.loads(response.read().decode("utf-8"))
        for r in page["results"]:
            rows.append({"district": r["district"], "disease_code": r["disease_code"], "date_reported": date.fromisoformat(r["date_reported"])})
        offset = page["next_offset"]
    return rows


class Command(BaseCommand):
    help = "Train the forecasting model, check it on the last 10 weeks and save it."

    def add_arguments(self, parser):
        parser.add_argument("--from-api", dest="api_url", help="Read the reports from this server's API instead of the database.")
        parser.add_argument("--token", help="API key to use with --from-api.")
        parser.add_argument("--no-synthetic", action="store_true", help="Train on the real reports only.")
        parser.add_argument("--with-weather", action="store_true", help="Also use rainfall, temperature and season as inputs.")

    def handle(self, *args, **options):
        api_rows, source = None, "database"
        if options["api_url"]:
            if not options["token"]:
                raise CommandError("--from-api needs --token.")
            self.stdout.write("Reading case reports through the API ...")
            api_rows, source = read_reports_from_api(options["api_url"], options["token"]), "api"
            self.stdout.write(f"  {len(api_rows)} reports received.")
        if not WeatherObservation.objects.exists():
            self.stdout.write("No weather data yet, filling it first ...")
            from datetime import timedelta
            from surveillance.alerts import get_as_of_date

            end = get_as_of_date()
            update_weather(end - timedelta(days=399), end)
        self.stdout.write("Training (this takes a few seconds) ...")
        try:
            run = ml.train(api_rows=api_rows, data_source=source, use_weather=options["with_weather"], use_synthetic=not options["no_synthetic"])
        except ValueError as error:
            raise CommandError(str(error))
        saved = ml.refresh_predictions()
        self.stdout.write(self.style.SUCCESS(f"Model {run.version} saved. {saved} predictions created."))
        self.stdout.write(
            f"Unseen weeks, Poisson deviance (lower is better): model {run.deviance:.3f}, 'same as this week' "
            f"{run.baseline_deviance:.3f}, 4 week average {run.avg4_deviance:.3f} ({run.improvement_percent}% better than 'same as this week')."
        )
        self.stdout.write(
            f"National weekly total error: model {run.national_mae:.1f}, 'same as this week' {run.national_baseline_mae:.1f}. "
            f"Alert ranking AUC: model {run.alert_auc if run.alert_auc is None else round(run.alert_auc, 3)}, "
            f"simple rule {run.baseline_auc if run.baseline_auc is None else round(run.baseline_auc, 3)}."
        )
