from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.utils import timezone

from accounts.roles import ROLE_ADMIN, ROLE_OFFICER, ROLE_REPORTER
from locations.models import District
from surveillance.models import CaseReport, Disease, Patient


def make_user(username, role, district=None, password="Test@12345"):
    user = User.objects.create_user(username, password=password)
    user.groups.add(Group.objects.get(name={"admin": ROLE_ADMIN, "officer": ROLE_OFFICER, "reporter": ROLE_REPORTER}[role]))
    user.profile.district = district
    user.profile.save()
    return user


def district(name):
    return District.objects.get(name=name)


def make_disease(name="Test Fever", code="TST", **kwargs):
    defaults = dict(category="other", reporting="weekly", alert_multiplier=2, min_cases_for_alert=3)
    defaults.update(kwargs)
    return Disease.objects.create(name=name, code=code, **defaults)


def make_patient(dist, name="Jean Test", age=30):
    return Patient.objects.create(full_name=name, age=age, gender="M", district=dist)


def make_report(patient, disease, dist, days_ago=0, **kwargs):
    day = timezone.localdate() - timedelta(days=days_ago)
    defaults = dict(date_onset=day, date_reported=day, status="recovered")
    defaults.update(kwargs)
    return CaseReport.objects.create(patient=patient, disease=disease, district=dist, **defaults)
