from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from accounts.permissions import scope_by_district
from accounts.roles import ADMIN, OFFICER, REPORTER, get_role, has_role, user_district
from locations.models import Province
from surveillance.alerts import get_as_of_date
from surveillance.models import CaseReport, Disease
from surveillance.views import _require_role

from . import ml, services
from .models import ApiToken, Prediction

WEEKS_SHOWN = 14


def _filtered_predictions(request):
    queryset = services.latest_predictions(request.user)
    disease = request.GET.get("disease", "")
    province = request.GET.get("province", "")
    risk = request.GET.get("risk", "")
    if disease.isdigit():
        queryset = queryset.filter(disease_id=disease)
    if province.isdigit():
        queryset = queryset.filter(district__province_id=province)
    if risk == "high":
        queryset = queryset.filter(alert_probability__gte=0.5)
    elif risk == "moderate":
        queryset = queryset.filter(alert_probability__gte=0.2, alert_probability__lt=0.5)
    return queryset.order_by("-alert_probability", "-expected_cases")


def forecast_page(request):
    denied = _require_role(request)
    if denied:
        return denied
    queryset = _filtered_predictions(request)
    rows = list(queryset.filter(Q(expected_cases__gte=0.5) | Q(alert_probability__gte=0.02))[:25])
    context = {
        "rows": rows,
        "run": services.active_run(),
        "weather": services.weather_summary(request.user),
        "diseases": Disease.objects.filter(is_active=True),
        "provinces": Province.objects.all(),
        "filters": {"disease": request.GET.get("disease", ""), "province": request.GET.get("province", ""), "risk": request.GET.get("risk", "")},
        "latest": Prediction.objects.order_by("-as_of").values_list("as_of", flat=True).first(),
        "incoming": scope_by_district(CaseReport.objects.select_related("patient", "disease", "district"), request.user).order_by("-created_at")[:6],
        "total_expected": round(sum(p.expected_cases for p in queryset), 1),
    }
    return render(request, "forecasting/forecast.html", context)


@require_POST
def forecast_refresh(request):
    denied = _require_role(request, minimum=OFFICER)
    if denied:
        return denied
    district = None if get_role(request.user) == ADMIN else user_district(request.user)
    try:
        saved = ml.refresh_predictions(district=district)
    except ml.ModelUnavailable as error:
        messages.error(request, str(error))
    else:
        if saved:
            messages.success(request, f"Forecast refreshed: {saved} predictions saved.")
        else:
            messages.warning(request, "No model is trained yet, so nothing was refreshed.")
    return redirect(request.POST.get("next") or "forecast")


def api_guide(request):
    denied = _require_role(request)
    if denied:
        return denied
    token = ApiToken.objects.filter(user=request.user).first()
    return render(request, "forecasting/api_guide.html", {"token": token, "base_url": request.build_absolute_uri("/").rstrip("/")})


@require_POST
def api_token(request):
    denied = _require_role(request)
    if denied:
        return denied
    token, created = ApiToken.objects.get_or_create(user=request.user)
    if not created:
        token.regenerate()
    messages.success(request, "Your API key is ready. Keep it private.")
    return redirect("api_guide")


def forecast_data(request):
    """Weekly reports for the dashboard chart, plus the forecast for next week."""
    denied = _require_role(request)
    if denied:
        return JsonResponse({"error": "Sign in first."}, status=403)
    as_of = get_as_of_date()
    disease = request.GET.get("disease", "")
    province = request.GET.get("province", "")
    reports = scope_by_district(CaseReport.objects.all(), request.user)
    predictions = services.latest_predictions(request.user)
    if disease.isdigit():
        reports, predictions = reports.filter(disease_id=disease), predictions.filter(disease_id=disease)
    if province.isdigit():
        reports, predictions = reports.filter(district__province_id=province), predictions.filter(district__province_id=province)

    first_day = as_of - timedelta(days=7 * WEEKS_SHOWN - 1)
    per_day = dict(reports.filter(date_reported__gte=first_day, date_reported__lte=as_of).values_list("date_reported").annotate(n=Count("id")))
    weeks = []
    for k in range(WEEKS_SHOWN - 1, -1, -1):
        end = as_of - timedelta(days=7 * k)
        total = sum(per_day.get(end - timedelta(days=i), 0) for i in range(7))
        weeks.append({"end": end, "total": total})

    expected = round(sum(p.expected_cases for p in predictions), 1)
    probable = round(sum(p.alert_probability for p in predictions), 1)
    run = services.active_run()
    unfiltered = not disease.isdigit() and not province.isdigit() and get_role(request.user) == ADMIN
    backtest = []
    if run and unfiltered:
        backtest = [{"label": b["week_end"], "predicted": b["predicted"]} for b in run.backtest]
    return JsonResponse({
        "labels": [w["end"].strftime("%d %b") for w in weeks],
        "actual": [w["total"] for w in weeks],
        "ends": [str(w["end"]) for w in weeks],
        "forecast": {"label": (as_of + timedelta(days=7)).strftime("%d %b"), "value": expected, "expected_alerts": probable},
        "backtest": backtest,
        "has_model": run is not None,
    })
