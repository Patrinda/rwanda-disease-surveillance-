"""Download daily weather for every district from the Open-Meteo API.

    python manage.py fetch_weather                 last 400 days, real data
    python manage.py fetch_weather --days 120
    python manage.py fetch_weather --synthetic     make synthetic weather (works without internet)

If Open-Meteo cannot be reached, missing days are filled with synthetic weather
and marked as such. Real rows are never replaced by synthetic ones.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from surveillance.alerts import get_as_of_date

from forecasting.weather import update_weather


class Command(BaseCommand):
    help = "Download daily rainfall and temperature for all districts (Open-Meteo)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=400, help="How many days back to fetch (default 400).")
        parser.add_argument("--synthetic", action="store_true", help="Generate synthetic weather instead of downloading.")

    def handle(self, *args, **options):
        end = max(get_as_of_date(), timezone.localdate()) if options["synthetic"] else get_as_of_date()
        start = end - timedelta(days=options["days"] - 1)
        saved, source, message = update_weather(start, end, synthetic=options["synthetic"])
        self.stdout.write(self.style.SUCCESS(f"{saved} weather rows saved from {start} to {end} (source: {source}). {message}"))
