import random
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from forecasting import ml
from surveillance.models import CaseReport, Patient
from surveillance.tests.helpers import district, make_disease, make_patient, make_user


class ForecastTestCase(TestCase):
    """Builds about ten months of fictional reports in two districts and trains a small model.

    The model file is written to a temporary folder, so the real model is never touched.
    """

    @classmethod
    def setUpClass(cls):
        # The model file must be redirected before setUpTestData trains, so the real model is never overwritten.
        folder = tempfile.TemporaryDirectory()
        cls.addClassCleanup(folder.cleanup)
        patcher = mock.patch.object(ml, "MODEL_FILE", Path(folder.name) / "model.joblib")
        patcher.start()
        cls.addClassCleanup(patcher.stop)
        ml._cache.update(mtime=None, bundle=None)
        super().setUpClass()

    @classmethod
    def setUpTestData(cls):
        cls.kayonza, cls.huye = district("Kayonza"), district("Huye")
        cls.fever = make_disease("Test Fever", "TST", min_cases_for_alert=3, alert_multiplier=2)
        cls.cough = make_disease("Test Cough", "TSC", min_cases_for_alert=3, alert_multiplier=2)
        cls.admin = make_user("fc_admin", "admin")
        cls.officer = make_user("fc_officer", "officer", cls.kayonza)
        cls.reporter = make_user("fc_reporter", "reporter", cls.huye)
        rng = random.Random(5)
        patients = {d.pk: [make_patient(d, f"Patient {d.name} {i}") for i in range(8)] for d in (cls.kayonza, cls.huye)}
        end = timezone.localdate() - timedelta(days=3)
        rows = []
        for back in range(300):
            day = end - timedelta(days=back)
            for dist in (cls.kayonza, cls.huye):
                for disease in (cls.fever, cls.cough):
                    for _ in range(rng.choice([0, 0, 1, 1, 2])):
                        rows.append(CaseReport(patient=rng.choice(patients[dist.pk]), disease=disease, district=dist,
                                               status="recovered", date_onset=day, date_reported=day))
        CaseReport.objects.bulk_create(rows)
        cls.end = end
        cls.model_run = ml.train()
        ml.refresh_predictions()


def token_header(user):
    from forecasting.models import ApiToken

    token, _ = ApiToken.objects.get_or_create(user=user)
    return {"HTTP_AUTHORIZATION": f"Token {token.key}"}
