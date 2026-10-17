"""Queries behind the dashboard cards, charts, map and district pages."""
from collections import defaultdict
from datetime import date, timedelta

from django.db.models import Count, Q
from django.db.models.functions import TruncMonth
from django.utils.dateparse import parse_date

from locations.models import District, Province

from .alerts import current_alerts, get_as_of_date
from .models import CaseReport, Disease

AGE_BANDS = [("0-4", 0, 4), ("5-14", 5, 14), ("15-24", 15, 24), ("25-44", 25, 44), ("45-64", 45, 64), ("65+", 65, 200)]


def first_of_month(d):
    return d.replace(day=1)


def add_months(d, n):
    month_index = d.year * 12 + (d.month - 1) + n
    return date(month_index // 12, month_index % 12 + 1, 1)


def parse_filters(params):
    """Read the dashboard filters (disease, province, date_from, date_to) from request.GET."""
    disease = Disease.objects.filter(pk=params.get("disease")).first() if str(params.get("disease", "")).isdigit() else None
    province = Province.objects.filter(pk=params.get("province")).first() if str(params.get("province", "")).isdigit() else None
    date_from = parse_date(params.get("date_from", "") or "")
    date_to = parse_date(params.get("date_to", "") or "")
    return {"disease": disease, "province": province, "date_from": date_from, "date_to": date_to}


def filtered_reports(filters):
    qs = CaseReport.objects.all()
    if filters["disease"]:
        qs = qs.filter(disease=filters["disease"])
    if filters["province"]:
        qs = qs.filter(district__province=filters["province"])
    if filters["date_from"]:
        qs = qs.filter(date_reported__gte=filters["date_from"])
    if filters["date_to"]:
        qs = qs.filter(date_reported__lte=filters["date_to"])
    return qs


def summary_numbers(reports):
    counts = reports.aggregate(
        total=Count("id"),
        active=Count("id", filter=Q(status="active")),
        recovered=Count("id", filter=Q(status="recovered")),
        deceased=Count("id", filter=Q(status="deceased")),
    )
    total = counts["total"] or 0
    counts["recovery_rate"] = round(100 * counts["recovered"] / total, 1) if total else 0
    counts["fatality_rate"] = round(100 * counts["deceased"] / total, 1) if total else 0
    return counts


def month_window(filters, as_of):
    """First day of every month shown on the trend chart (12 months by default)."""
    if filters["date_from"] or filters["date_to"]:
        end = first_of_month(filters["date_to"] or as_of)
        start = first_of_month(filters["date_from"] or add_months(end, -11))
        months = []
        current = start
        while current <= end and len(months) < 36:
            months.append(current)
            current = add_months(current, 1)
        return months or [end]
    end = first_of_month(as_of)
    return [add_months(end, i) for i in range(-11, 1)]


def monthly_counts(reports, months):
    rows = (
        reports.filter(date_reported__gte=months[0])
        .annotate(month=TruncMonth("date_reported"))
        .values("month")
        .annotate(n=Count("id"))
    )
    lookup = {r["month"]: r["n"] for r in rows}
    return [lookup.get(m, 0) for m in months]


def chart_payload(filters):
    """Everything the four dashboard charts need, as plain Python data."""
    as_of = get_as_of_date()
    reports = filtered_reports(filters)

    by_district = list(
        reports.values("district__name").annotate(n=Count("id")).order_by("-n", "district__name")[:10]
    )

    disease_rows = list(reports.values("disease__name").annotate(n=Count("id")).order_by("-n", "disease__name"))
    top, rest = disease_rows[:6], disease_rows[6:]
    by_disease = [{"label": r["disease__name"], "value": r["n"]} for r in top]
    if rest:
        by_disease.append({"label": "Other diseases", "value": sum(r["n"] for r in rest)})

    months = month_window(filters, as_of)
    trend = {
        "labels": [m.strftime("%b %Y") for m in months],
        "series": [{"label": filters["disease"].name if filters["disease"] else "All diseases", "data": monthly_counts(reports, months)}],
    }
    if not filters["disease"]:
        rvf = Disease.objects.filter(code="RVF").first()
        if rvf:
            trend["series"].append({"label": rvf.name, "data": monthly_counts(reports.filter(disease=rvf), months)})

    aggregates = {}
    for label, lo, hi in AGE_BANDS:
        for sex in ("M", "F"):
            aggregates[f"{sex}_{lo}"] = Count(
                "id", filter=Q(patient__gender=sex, patient__age__gte=lo, patient__age__lte=hi)
            )
    counts = reports.aggregate(**aggregates)
    age_gender = {
        "labels": [b[0] for b in AGE_BANDS],
        "female": [counts[f"F_{b[1]}"] for b in AGE_BANDS],
        "male": [counts[f"M_{b[1]}"] for b in AGE_BANDS],
    }

    return {
        "as_of": as_of.isoformat(),
        "by_district": {"labels": [r["district__name"] for r in by_district], "data": [r["n"] for r in by_district]},
        "by_disease": by_disease,
        "trend": trend,
        "age_gender": age_gender,
    }


def map_payload(disease=None, date_from=None, date_to=None):
    """One record per district for the Leaflet map."""
    as_of = get_as_of_date()
    reports = CaseReport.objects.all()
    if disease:
        reports = reports.filter(disease=disease)
    if date_from:
        reports = reports.filter(date_reported__gte=date_from)
    if date_to:
        reports = reports.filter(date_reported__lte=date_to)

    totals = {
        r["district_id"]: r
        for r in reports.values("district_id").annotate(
            total=Count("id"),
            active=Count("id", filter=Q(status="active")),
            deceased=Count("id", filter=Q(status="deceased")),
        )
    }
    breakdown = defaultdict(list)
    for r in reports.values("district_id", "disease__name").annotate(n=Count("id")).order_by("-n"):
        breakdown[r["district_id"]].append({"disease": r["disease__name"], "cases": r["n"]})

    alerts = defaultdict(list)
    for a in current_alerts(as_of=as_of, disease=disease):
        alerts[a["district"].id].append(
            {"disease": a["disease"].name, "level": a["level"], "current": a["current"], "baseline": float(a["baseline"])}
        )

    districts = []
    for d in District.objects.select_related("province"):
        t = totals.get(d.id, {})
        district_alerts = alerts.get(d.id, [])
        level = "alert" if any(a["level"] == "alert" for a in district_alerts) else ("watch" if district_alerts else "normal")
        districts.append(
            {
                "id": d.id,
                "name": d.name,
                "province": d.province.name,
                "latitude": float(d.latitude),
                "longitude": float(d.longitude),
                "total": t.get("total", 0),
                "active": t.get("active", 0),
                "deceased": t.get("deceased", 0),
                "top_diseases": breakdown.get(d.id, [])[:5],
                "alerts": district_alerts,
                "level": level,
                "url": f"/locations/districts/{d.id}/",
            }
        )
    return {
        "as_of": as_of.isoformat(),
        "max_total": max((d["total"] for d in districts), default=0),
        "total_cases": sum(d["total"] for d in districts),
        "districts": districts,
    }


def district_context(district):
    """Numbers and chart data for one district profile page."""
    as_of = get_as_of_date()
    reports = CaseReport.objects.filter(district=district)
    months = [add_months(first_of_month(as_of), i) for i in range(-11, 1)]
    by_disease = list(reports.values("disease__name").annotate(n=Count("id")).order_by("-n")[:8])
    return {
        "numbers": summary_numbers(reports),
        "alerts": [a for a in current_alerts(as_of=as_of) if a["district"].id == district.id],
        "recent_reports": reports.select_related("patient", "disease")[:10],
        "chart": {
            "disease_labels": [r["disease__name"] for r in by_disease],
            "disease_data": [r["n"] for r in by_disease],
            "trend_labels": [m.strftime("%b %Y") for m in months],
            "trend_data": monthly_counts(reports, months),
        },
        "outbreaks": district.outbreaks.select_related("disease").filter(status="open"),
        "as_of": as_of,
    }
