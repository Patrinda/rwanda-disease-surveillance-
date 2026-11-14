"""Send new fictional case reports, as a health facility system would.

    python manage.py simulate_incoming                       3 days, written directly
    python manage.py simulate_incoming --days 5 --per-day 12
    python manage.py simulate_incoming --api-url http://127.0.0.1:8000 --token YOUR_KEY

Without --api-url the reports are saved through the same checking code the API uses.
With --api-url they are sent as real HTTP requests to the running server.
Reports are dated today and the days before, so the dashboard moves forward.
Add --outbreak "Cholera:Huye" to push one disease up in one district.
"""
import json
import random
import urllib.error
import urllib.request
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from locations.models import District
from surveillance.models import Disease

from forecasting.services import IncomingReportForm, ingest_report

FIRST = ["Jean", "Marie", "Claude", "Aline", "Eric", "Grace", "Patrick", "Diane", "Olivier", "Chantal", "Emmanuel", "Esther"]
LAST = ["Mugabo", "Uwase", "Habimana", "Mukamana", "Niyonzima", "Ingabire", "Nsengimana", "Uwimana", "Bizimana", "Mutesi"]


class Command(BaseCommand):
    help = "Send fictional incoming case reports so the live forecast can be demonstrated."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=3)
        parser.add_argument("--per-day", type=int, default=10)
        parser.add_argument("--api-url")
        parser.add_argument("--token")
        parser.add_argument("--outbreak", help='Disease and district to push up, for example "Cholera:Huye".')
        parser.add_argument("--seed", type=int, default=None)

    def handle(self, *args, **o):
        rng = random.Random(o["seed"])
        diseases = list(Disease.objects.filter(is_active=True))
        districts = list(District.objects.all())
        weights = {z.pk: max(float(z.min_cases_for_alert), 1) for z in diseases}
        special = None
        if o["outbreak"]:
            try:
                dname, tname = o["outbreak"].split(":")
                special = (Disease.objects.get(name__iexact=dname.strip()), District.objects.get(name__iexact=tname.strip()))
            except (ValueError, Disease.DoesNotExist, District.DoesNotExist):
                raise CommandError('Use --outbreak "Disease name:District name" with names that exist.')
        user = None
        if not o["api_url"]:
            user = get_user_model().objects.filter(is_superuser=True).first()
            if user is None:
                raise CommandError("Create a superuser first.")
        elif not o["token"]:
            raise CommandError("--api-url needs --token.")

        today, sent, failed = timezone.localdate(), 0, 0
        for back in range(o["days"] - 1, -1, -1):
            day = today - timedelta(days=back)
            for _ in range(o["per_day"]):
                if special and rng.random() < 0.35:
                    disease, district = special
                else:
                    disease = rng.choices(diseases, weights=[weights[z.pk] for z in diseases])[0]
                    district = rng.choice(districts)
                payload = {
                    "patient_name": f"{rng.choice(FIRST)} {rng.choice(LAST)}", "age": rng.randint(1, 80),
                    "gender": rng.choice(["M", "F"]), "district": district.name, "disease": disease.code,
                    "case_type": "suspected", "status": "active", "date_onset": str(day - timedelta(days=rng.randint(0, 3))),
                    "date_reported": str(day),
                }
                if self._send(payload, o, user):
                    sent += 1
                else:
                    failed += 1
        self.stdout.write(self.style.SUCCESS(f"{sent} reports sent, {failed} rejected."))

    def _send(self, payload, o, user):
        if o["api_url"]:
            request = urllib.request.Request(
                f"{o['api_url'].rstrip('/')}/api/v1/reports/", data=json.dumps(payload).encode(), method="POST",
                headers={"Authorization": f"Token {o['token']}", "Content-Type": "application/json"},
            )
            try:
                with urllib.request.urlopen(request, timeout=30):
                    return True
            except urllib.error.HTTPError:
                return False
        form = IncomingReportForm(payload, user=user)
        if not form.is_valid():
            return False
        try:
            ingest_report(form)
        except Exception:
            return False
        return True
