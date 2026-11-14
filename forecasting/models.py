import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone


class WeatherObservation(models.Model):
    """Daily rainfall and temperature for one district."""

    class Source(models.TextChoices):
        OPEN_METEO = "open-meteo", "Open-Meteo"
        SYNTHETIC = "synthetic", "Synthetic"

    district = models.ForeignKey("locations.District", on_delete=models.CASCADE, related_name="weather")
    date = models.DateField()
    rainfall_mm = models.FloatField()
    temperature_c = models.FloatField()
    source = models.CharField(max_length=12, choices=Source.choices, default=Source.OPEN_METEO)

    class Meta:
        ordering = ["district", "date"]
        constraints = [models.UniqueConstraint(fields=["district", "date"], name="one_weather_row_per_district_day")]

    def __str__(self):
        return f"{self.district} {self.date} {self.rainfall_mm} mm"


class ModelRun(models.Model):
    """One training run: what was trained, on which data and how well it did on unseen weeks."""

    version = models.CharField(max_length=30, unique=True)
    algorithm = models.CharField(max_length=80)
    trained_at = models.DateTimeField(default=timezone.now)
    data_source = models.CharField(max_length=40, default="database")
    weather_source = models.CharField(max_length=40, blank=True)
    history_start = models.DateField()
    history_end = models.DateField()
    training_rows = models.PositiveIntegerField()
    synthetic_rows = models.PositiveIntegerField(default=0, help_text="Generated outbreak examples added to training.")
    test_weeks = models.PositiveSmallIntegerField()
    uses_weather = models.BooleanField(default=False)
    features = models.JSONField(default=list, blank=True)
    deviance = models.FloatField(help_text="Poisson deviance on unseen weeks (lower is better). Suits small counts.")
    baseline_deviance = models.FloatField(help_text="Same score for the simple rule: next week equals this week.")
    avg4_deviance = models.FloatField(help_text="Same score for the 4 week average rule.")
    mae = models.FloatField(help_text="Mean absolute error per district and disease, next week, on unseen weeks.")
    baseline_mae = models.FloatField(help_text="Same error for the simple rule: next week equals this week.")
    rmse = models.FloatField()
    baseline_rmse = models.FloatField()
    national_mae = models.FloatField(help_text="Error of the national weekly total on unseen weeks.")
    national_baseline_mae = models.FloatField()
    alert_events = models.PositiveIntegerField(default=0, help_text="Alert situations in the unseen weeks.")
    alert_auc = models.FloatField(null=True, blank=True)
    baseline_auc = models.FloatField(null=True, blank=True)
    feature_importance = models.JSONField(default=dict, blank=True)
    backtest = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-trained_at"]

    def __str__(self):
        return f"{self.version} ({self.algorithm})"

    @property
    def improvement_percent(self):
        """How much lower the model's error is than the simple rule 'next week equals this week'."""
        if not self.baseline_deviance:
            return 0.0
        return round(100 * (self.baseline_deviance - self.deviance) / self.baseline_deviance, 1)

    @property
    def national_improvement_percent(self):
        if not self.national_baseline_mae:
            return 0.0
        return round(100 * (self.national_baseline_mae - self.national_mae) / self.national_baseline_mae, 1)


class Prediction(models.Model):
    """Forecast of next week for one disease in one district."""

    HIGH, MODERATE, LOW = "high", "moderate", "low"

    run = models.ForeignKey(ModelRun, on_delete=models.CASCADE, related_name="predictions")
    district = models.ForeignKey("locations.District", on_delete=models.CASCADE, related_name="predictions")
    disease = models.ForeignKey("surveillance.Disease", on_delete=models.CASCADE, related_name="predictions")
    as_of = models.DateField(help_text="Last day of data used.")
    week_start = models.DateField()
    week_end = models.DateField()
    recent_cases = models.PositiveIntegerField(help_text="Reports in the last 7 days.")
    usual_level = models.FloatField(help_text="Average weekly reports in the 4 weeks before the last 7 days.")
    expected_cases = models.FloatField()
    alert_probability = models.FloatField()
    created_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-as_of", "-alert_probability", "-expected_cases"]
        constraints = [
            models.UniqueConstraint(fields=["district", "disease", "as_of"], name="one_prediction_per_series_and_day")
        ]
        indexes = [models.Index(fields=["as_of", "alert_probability"])]

    def __str__(self):
        return f"{self.disease} in {self.district}: {self.expected_cases:.1f} (week of {self.week_start})"

    @property
    def risk(self):
        if self.alert_probability >= 0.5:
            return self.HIGH
        if self.alert_probability >= 0.2:
            return self.MODERATE
        return self.LOW

    @property
    def probability_percent(self):
        return round(self.alert_probability * 100)


def new_token_key():
    return secrets.token_hex(20)


class ApiToken(models.Model):
    """Key a program sends in the Authorization header to use the API without a browser."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="api_token")
    key = models.CharField(max_length=40, unique=True, default=new_token_key, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Token of {self.user}"

    def regenerate(self):
        self.key = new_token_key()
        self.save(update_fields=["key"])
