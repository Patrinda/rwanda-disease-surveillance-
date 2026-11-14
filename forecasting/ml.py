"""Forecasting model: training, saving, loading and predicting.

What the model predicts
    For one disease in one district, how many reports there will be in the next
    7 days, and from that the chance that the existing alert rule will fire.

How it learns
    Every day in the history is treated as "today". The inputs are what was known
    on that day (reports in each of the last four weeks, the usual weekly level,
    rainfall, temperature, time of year, the disease). The answer is the number of
    reports in the following 7 days. A gradient boosting model with Poisson loss is
    used because the answer is a small count. The model does not guess the number
    from nothing: it learns how much next week usually differs from the recent weekly
    level, so it can follow a sudden rise it has not seen before.

How it is checked
    The last 10 weeks are held out. The model is trained on earlier days only and
    scored on those unseen weeks against two simple rules: "next week equals this
    week" and "next week equals the 4 week average".
"""
import math
import warnings
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

import numpy as np
from django.conf import settings
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from locations.models import District
from surveillance.alerts import get_as_of_date
from surveillance.models import CaseReport, Disease

from .models import ModelRun, Prediction, WeatherObservation

MODEL_FILE = Path(settings.BASE_DIR) / "forecasting" / "model_store" / "forecast_model.joblib"
ALGORITHM = "HistGradientBoostingRegressor (Poisson loss)"
WARMUP = 55            # days of history needed before the first usable day
HORIZON = 7
TEST_DAYS = 70         # 10 weeks held out for checking
# Inputs used by the deployed model. Weather is available as an option (train_model --with-weather);
# on this fictional data it did not improve the forecast, so it is left out by default.
FEATURES = [
    "w0", "w1", "w2", "w3", "m4", "m8", "ratio", "trend", "district_recent", "disease_recent",
    "category_code", "multiplier", "min_cases",
]
WEATHER_FEATURES = ["rain7", "rain28", "temp7", "doy_sin", "doy_cos"]
CATEGORICAL = ["category_code"]
EPSILON = 0.1          # keeps the recent level above zero for diseases with no recent cases


class ModelUnavailable(Exception):
    """No trained model file, or the file cannot be used with the installed libraries."""


# ---------------------------------------------------------------- data
class Dataset:
    """Daily case counts and weather for every district and disease pair."""

    def __init__(self, start, end, districts, diseases):
        self.start, self.end = start, end
        self.districts, self.diseases = districts, diseases
        self.days = (end - start).days + 1
        self.nd, self.nz = len(districts), len(diseases)
        self.counts = np.zeros((self.nd * self.nz, self.days))
        self.rain = np.zeros((self.nd, self.days))
        self.temp = np.full((self.nd, self.days), 20.0)
        self.weather_sources = set()
        self.district_index = {d.pk: i for i, d in enumerate(districts)}
        self.disease_index = {z.pk: i for i, z in enumerate(diseases)}
        categories = sorted({z.category for z in diseases})
        self.category_code = np.array([categories.index(z.category) for z in diseases])
        self.multiplier = np.array([float(z.alert_multiplier) for z in diseases])
        self.min_cases = np.array([float(z.min_cases_for_alert) for z in diseases])

    def series(self, district_pk, disease_pk):
        return self.district_index[district_pk] * self.nz + self.disease_index[disease_pk]

    def add_count(self, district_pk, disease_pk, day, n):
        offset = (day - self.start).days
        if 0 <= offset < self.days and district_pk in self.district_index and disease_pk in self.disease_index:
            self.counts[self.series(district_pk, disease_pk), offset] += n

    def date_of(self, index):
        return self.start + timedelta(days=int(index))


def _fill_weather(ds):
    rows = WeatherObservation.objects.filter(date__gte=ds.start, date__lte=ds.end).values_list(
        "district_id", "date", "rainfall_mm", "temperature_c", "source"
    )
    seen = np.zeros((ds.nd, ds.days), dtype=bool)
    for district_pk, day, rain, temp, source in rows:
        i = ds.district_index.get(district_pk)
        if i is None:
            continue
        offset = (day - ds.start).days
        ds.rain[i, offset], ds.temp[i, offset], seen[i, offset] = rain, temp, True
        ds.weather_sources.add(source)
    for i in range(ds.nd):                       # days without weather get the district's average
        if seen[i].any() and not seen[i].all():
            ds.rain[i, ~seen[i]] = ds.rain[i, seen[i]].mean()
            ds.temp[i, ~seen[i]] = ds.temp[i, seen[i]].mean()


def load_dataset(end=None, days=420, api_rows=None):
    """Build the dataset from the database, or from rows downloaded from the API."""
    end = end or get_as_of_date()
    diseases = list(Disease.objects.filter(is_active=True).order_by("id"))
    districts = list(District.objects.order_by("id"))
    if api_rows is None:
        first = CaseReport.objects.order_by("date_reported").values_list("date_reported", flat=True).first()
        start = max(first or end, end - timedelta(days=days - 1))
        ds = Dataset(start, end, districts, diseases)
        grouped = (
            CaseReport.objects.filter(date_reported__gte=start, date_reported__lte=end, disease__is_active=True)
            .values("district_id", "disease_id", "date_reported").annotate(n=Count("id"))
        )
        for row in grouped:
            ds.add_count(row["district_id"], row["disease_id"], row["date_reported"], row["n"])
    else:
        by_name = {d.name: d.pk for d in districts}
        by_code = {z.code: z.pk for z in diseases}
        days_seen = [r["date_reported"] for r in api_rows]
        start = max(min(days_seen), end - timedelta(days=days - 1))
        ds = Dataset(start, end, districts, diseases)
        for r in api_rows:
            ds.add_count(by_name.get(r["district"]), by_code.get(r["disease_code"]), r["date_reported"], 1)
    _fill_weather(ds)
    return ds


# ------------------------------------------------------------ features
def make_features(ds, ts, series=None, names=None):
    """Feature matrix for the chosen days `ts` (indices into the dataset).

    Returns X with one row per (series, day), plus the series and day of every row.
    """
    ts = np.asarray(ts, dtype=int)
    idx = np.arange(ds.counts.shape[0]) if series is None else np.asarray(series, dtype=int)
    C = np.concatenate([np.zeros((ds.counts.shape[0], 1)), np.cumsum(ds.counts, axis=1)], axis=1)
    dist_idx, dis_idx = idx // ds.nz, idx % ds.nz

    def week(k):
        return C[np.ix_(idx, ts - 7 * k + 1)] - C[np.ix_(idx, ts - 7 * k - 6)]

    w = [week(k) for k in range(4)]
    usual = ((week(1) + week(2) + week(3) + week(4)) / 4.0).reshape(-1)      # the alert rule's baseline
    m4 = sum(w) / 4.0
    m8 = (C[np.ix_(idx, ts + 1)] - C[np.ix_(idx, ts - 55)]) / 8.0

    # all diseases together in the district (last 28 days), one disease nationally (last 7 days)
    dist_tot = np.zeros((ds.nd, ds.days))
    dis_tot = np.zeros((ds.nz, ds.days))
    for s in range(ds.counts.shape[0]):
        dist_tot[s // ds.nz] += ds.counts[s]
        dis_tot[s % ds.nz] += ds.counts[s]
    Cd = np.concatenate([np.zeros((ds.nd, 1)), np.cumsum(dist_tot, axis=1)], axis=1)
    Cz = np.concatenate([np.zeros((ds.nz, 1)), np.cumsum(dis_tot, axis=1)], axis=1)
    district_recent = Cd[np.ix_(dist_idx, ts + 1)] - Cd[np.ix_(dist_idx, ts - 27)]
    disease_recent = Cz[np.ix_(dis_idx, ts + 1)] - Cz[np.ix_(dis_idx, ts - 6)]

    Cr = np.concatenate([np.zeros((ds.nd, 1)), np.cumsum(ds.rain, axis=1)], axis=1)
    Ct = np.concatenate([np.zeros((ds.nd, 1)), np.cumsum(ds.temp, axis=1)], axis=1)
    rain7 = Cr[np.ix_(dist_idx, ts + 1)] - Cr[np.ix_(dist_idx, ts - 6)]
    rain28 = (Cr[np.ix_(dist_idx, ts + 1)] - Cr[np.ix_(dist_idx, ts - 27)]) / 4.0
    temp7 = (Ct[np.ix_(dist_idx, ts + 1)] - Ct[np.ix_(dist_idx, ts - 6)]) / 7.0

    doy = np.array([ds.date_of(t).timetuple().tm_yday for t in ts], dtype=float)
    angle = 2 * np.pi * doy / 365.25
    shape = w[0].shape
    full = lambda v: np.broadcast_to(v, shape)  # noqa: E731
    columns = {
        "w0": w[0], "w1": w[1], "w2": w[2], "w3": w[3], "m4": m4, "m8": m8,
        "ratio": (w[0] + 0.5) / (m4 + 0.5), "trend": w[0] - w[1],
        "district_recent": district_recent, "disease_recent": disease_recent,
        "doy_sin": full(np.sin(angle)[None, :]), "doy_cos": full(np.cos(angle)[None, :]),
        "rain7": rain7, "rain28": rain28, "temp7": temp7,
        "category_code": full(ds.category_code[dis_idx][:, None].astype(float)),
        "multiplier": full(ds.multiplier[dis_idx][:, None]), "min_cases": full(ds.min_cases[dis_idx][:, None]),
    }
    X = np.stack([np.asarray(columns[name]).reshape(-1) for name in (names or FEATURES)], axis=1)
    row_series = np.repeat(idx, len(ts))
    row_days = np.tile(ts, len(idx))
    return X, row_series, row_days, m4.reshape(-1), w[0].reshape(-1), usual


def targets(ds, row_series, row_days):
    C = np.concatenate([np.zeros((ds.counts.shape[0], 1)), np.cumsum(ds.counts, axis=1)], axis=1)
    return C[row_series, row_days + HORIZON + 1] - C[row_series, row_days + 1]


def level(w0, m4):
    """Recent weekly level. The model learns by how much next week differs from this level."""
    return 0.5 * w0 + 0.5 * m4 + EPSILON


def alert_threshold(ds, row_series, usual):
    """Weekly count that reaches the Alert level: the disease multiplier times the usual level (average of the 4 weeks before the current week), and at least the disease minimum."""
    dis = row_series % ds.nz
    return np.maximum(ds.min_cases[dis], np.ceil(ds.multiplier[dis] * usual - 1e-9))


def alert_probability(expected, threshold):
    """Chance that a Poisson count with mean `expected` reaches the alert threshold."""
    from scipy.stats import poisson

    return poisson.sf(threshold - 1, np.maximum(expected, 1e-9))


# ------------------------------------------------------------ training
def _new_regressor(names):
    from sklearn.ensemble import HistGradientBoostingRegressor

    return HistGradientBoostingRegressor(
        loss="poisson", max_iter=150, learning_rate=0.06, max_leaf_nodes=8, min_samples_leaf=100,
        l2_regularization=2.0, categorical_features=[names.index(c) for c in CATEGORICAL if c in names], random_state=42,
    )


def _poisson_deviance(y, p):
    from sklearn.metrics import mean_poisson_deviance

    return float(mean_poisson_deviance(y, np.maximum(p, 1e-6)))


def _synthetic_training_rows(ds, names):
    """Feature rows from generated outbreak history (see synthetic.py)."""
    from .synthetic import make_synthetic

    syn = make_synthetic(ds)
    days = np.arange(WARMUP, syn.days - HORIZON, 2)          # every second day is enough
    X, s, d, m4, w0, _ = make_features(syn, days, names=names)
    return X, targets(syn, s, d), m4, w0


def train(api_rows=None, data_source="database", use_weather=False, use_synthetic=True):
    """Train, check on the last 10 weeks, refit on everything, save the file and the ModelRun row."""
    import joblib
    import sklearn
    from sklearn.inspection import permutation_importance
    from sklearn.metrics import roc_auc_score

    use_synthetic = use_synthetic and not use_weather          # generated history has no weather
    names = FEATURES + (WEATHER_FEATURES if use_weather else [])
    ds = load_dataset(api_rows=api_rows)
    all_days = np.arange(WARMUP, ds.days - HORIZON)
    if len(all_days) < TEST_DAYS + 60:
        raise ValueError("There is not enough history to train. At least 6 months of reports are needed.")
    test_days = all_days[-TEST_DAYS:]
    train_days = all_days[: -(TEST_DAYS + HORIZON + 1)]

    X_tr, s_tr, d_tr, m4_tr, w0_tr, _ = make_features(ds, train_days, names=names)
    y_tr = targets(ds, s_tr, d_tr)
    synthetic_rows = 0
    if use_synthetic:
        extra = _synthetic_training_rows(ds, names)
        synthetic_rows = len(extra[1])
        X_tr, y_tr = np.vstack([X_tr, extra[0]]), np.concatenate([y_tr, extra[1]])
        m4_tr, w0_tr = np.concatenate([m4_tr, extra[2]]), np.concatenate([w0_tr, extra[3]])
    X_te, s_te, d_te, m4_te, w0_te, usual_te = make_features(ds, test_days, names=names)
    y_te = targets(ds, s_te, d_te)

    base_tr, base_te = level(w0_tr, m4_tr), level(w0_te, m4_te)
    check = _new_regressor(names).fit(X_tr, y_tr / base_tr, sample_weight=base_tr)
    pred = base_te * check.predict(X_te)
    naive, avg4 = w0_te, m4_te

    mae = lambda p: float(np.mean(np.abs(y_te - p)))  # noqa: E731
    rmse = lambda p: float(np.sqrt(np.mean((y_te - p) ** 2)))  # noqa: E731

    # national weekly totals, one point per unseen week
    backtest, nat_err, nat_err_naive = [], [], []
    for t in test_days[::-1][::HORIZON]:
        pick = d_te == t
        actual, model_total, naive_total = float(y_te[pick].sum()), float(pred[pick].sum()), float(naive[pick].sum())
        nat_err.append(abs(actual - model_total))
        nat_err_naive.append(abs(actual - naive_total))
        backtest.append({"week_end": str(ds.date_of(t + HORIZON)), "actual": round(actual, 1),
                         "predicted": round(model_total, 1), "naive": round(naive_total, 1)})
    backtest.reverse()

    # does the predicted chance of an Alert rank the real alert situations higher?
    threshold = alert_threshold(ds, s_te, usual_te)
    is_alert = (y_te >= threshold).astype(int)
    auc_model = auc_naive = None
    if 0 < is_alert.sum() < len(is_alert):
        auc_model = float(roc_auc_score(is_alert, alert_probability(pred, threshold)))
        auc_naive = float(roc_auc_score(is_alert, alert_probability(naive + EPSILON, threshold)))

    sample = np.random.RandomState(0).choice(len(y_te), size=min(15000, len(y_te)), replace=False)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        imp = permutation_importance(
            check, X_te[sample], y_te[sample] / base_te[sample], n_repeats=3, random_state=0,
            scoring="neg_mean_poisson_deviance", sample_weight=base_te[sample],
        )
    importance = {name: round(float(v), 5) for name, v in sorted(zip(names, imp.importances_mean), key=lambda p: -p[1])}

    # final model uses every day that has a known next week
    X_all, s_all, d_all, m4_all, w0_all, _ = make_features(ds, all_days, names=names)
    y_all = targets(ds, s_all, d_all)
    if use_synthetic:
        X_all, y_all = np.vstack([X_all, extra[0]]), np.concatenate([y_all, extra[1]])
        m4_all, w0_all = np.concatenate([m4_all, extra[2]]), np.concatenate([w0_all, extra[3]])
    base_all = level(w0_all, m4_all)
    final = _new_regressor(names).fit(X_all, y_all / base_all, sample_weight=base_all)
    version = timezone.localtime().strftime("%Y%m%d-%H%M%S")
    MODEL_FILE.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": final, "features": names, "version": version, "sklearn": sklearn.__version__}, MODEL_FILE)

    with transaction.atomic():
        ModelRun.objects.filter(is_active=True).update(is_active=False)
        run = ModelRun.objects.create(
            version=version, algorithm=ALGORITHM,
            data_source=data_source + (" + synthetic outbreaks" if use_synthetic else ""), synthetic_rows=synthetic_rows,
            weather_source=", ".join(sorted(ds.weather_sources)) or "none",
            history_start=ds.start, history_end=ds.end, training_rows=len(y_tr) - synthetic_rows + len(y_te), test_weeks=TEST_DAYS // 7,
            uses_weather=use_weather, features=names,
            deviance=_poisson_deviance(y_te, pred), baseline_deviance=_poisson_deviance(y_te, naive + EPSILON),
            avg4_deviance=_poisson_deviance(y_te, avg4 + EPSILON),
            mae=mae(pred), baseline_mae=mae(naive), rmse=rmse(pred), baseline_rmse=rmse(naive),
            national_mae=float(np.mean(nat_err)), national_baseline_mae=float(np.mean(nat_err_naive)),
            alert_events=int(is_alert.sum()), alert_auc=auc_model, baseline_auc=auc_naive,
            feature_importance=importance, backtest=backtest,
            notes=f"Held-out weeks: {len(test_days) // 7}. Row level MAE of the 4-week average rule: {mae(avg4):.4f}.",
        )
    return run


# ---------------------------------------------------------- predicting
_cache = {"mtime": None, "bundle": None}


def load_model():
    """Load the saved model once and reuse it until the file changes."""
    if not MODEL_FILE.exists():
        raise ModelUnavailable("No trained model found. Run: python manage.py train_model")
    mtime = MODEL_FILE.stat().st_mtime
    if _cache["mtime"] == mtime:
        return _cache["bundle"]
    import joblib

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            bundle = joblib.load(MODEL_FILE)
    except Exception as error:  # version mismatch, damaged file, missing library
        raise ModelUnavailable(f"The model file cannot be used here ({error}). Run: python manage.py train_model") from error
    if not set(FEATURES) <= set(bundle.get("features", [])):
        raise ModelUnavailable("The model was trained with different inputs. Run: python manage.py train_model")
    _cache.update(mtime=mtime, bundle=bundle)
    return bundle


def refresh_predictions(district=None, disease=None, as_of=None):
    """Predict next week for every district and disease (or just one pair) and store the result.

    Called after new reports arrive and by the `refresh_predictions` command.
    Returns the number of predictions saved.
    """
    run = ModelRun.objects.filter(is_active=True).first()
    if run is None:
        return 0
    bundle = load_model()
    as_of = as_of or get_as_of_date()
    ds = load_dataset(end=as_of, days=120)
    if ds.days <= WARMUP:
        return 0
    series = None
    if district is not None and disease is not None:
        if district.pk not in ds.district_index or disease.pk not in ds.disease_index:
            return 0
        series = [ds.series(district.pk, disease.pk)]
    elif district is not None:
        series = [ds.series(district.pk, z.pk) for z in ds.diseases]
    elif disease is not None:
        series = [ds.series(d.pk, disease.pk) for d in ds.districts]

    t = ds.days - 1
    X, row_series, _, m4, w0, usual = make_features(ds, [t], series=series, names=bundle["features"])
    expected = np.maximum(level(w0, m4) * bundle["model"].predict(X), 0)
    chance = alert_probability(expected, alert_threshold(ds, row_series, usual))
    week_start, week_end = as_of + timedelta(days=1), as_of + timedelta(days=HORIZON)
    rows = []
    for i, s in enumerate(row_series):
        rows.append(Prediction(
            run=run, district=ds.districts[s // ds.nz], disease=ds.diseases[s % ds.nz], as_of=as_of,
            week_start=week_start, week_end=week_end, recent_cases=int(w0[i]), usual_level=round(float(usual[i]), 2),
            expected_cases=round(float(expected[i]), 3), alert_probability=round(float(chance[i]), 4),
        ))
    with transaction.atomic():
        Prediction.objects.bulk_create(
            rows, batch_size=500, update_conflicts=True, unique_fields=["district", "disease", "as_of"],
            update_fields=["run", "week_start", "week_end", "recent_cases", "usual_level", "expected_cases", "alert_probability"],
        )
    return len(rows)
