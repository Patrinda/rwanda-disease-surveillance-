from django import forms
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.utils import timezone

from accounts.forms import RW_PHONE
from accounts.permissions import scope_by_district
from accounts.roles import ADMIN, get_role, user_district
from locations.models import District

from .models import CaseReport, Disease, Outbreak, Patient

NAME_VALIDATOR = RegexValidator(
    r"^[A-Za-z][A-Za-z '\-\.]{2,}$",
    "Use letters, spaces, apostrophes and hyphens only (at least 3 characters).",
)


class BootstrapFormMixin:
    """Adds Bootstrap classes to every widget and marks fields with errors."""

    def _style_widgets(self):
        for field in self.fields.values():
            widget = field.widget
            css = widget.attrs.get("class", "")
            if isinstance(widget, forms.CheckboxInput):
                base = "form-check-input"
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                base = "form-select"
            else:
                base = "form-control"
            if base not in css:
                widget.attrs["class"] = (css + " " + base).strip()

    def full_clean(self):
        super().full_clean()
        self._style_widgets()
        for name in self.errors:
            if name in self.fields:
                widget = self.fields[name].widget
                if "is-invalid" not in widget.attrs.get("class", ""):
                    widget.attrs["class"] = (widget.attrs.get("class", "") + " is-invalid").strip()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_widgets()


class DiseaseForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Disease
        fields = ["name", "code", "category", "reporting", "description", "alert_multiplier", "min_cases_for_alert", "is_active"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def clean_code(self):
        code = self.cleaned_data["code"].strip().upper()
        clash = Disease.objects.filter(code__iexact=code).exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError("A disease with this code already exists.")
        return code


class PatientForm(BootstrapFormMixin, forms.ModelForm):
    full_name = forms.CharField(max_length=120, validators=[NAME_VALIDATOR])
    age = forms.IntegerField(
        min_value=0, max_value=120, validators=[MinValueValidator(0), MaxValueValidator(120)],
        help_text="Age in years, from 0 to 120.",
    )
    phone = forms.CharField(
        max_length=15, required=False, validators=[RW_PHONE],
        help_text="Optional. Example: 0788123456 or +250788123456.",
    )

    class Meta:
        model = Patient
        fields = ["full_name", "age", "gender", "phone", "district"]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None and get_role(user) != ADMIN:
            district = user_district(user)
            self.fields["district"].queryset = District.objects.filter(pk=district.pk) if district else District.objects.none()
            if district and not self.instance.pk:
                self.fields["district"].initial = district


class CaseReportForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = CaseReport
        fields = ["patient", "disease", "district", "case_type", "status", "date_onset", "date_reported", "notes"]
        widgets = {
            "date_onset": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "date_reported": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        today = timezone.localdate().isoformat()
        self.fields["date_onset"].widget.attrs["max"] = today
        self.fields["date_reported"].widget.attrs["max"] = today
        self.fields["disease"].queryset = Disease.objects.filter(is_active=True)
        if user is not None:
            self.fields["patient"].queryset = scope_by_district(Patient.objects.all(), user)
            if get_role(user) != ADMIN:
                district = user_district(user)
                self.fields["district"].queryset = District.objects.filter(pk=district.pk) if district else District.objects.none()
                if district and not self.instance.pk:
                    self.fields["district"].initial = district


class OutbreakForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Outbreak
        fields = ["disease", "district", "level", "start_date", "notes"]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["disease"].queryset = Disease.objects.filter(is_active=True)

    def clean(self):
        cleaned = super().clean()
        disease, district = cleaned.get("disease"), cleaned.get("district")
        if disease and district and Outbreak.objects.filter(disease=disease, district=district, status="open").exists():
            raise forms.ValidationError("There is already an open outbreak for this disease in this district.")
        return cleaned
