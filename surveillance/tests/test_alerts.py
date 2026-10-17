from django.core.management import call_command
from django.test import TestCase
from io import StringIO

from surveillance.alerts import classify, current_alerts
from surveillance.models import CaseReport, Disease

from .helpers import district, make_disease, make_patient, make_report


class ClassifyTests(TestCase):
    def test_rules(self):
        self.assertEqual(classify(2, 0, 2, 3), "normal")      # below the minimum
        self.assertEqual(classify(3, 0, 2, 3), "alert")       # new cluster, no baseline
        self.assertEqual(classify(6, 3, 2, 3), "alert")       # exactly double
        self.assertEqual(classify(5, 3, 2, 3), "watch")       # 1.67 times
        self.assertEqual(classify(4, 3, 2, 3), "normal")      # 1.33 times
        self.assertEqual(classify(10, 10, 2, 3), "normal")


class CurrentAlertsTests(TestCase):
    def setUp(self):
        self.disease = make_disease(min_cases_for_alert=3, alert_multiplier=2)
        self.d = district("Gasabo")
        self.p = make_patient(self.d)

    def add(self, count, days_ago):
        for _ in range(count):
            make_report(self.p, self.disease, self.d, days_ago=days_ago)

    def test_alert_when_week_is_double_the_baseline(self):
        self.add(2, 10)   # baseline: 2 cases in 28 days is 0.5 a week
        self.add(4, 1)
        result = current_alerts()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["level"], "alert")
        self.assertEqual(result[0]["district"], self.d)

    def test_nothing_below_minimum(self):
        self.add(2, 1)
        self.assertEqual(current_alerts(), [])

    def test_min_level_filter(self):
        self.add(8, 10)   # baseline 2 a week
        self.add(3, 1)    # 3 is 1.5 times 2: watch
        self.assertEqual(len(current_alerts()), 1)
        self.assertEqual(current_alerts()[0]["level"], "watch")
        self.assertEqual(current_alerts(min_level="alert"), [])

    def test_inactive_disease_is_ignored(self):
        self.add(5, 1)
        self.disease.is_active = False
        self.disease.save()
        self.assertEqual(current_alerts(), [])


class SeedTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", stdout=StringIO())

    def test_expected_alerts_and_watches(self):
        result = current_alerts()
        self.assertEqual(sum(a["level"] == "alert" for a in result), 3)
        self.assertEqual(sum(a["level"] == "watch" for a in result), 3)
        names = {(a["disease"].name, a["district"].name, a["level"]) for a in result}
        self.assertIn(("Rift Valley Fever", "Kayonza", "alert"), names)
        self.assertIn(("Rift Valley Fever", "Ngoma", "alert"), names)

    def test_rift_valley_fever_is_concentrated_in_kayonza_and_ngoma(self):
        rvf = CaseReport.objects.filter(disease__name="Rift Valley Fever")
        total = rvf.count()
        east = rvf.filter(district__name__in=["Kayonza", "Ngoma"]).count()
        self.assertGreater(east / total, 0.4)
        self.assertGreater(rvf.exclude(district__name__in=["Kayonza", "Ngoma"]).values("district").distinct().count(), 10)

    def test_seed_is_safe_to_run_twice(self):
        before = CaseReport.objects.count()
        call_command("seed_demo", stdout=StringIO())
        self.assertEqual(CaseReport.objects.count(), before)
        call_command("seed_demo", "--reset", stdout=StringIO())
        self.assertGreater(CaseReport.objects.count(), 1000)
        self.assertEqual(Disease.objects.count(), 21)
