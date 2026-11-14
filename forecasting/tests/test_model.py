import math

import numpy as np

from forecasting import ml
from forecasting.models import ModelRun, Prediction

from .base import ForecastTestCase


class TrainingTests(ForecastTestCase):
    def test_training_saves_file_and_run(self):
        self.assertTrue(ml.MODEL_FILE.exists())
        run = ModelRun.objects.get(is_active=True)
        self.assertEqual(run.pk, self.model_run.pk)
        self.assertEqual(run.algorithm, ml.ALGORITHM)
        for value in (run.deviance, run.baseline_deviance, run.mae, run.baseline_mae, run.national_mae):
            self.assertTrue(math.isfinite(value))
        self.assertEqual(run.test_weeks, 10)
        self.assertTrue(run.synthetic_rows > 0)

    def test_only_one_active_run(self):
        ml.train()
        self.assertEqual(ModelRun.objects.filter(is_active=True).count(), 1)

    def test_predictions_cover_every_district_and_disease(self):
        expected = 30 * 2   # 30 districts and the two active test diseases
        self.assertEqual(Prediction.objects.filter(as_of=self.end).count(), expected)

    def test_prediction_values_are_valid(self):
        for p in Prediction.objects.all():
            self.assertGreaterEqual(p.expected_cases, 0)
            self.assertTrue(0 <= p.alert_probability <= 1)
            self.assertEqual((p.week_end - p.week_start).days, 6)

    def test_weather_is_not_a_model_input_by_default(self):
        self.assertFalse(self.model_run.uses_weather)
        self.assertNotIn("rain7", self.model_run.features)


class MathTests(ForecastTestCase):
    def test_alert_probability_rises_with_expected_cases(self):
        low = ml.alert_probability(np.array([1.0]), np.array([6.0]))[0]
        high = ml.alert_probability(np.array([9.0]), np.array([6.0]))[0]
        self.assertLess(low, 0.01)
        self.assertGreater(high, 0.8)

    def test_alert_probability_is_near_zero_without_cases(self):
        self.assertLess(ml.alert_probability(np.array([0.0]), np.array([3.0]))[0], 1e-6)

    def test_features_have_no_missing_values(self):
        ds = ml.load_dataset()
        X, series, days, m4, w0, usual = ml.make_features(ds, [ds.days - 1])
        self.assertEqual(X.shape, (ds.nd * ds.nz, len(ml.FEATURES)))
        self.assertFalse(np.isnan(X).any())
        self.assertFalse(np.isnan(usual).any())

    def test_threshold_follows_the_alert_rule(self):
        ds = ml.load_dataset()
        fever = ds.series(self.kayonza.pk, self.fever.pk)
        # multiplier 2, usual level 4 -> 8 cases; minimum 3 only matters when 2 x usual is smaller
        self.assertEqual(ml.alert_threshold(ds, np.array([fever, fever]), np.array([4.0, 0.5])).tolist(), [8.0, 3.0])


class RefreshTests(ForecastTestCase):
    def test_refresh_without_run_does_nothing(self):
        ModelRun.objects.update(is_active=False)
        self.assertEqual(ml.refresh_predictions(), 0)

    def test_missing_file_raises_a_clear_error(self):
        ml.MODEL_FILE.rename(ml.MODEL_FILE.with_suffix(".moved"))
        ml._cache.update(mtime=None, bundle=None)
        try:
            with self.assertRaises(ml.ModelUnavailable):
                ml.refresh_predictions()
        finally:
            ml.MODEL_FILE.with_suffix(".moved").rename(ml.MODEL_FILE)
            ml._cache.update(mtime=None, bundle=None)

    def test_new_reports_raise_the_forecast_through_the_signal(self):
        from surveillance.tests.helpers import make_patient, make_report

        before = Prediction.objects.get(district=self.huye, disease=self.fever, as_of=self.end)
        patient = make_patient(self.huye, "Signal Test")
        for i in range(6):
            make_report(patient, self.fever, self.huye, days_ago=3, status="recovered")
        after = Prediction.objects.get(district=self.huye, disease=self.fever, as_of=self.end)
        self.assertGreater(after.recent_cases, before.recent_cases)
        self.assertGreater(after.expected_cases, before.expected_cases)
