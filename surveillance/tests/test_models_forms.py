from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from locations.models import District, Province
from surveillance.forms import CaseReportForm, DiseaseForm, OutbreakForm, PatientForm
from surveillance.models import CaseReport, Disease, Outbreak

from .helpers import district, make_disease, make_patient, make_report, make_user


class LocationDataTests(TestCase):
    def test_migration_loads_rwanda_geography(self):
        self.assertEqual(Province.objects.count(), 5)
        self.assertEqual(District.objects.count(), 30)
        self.assertEqual(district("Kayonza").province.name, "Eastern")
        self.assertEqual(district("Ngoma").province.name, "Eastern")

    def test_district_cannot_be_deleted_while_it_has_patients(self):
        d = district("Huye")
        make_patient(d)
        from django.db.models import ProtectedError
        with self.assertRaises(ProtectedError):
            d.delete()


class DiseaseTests(TestCase):
    def test_form_rejects_duplicate_name_and_low_multiplier(self):
        make_disease("Malaria X", "MX")
        form = DiseaseForm(data={"name": "malaria x", "code": "MY", "category": "other", "reporting": "weekly",
                                 "alert_multiplier": "0.5", "min_cases_for_alert": "0", "is_active": "on"})
        self.assertFalse(form.is_valid())
        self.assertIn("name", form.errors)
        self.assertIn("alert_multiplier", form.errors)
        self.assertIn("min_cases_for_alert", form.errors)


class PatientTests(TestCase):
    def test_patient_code_is_generated(self):
        p = make_patient(district("Huye"))
        self.assertEqual(p.patient_code, f"P-{p.pk:05d}")

    def test_form_validation(self):
        base = {"full_name": "Alice Uwase", "age": "25", "gender": "F", "phone": "0788123456", "district": district("Huye").pk}
        self.assertTrue(PatientForm(data=base).is_valid())
        for field, bad in (("age", "150"), ("phone", "12345"), ("full_name", "A1!")):
            form = PatientForm(data={**base, field: bad})
            self.assertFalse(form.is_valid(), field)
            self.assertIn(field, form.errors)


class CaseReportTests(TestCase):
    def setUp(self):
        self.d = district("Huye")
        self.patient = make_patient(self.d)
        self.disease = make_disease()
        self.today = timezone.localdate()

    def test_future_date_rejected(self):
        r = CaseReport(patient=self.patient, disease=self.disease, district=self.d,
                       date_onset=self.today, date_reported=self.today + timedelta(days=1))
        with self.assertRaises(ValidationError):
            r.full_clean()

    def test_onset_after_report_rejected(self):
        r = CaseReport(patient=self.patient, disease=self.disease, district=self.d,
                       date_onset=self.today, date_reported=self.today - timedelta(days=2))
        with self.assertRaises(ValidationError) as ctx:
            r.full_clean()
        self.assertIn("date_onset", ctx.exception.message_dict)

    def test_one_active_report_per_patient_and_disease(self):
        make_report(self.patient, self.disease, self.d, status="active")
        r = CaseReport(patient=self.patient, disease=self.disease, district=self.d,
                       date_onset=self.today, date_reported=self.today, status="active")
        with self.assertRaises(ValidationError) as ctx:
            r.full_clean()
        self.assertIn("disease", ctx.exception.message_dict)

    def test_form_limits_choices_to_active_diseases(self):
        retired = make_disease("Retired", "RET", is_active=False)
        form = CaseReportForm()
        self.assertNotIn(retired, form.fields["disease"].queryset)
        self.assertIn(self.disease, form.fields["disease"].queryset)


class OutbreakTests(TestCase):
    def setUp(self):
        self.disease = make_disease()
        self.d = district("Kayonza")
        self.today = timezone.localdate()

    def test_only_one_open_outbreak_per_disease_and_district(self):
        Outbreak.objects.create(disease=self.disease, district=self.d, level="alert", start_date=self.today)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Outbreak.objects.create(disease=self.disease, district=self.d, level="watch", start_date=self.today)

    def test_form_reports_duplicate_open_outbreak(self):
        Outbreak.objects.create(disease=self.disease, district=self.d, level="alert", start_date=self.today)
        form = OutbreakForm(data={"disease": self.disease.pk, "district": self.d.pk, "level": "alert",
                                  "start_date": self.today.isoformat(), "notes": ""})
        self.assertFalse(form.is_valid())

    def test_closed_outbreak_does_not_block_a_new_one(self):
        Outbreak.objects.create(disease=self.disease, district=self.d, level="alert", start_date=self.today, status="closed")
        Outbreak.objects.create(disease=self.disease, district=self.d, level="alert", start_date=self.today)
        self.assertEqual(Outbreak.objects.count(), 2)
