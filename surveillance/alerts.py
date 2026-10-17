"""Outbreak detection rule.

For every disease in every district we compare:

    current  = reports in the latest 7 days
    baseline = average weekly reports in the 4 weeks before that

Alert: current >= min_cases_for_alert and current >= alert_multiplier x baseline
Watch: current >= min_cases_for_alert and current >= 1.5 x baseline
Anything else is normal and is not returned.

This is a simplified rule for the project. Real surveillance systems use more careful
statistics (seasonal baselines, case definitions and so on).
"""
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Q
from django.utils import timezone

from .models import CaseReport

WATCH_FACTOR = Decimal("1.5")
LEVEL_ORDER = {"normal": 0, "watch": 1, "alert": 2}


def get_as_of_date():
    """Date the analysis is based on.

    Normally today. If the database has no report from the last 7 days (for
    example an old demo database), the latest report date is used instead so
    the dashboard still shows meaningful numbers. The pages show this date.
    """
    today = timezone.localdate()
    latest = CaseReport.objects.order_by("-date_reported").values_list("date_reported", flat=True).first()
    if latest is not None and (today - latest).days > 7:
        return latest
    return today


def classify(current, baseline, multiplier, minimum):
    """Return 'alert', 'watch' or 'normal' for one disease in one district."""
    multiplier = Decimal(str(multiplier))
    baseline = Decimal(str(baseline))
    if current < minimum:
        return "normal"
    if Decimal(current) >= multiplier * baseline:
        return "alert"
    if Decimal(current) >= WATCH_FACTOR * baseline:
        return "watch"
    return "normal"


def current_alerts(as_of=None, min_level="watch", disease=None):
    """List the districts and diseases that are on Watch or Alert.

    Each item is a dictionary with disease and district objects, the counts and
    the level. Sorted with alerts first, then by number of cases.
    """
    as_of = as_of or get_as_of_date()
    week_start = as_of - timedelta(days=6)            # latest 7 days, inclusive
    base_start = as_of - timedelta(days=34)           # the 28 days before that
    base_end = as_of - timedelta(days=7)

    reports = CaseReport.objects.filter(date_reported__gte=base_start, date_reported__lte=as_of, disease__is_active=True)
    if disease is not None:
        reports = reports.filter(disease=disease)
    rows = (
        reports.values("disease_id", "district_id")
        .annotate(
            current=Count("id", filter=Q(date_reported__gte=week_start)),
            previous=Count("id", filter=Q(date_reported__gte=base_start, date_reported__lte=base_end)),
        )
        .filter(current__gte=1)
    )

    from locations.models import District
    from .models import Disease

    diseases = {d.id: d for d in Disease.objects.all()}
    districts = {d.id: d for d in District.objects.select_related("province")}
    minimum_rank = LEVEL_ORDER[min_level]

    alerts = []
    for row in rows:
        dis = diseases[row["disease_id"]]
        baseline = Decimal(row["previous"]) / 4
        level = classify(row["current"], baseline, dis.alert_multiplier, dis.min_cases_for_alert)
        if LEVEL_ORDER[level] < minimum_rank or level == "normal":
            continue
        alerts.append(
            {
                "disease": dis,
                "district": districts[row["district_id"]],
                "current": row["current"],
                "baseline": baseline.quantize(Decimal("0.1")),
                "level": level,
            }
        )
    alerts.sort(key=lambda a: (-LEVEL_ORDER[a["level"]], -a["current"], a["disease"].name))
    return alerts
