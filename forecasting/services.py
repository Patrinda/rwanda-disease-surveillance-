"""Shared logic used by the API and the management commands."""
from datetime import date, timedelta

from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from accounts.permissions import scope_by_district
from accounts.roles import ADMIN, get_role, user_district
from locations.models import District
from surveillance.forms import NAME_VALIDATOR
from surveillance.models import CaseReport, Disease, Patient

from .models import ModelRun, Prediction, WeatherObservation


class IncomingReportForm(forms.Form):
    """Validates one report that arrives through the API (the same rules as the web form)."""

    patient_code = forms.CharField(required=False, max_length=20)
    patient_name = forms.CharField(required=False, max_length=120, validators=[NAME_VALIDATOR])
    age = forms.IntegerField(required=False, min_value=0, max_value=120)
    gender = forms.ChoiceField(required=False, choices=[("M", "Male"), ("F", "Female")])
    district = forms.CharField(max_length=60)
    disease = forms.CharField(max_length=80)
    case_type = forms.ChoiceField(choices=CaseReport.CaseType.choices, required=False)
    status = forms.ChoiceField(choices=CaseReport.Status.choices, required=False)
    date_onset = forms.DateField()
    date_reported = forms.DateField(required=False)
    notes = forms.CharField(required=False, max_length=500)

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_district(self):
        raw = str(self.cleaned_data["district"]).strip()
        found = District.objects.filter(pk=raw).first() if raw.isdigit() else District.objects.filter(name__iexact=raw).first()
        if not found:
            raise ValidationError("Unknown district. Use the district name or its id.")
        return found

    def clean_disease(self):
        raw = str(self.cleaned_data["disease"]).strip()
        found = Disease.objects.filter(pk=raw).first() if raw.isdigit() else (
            Disease.objects.filter(code__iexact=raw).first() or Disease.objects.filter(name__iexact=raw).first()
        )
        if not found:
            raise ValidationError("Unknown disease. Use the disease code, name or id.")
        return found

    def clean(self):
        data = super().clean()
        district = data.get("district")
        if district is not None and get_role(self.user) != ADMIN:
            own = user_district(self.user)
            if own is None or own.pk != district.pk:
                self.add_error("district", "You can only send reports for your own district.")
        if not data.get("patient_code") and not (data.get("patient_name") and data.get("age") is not None and data.get("gender")):
            raise ValidationError("Send patient_code for an existing patient, or patient_name, age and gender for a new one.")
        return data


def ingest_report(form):
    """Create the patient (if new) and the case report from a valid form. Returns the CaseReport."""
    data = form.cleaned_data
    district = data["district"]
    with transaction.atomic():
        if data.get("patient_code"):
            patient = scope_by_district(Patient.objects.all(), form.user).filter(patient_code=data["patient_code"]).first()
            if patient is None:
                raise ValidationError({"patient_code": "No patient with this code in your area."})
        else:
            patient = Patient(full_name=data["patient_name"], age=data["age"], gender=data["gender"], district=district)
            patient.full_clean()
            patient.save()
        report = CaseReport(
            patient=patient, disease=data["disease"], district=district,
            case_type=data.get("case_type") or CaseReport.CaseType.SUSPECTED,
            status=data.get("status") or CaseReport.Status.ACTIVE,
            date_onset=data["date_onset"], date_reported=data.get("date_reported") or timezone.localdate(),
            reported_by=form.user, notes=data.get("notes", ""),
        )
        report.full_clean()
        report.save()          # the post_save signal refreshes this district's forecast
    return report


# ------------------------------------------------------------ read helpers
def latest_predictions(user=None):
    """Predictions from the newest forecast day, limited to the user's district."""
    newest = Prediction.objects.order_by("-as_of").values_list("as_of", flat=True).first()
    queryset = Prediction.objects.filter(as_of=newest).select_related("district", "district__province", "disease")
    if user is not None:
        queryset = scope_by_district(queryset, user)
    return queryset


def weather_summary(user=None, days=7):
    """Average rainfall and temperature of the last `days` days that have weather data."""
    last = WeatherObservation.objects.order_by("-date").values_list("date", flat=True).first()
    if last is None:
        return None
    rows = WeatherObservation.objects.filter(date__gt=last - timedelta(days=days), date__lte=last)
    if user is not None:
        rows = scope_by_district(rows, user)
    if not rows.exists():
        return None
    districts = rows.values("district").distinct().count()
    totals = rows.values("district__name").annotate(rain=Sum("rainfall_mm")).order_by("-rain")[:5]
    avg_rain = sum(r["rain"] for r in rows.values("district").annotate(rain=Sum("rainfall_mm"))) / max(districts, 1)
    avg_temp = sum(rows.values_list("temperature_c", flat=True)) / rows.count()
    sources = set(rows.values_list("source", flat=True))
    return {
        "last_day": last, "days": days, "rain_mm": round(avg_rain, 1), "temp_c": round(avg_temp, 1),
        "wettest": [{"name": t["district__name"], "rain": round(t["rain"], 1)} for t in totals],
        "synthetic": WeatherObservation.Source.SYNTHETIC in sources,
        "label": "Synthetic" if sources == {WeatherObservation.Source.SYNTHETIC} else "Open-Meteo",
    }


def active_run():
    return ModelRun.objects.filter(is_active=True).first()


def dashboard_forecast(user):
    """Everything the dashboard needs about the forecast, limited to what the user may see."""
    run = active_run()
    predictions = latest_predictions(user)
    ranked = predictions.filter(expected_cases__gte=0.05).order_by("-alert_probability", "-expected_cases")
    return {
        "run": run,
        "top": list(ranked[:5]),
        "expected_total": round(sum(p.expected_cases for p in predictions), 1),
        "high": predictions.filter(alert_probability__gte=0.5).count(),
        "moderate": predictions.filter(alert_probability__gte=0.2, alert_probability__lt=0.5).count(),
        "weather": weather_summary(user),
    }
