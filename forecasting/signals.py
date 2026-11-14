"""New or edited reports update the forecast for that district and disease straight away."""
import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from surveillance.models import CaseReport

from .models import ModelRun

log = logging.getLogger(__name__)


@receiver(post_save, sender=CaseReport)
def update_forecast(sender, instance, raw=False, **kwargs):
    if raw or not ModelRun.objects.filter(is_active=True).exists():
        return
    try:
        from .ml import refresh_predictions

        refresh_predictions(district=instance.district, disease=instance.disease)
    except Exception as error:  # a forecasting problem must never block saving a report
        log.warning("Forecast was not updated: %s", error)
