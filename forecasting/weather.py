"""Daily weather for each district.

Real data comes from the free Open-Meteo API (no key needed). If the internet is
not available the same table can be filled with synthetic weather that follows
Rwanda's rainy seasons, so the rest of the system still works. Every row records
its source, and synthetic rows never replace real ones.
"""
import json
import math
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

import numpy as np

from locations.models import District

from .models import WeatherObservation

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
DAILY = "temperature_2m_mean,precipitation_sum"
ARCHIVE_DELAY_DAYS = 7          # the archive lags a few days behind today
BATCH = 10                      # districts per request


class WeatherUnavailable(Exception):
    """Raised when the Open-Meteo API cannot be reached."""


def _get_json(url, params, timeout=40):
    query = urllib.parse.urlencode(params, safe=",")
    request = urllib.request.Request(f"{url}?{query}", headers={"User-Agent": "rwanda-surveillance-student-project"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        raise WeatherUnavailable(str(error)) from error


def parse_open_meteo(payload, districts):
    """Turn an Open-Meteo response into rows (district, date, rain, temperature).

    One location returns a dictionary, several locations return a list in the
    same order as the coordinates we sent.
    """
    results = payload if isinstance(payload, list) else [payload]
    rows = []
    for district, result in zip(districts, results):
        daily = result.get("daily") or {}
        for day, rain, temp in zip(daily.get("time", []), daily.get("precipitation_sum", []), daily.get("temperature_2m_mean", [])):
            if rain is None or temp is None:
                continue
            rows.append((district, date.fromisoformat(day), float(rain), float(temp)))
    return rows


def fetch_open_meteo(districts, start, end):
    """Download daily weather for the districts between two dates (inclusive)."""
    rows = []
    archive_end = min(end, date.today() - timedelta(days=ARCHIVE_DELAY_DAYS))
    for i in range(0, len(districts), BATCH):
        chunk = districts[i : i + BATCH]
        coords = {
            "latitude": ",".join(str(d.latitude) for d in chunk),
            "longitude": ",".join(str(d.longitude) for d in chunk),
            "daily": DAILY,
            "timezone": "Africa/Kigali",
        }
        if start <= archive_end:
            payload = _get_json(ARCHIVE_URL, dict(coords, start_date=start.isoformat(), end_date=archive_end.isoformat()))
            rows += parse_open_meteo(payload, chunk)
        if end > archive_end:
            days_back = max((date.today() - max(start, archive_end + timedelta(days=1))).days, 0)
            payload = _get_json(FORECAST_URL, dict(coords, past_days=min(days_back + 1, 92), forecast_days=1))
            rows += [r for r in parse_open_meteo(payload, chunk) if archive_end < r[1] <= end]
    return rows


# ---------- Synthetic fallback ----------
# Average rain per day in each month (mm): long rains March to May, short rains October to December.
MONTHLY_RAIN = [3.5, 4.5, 6.5, 8.0, 6.5, 1.0, 0.5, 1.5, 3.5, 6.0, 7.5, 5.0]


def synthetic_rows(districts, start, end):
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    rows = []
    for district in districts:
        rng = np.random.RandomState(1000 + district.pk)
        wet_factor = 0.8 + 0.5 * rng.rand()                         # some districts are wetter
        base_temp = 18.0 + (float(district.longitude) - 29.0) * 2.2  # the east is warmer
        for day in days:
            mean_rain = MONTHLY_RAIN[day.month - 1] * wet_factor
            wet = rng.rand() < min(0.9, mean_rain / 9.0)
            rain = float(rng.exponential(mean_rain / max(min(0.9, mean_rain / 9.0), 0.05))) if wet else 0.0
            season = math.cos(2 * math.pi * (day.timetuple().tm_yday - 30) / 365.0)
            temp = base_temp + 0.8 * season - 0.03 * min(rain, 20) + rng.normal(0, 0.6)
            rows.append((district, day, round(rain, 1), round(temp, 1)))
    return rows


def store(rows, source):
    """Save rows. Real data replaces synthetic rows; synthetic data never replaces real rows."""
    if not rows:
        return 0
    keys = {(d.pk, day) for d, day, _, _ in rows}
    existing = {
        (o.district_id, o.date): o
        for o in WeatherObservation.objects.filter(
            district_id__in={k[0] for k in keys}, date__gte=min(k[1] for k in keys), date__lte=max(k[1] for k in keys)
        )
    }
    new, changed = [], []
    for district, day, rain, temp in rows:
        current = existing.get((district.pk, day))
        if current is None:
            new.append(WeatherObservation(district=district, date=day, rainfall_mm=rain, temperature_c=temp, source=source))
        elif source == WeatherObservation.Source.OPEN_METEO or current.source == WeatherObservation.Source.SYNTHETIC:
            current.rainfall_mm, current.temperature_c, current.source = rain, temp, source
            changed.append(current)
    WeatherObservation.objects.bulk_create(new, batch_size=2000)
    WeatherObservation.objects.bulk_update(changed, ["rainfall_mm", "temperature_c", "source"], batch_size=2000)
    return len(new) + len(changed)


def update_weather(start, end, synthetic=False):
    """Fill the weather table. Returns (rows saved, source used, message)."""
    districts = list(District.objects.all())
    if not synthetic:
        try:
            saved = store(fetch_open_meteo(districts, start, end), WeatherObservation.Source.OPEN_METEO)
            return saved, WeatherObservation.Source.OPEN_METEO, "Downloaded from Open-Meteo."
        except WeatherUnavailable as error:
            message = f"Open-Meteo could not be reached ({error}). Synthetic weather was used for missing days."
    else:
        message = "Synthetic weather was generated on request."
    saved = store(synthetic_rows(districts, start, end), WeatherObservation.Source.SYNTHETIC)
    return saved, WeatherObservation.Source.SYNTHETIC, message
