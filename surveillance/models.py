import uuid
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Disease(models.Model):
    """A disease or condition that health facilities report."""

    class Category(models.TextChoices):
        VECTOR = "vector", "Vector-borne"
        ZOONOTIC = "zoonotic", "Zoonotic"
        RESPIRATORY = "respiratory", "Respiratory"
        WATER_FOOD = "water_food", "Water and food-borne"
        VACCINE = "vaccine", "Vaccine-preventable"
        HAEMORRHAGIC = "haemorrhagic", "Viral haemorrhagic"
        INJURY = "injury", "Injury and envenomation"
        OTHER = "other", "Other"

    class Reporting(models.TextChoices):
        IMMEDIATE = "immediate", "Immediate (within 24 hours)"
        WEEKLY = "weekly", "Weekly"

    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=10, unique=True)
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.OTHER)
    reporting = models.CharField(max_length=10, choices=Reporting.choices, default=Reporting.WEEKLY)
    description = models.TextField(blank=True)
    alert_multiplier = models.DecimalField(
        max_digits=4, decimal_places=1, default=2.0,
        help_text="An alert is raised when this week's cases reach this many times the usual weekly level.",
    )
    min_cases_for_alert = models.PositiveSmallIntegerField(
        default=5, help_text="Never raise an alert for fewer cases than this in one week."
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def clean(self):
        errors = {}
        if self.alert_multiplier is not None and self.alert_multiplier < 1:
            errors["alert_multiplier"] = "The multiplier must be at least 1.0."
        if self.min_cases_for_alert is not None and self.min_cases_for_alert < 1:
            errors["min_cases_for_alert"] = "The minimum number of cases must be at least 1."
        if self.name:
            clash = Disease.objects.filter(name__iexact=self.name).exclude(pk=self.pk)
            if clash.exists():
                errors["name"] = "A disease with this name already exists."
        if errors:
            raise ValidationError(errors)


class Patient(models.Model):
    class Gender(models.TextChoices):
        MALE = "M", "Male"
        FEMALE = "F", "Female"

    patient_code = models.CharField(max_length=20, unique=True, editable=False)
    full_name = models.CharField(max_length=120)
    age = models.PositiveSmallIntegerField()
    gender = models.CharField(max_length=1, choices=Gender.choices)
    phone = models.CharField(max_length=15, blank=True)
    district = models.ForeignKey("locations.District", on_delete=models.PROTECT, related_name="patients")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return f"{self.patient_code} {self.full_name}"

    def save(self, *args, **kwargs):
        # The readable code (P-00012) needs the database id, so it is set after the first save.
        if not self.patient_code:
            self.patient_code = f"TMP-{uuid.uuid4().hex[:12]}"
        super().save(*args, **kwargs)
        if self.patient_code.startswith("TMP-"):
            self.patient_code = f"P-{self.pk:05d}"
            super().save(update_fields=["patient_code"])

    def clean(self):
        if self.age is not None and self.age > 120:
            raise ValidationError({"age": "Age must be between 0 and 120."})


class CaseReport(models.Model):
    class CaseType(models.TextChoices):
        SUSPECTED = "suspected", "Suspected"
        CONFIRMED = "confirmed", "Confirmed"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        RECOVERED = "recovered", "Recovered"
        DECEASED = "deceased", "Deceased"

    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="cases")
    disease = models.ForeignKey(Disease, on_delete=models.PROTECT, related_name="cases")
    district = models.ForeignKey("locations.District", on_delete=models.PROTECT, related_name="cases")
    case_type = models.CharField(max_length=10, choices=CaseType.choices, default=CaseType.SUSPECTED)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    date_onset = models.DateField(help_text="Day the first symptoms started.")
    date_reported = models.DateField(default=timezone.localdate)
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="reports"
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date_reported", "-id"]
        indexes = [models.Index(fields=["disease", "district", "date_reported"])]

    def __str__(self):
        return f"{self.disease} / {self.patient.patient_code} / {self.date_reported}"

    def clean(self):
        errors = {}
        if self.date_reported and self.date_reported > timezone.localdate():
            errors["date_reported"] = "The report date cannot be in the future."
        if self.date_onset and self.date_reported:
            if self.date_onset > self.date_reported:
                errors["date_onset"] = "Symptom onset cannot be after the report date."
            elif self.date_onset < self.date_reported - timedelta(days=365):
                errors["date_onset"] = "Symptom onset cannot be more than one year before the report date."
        if self.patient_id and self.disease_id and self.status == self.Status.ACTIVE:
            duplicate = CaseReport.objects.filter(
                patient_id=self.patient_id, disease_id=self.disease_id, status=self.Status.ACTIVE
            ).exclude(pk=self.pk)
            if duplicate.exists():
                errors["disease"] = "This patient already has an active report for this disease."
        if errors:
            raise ValidationError(errors)


class Outbreak(models.Model):
    class Level(models.TextChoices):
        WATCH = "watch", "Watch"
        ALERT = "alert", "Alert"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        CONTAINED = "contained", "Contained"
        CLOSED = "closed", "Closed"

    disease = models.ForeignKey(Disease, on_delete=models.PROTECT, related_name="outbreaks")
    district = models.ForeignKey("locations.District", on_delete=models.PROTECT, related_name="outbreaks")
    level = models.CharField(max_length=10, choices=Level.choices, default=Level.ALERT)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    start_date = models.DateField(default=timezone.localdate)
    end_date = models.DateField(null=True, blank=True)
    auto_detected = models.BooleanField(default=False, help_text="Raised from an automatic alert.")
    cases = models.ManyToManyField(CaseReport, blank=True, related_name="outbreaks")
    declared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="declared_outbreaks"
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_date", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["disease", "district"],
                condition=Q(status="open"),
                name="one_open_outbreak_per_disease_and_district",
                violation_error_message="There is already an open outbreak for this disease in this district.",
            )
        ]

    def __str__(self):
        return f"{self.disease} in {self.district} ({self.get_status_display()})"

    def clean(self):
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "The end date cannot be before the start date."})

    @property
    def is_open(self):
        return self.status == self.Status.OPEN
