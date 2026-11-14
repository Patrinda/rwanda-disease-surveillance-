"""Recalculate next week's forecast from the latest data.

    python manage.py refresh_predictions
"""
from django.core.management.base import BaseCommand, CommandError

from forecasting import ml


class Command(BaseCommand):
    help = "Recalculate the forecast for every district and disease."

    def handle(self, *args, **options):
        try:
            saved = ml.refresh_predictions()
        except ml.ModelUnavailable as error:
            raise CommandError(str(error))
        self.stdout.write(self.style.SUCCESS(f"{saved} predictions saved."))
