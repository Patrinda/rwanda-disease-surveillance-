"""JSON API, version 1.

Programs sign in with a token in the Authorization header (Authorization: Token <key>).
A signed in browser session may also read (GET) the data. Sending data (POST) needs a token.
"""
import json
from datetime import timedelta
from functools import wraps

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from accounts.permissions import scope_by_district
from accounts.roles import OFFICER, REPORTER, get_role, has_role
from locations.models import District
from surveillance.alerts import get_as_of_date
from surveillance.models import CaseReport, Disease

from . import services
from .models import ApiToken, ModelRun, Prediction, WeatherObservation


def _user_from_token(request):
    header = request.headers.get("Authorization", "")
    if not header.lower().startswith("token "):
        return None
    token = ApiToken.objects.select_related("user").filter(key=header[6:].strip(), user__is_active=True).first()
    if token is None:
        return None
    token.last_used_at = timezone.now()
    token.save(update_fields=["last_used_at"])
    return token.user


def api_endpoint(minimum=REPORTER, methods=("GET",)):
    """Check the method, the sign in (token or session) and the role, and answer errors as JSON."""

    def decorator(view):
        @csrf_exempt
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if request.method not in methods:
                return JsonResponse({"error": f"Method {request.method} is not allowed here."}, status=405)
            user = _user_from_token(request)
            if user is None and request.method == "GET" and request.user.is_authenticated:
                user = request.user
            if user is None:
                return JsonResponse({"error": "Authentication needed. Send the header: Authorization: Token <your key>."}, status=401)
            if not has_role(user, minimum):
                return JsonResponse({"error": "Your role does not allow this."}, status=403)
            request.api_user = user
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


def _page(request, queryset, serializer, default=100, maximum=500):
    try:
        limit = min(max(int(request.GET.get("limit", default)), 1), maximum)
        offset = max(int(request.GET.get("offset", 0)), 0)
    except ValueError:
        limit, offset = default, 0
    total = queryset.count()
    items = [serializer(obj) for obj in queryset[offset : offset + limit]]
    return JsonResponse({"count": total, "limit": limit, "offset": offset,
                         "next_offset": offset + limit if offset + limit < total else None, "results": items})


def _report_json(r):
    return {
        "id": r.pk, "patient_code": r.patient.patient_code, "disease": r.disease.name, "disease_code": r.disease.code,
        "district": r.district.name, "case_type": r.case_type, "status": r.status,
        "date_onset": str(r.date_onset), "date_reported": str(r.date_reported),
    }


def _prediction_json(p):
    return {
        "district": p.district.name, "province": p.district.province.name, "disease": p.disease.name,
        "disease_code": p.disease.code, "as_of": str(p.as_of), "week_start": str(p.week_start), "week_end": str(p.week_end),
        "recent_cases": p.recent_cases, "usual_level": p.usual_level, "expected_cases": round(p.expected_cases, 2),
        "alert_probability": round(p.alert_probability, 3), "risk": p.risk, "model_version": p.run.version,
    }


@api_endpoint()
def index(request):
    return JsonResponse({
        "name": "Rwanda Disease Surveillance API", "version": 1,
        "endpoints": {
            "GET /api/v1/status/": "Health of the system and the active model.",
            "GET /api/v1/reports/": "Case reports (filters: disease, district, from, to, limit, offset).",
            "POST /api/v1/reports/": "Send a new case report. The forecast for that district is updated at once.",
            "GET /api/v1/predictions/": "Next week forecast (filters: disease, district, min_probability, limit, offset).",
            "GET /api/v1/weather/": "Daily rainfall and temperature (filters: district, days).",
        },
    })


@api_endpoint()
def status(request):
    run = services.active_run()
    latest = Prediction.objects.order_by("-as_of").values_list("as_of", flat=True).first()
    return JsonResponse({
        "ok": True, "as_of": str(get_as_of_date()), "reports": scope_by_district(CaseReport.objects.all(), request.api_user).count(),
        "model": None if run is None else {
            "version": run.version, "algorithm": run.algorithm, "trained_at": run.trained_at.isoformat(),
            "deviance": round(run.deviance, 4), "baseline_deviance": round(run.baseline_deviance, 4), "improvement_percent": run.improvement_percent, "alert_auc": run.alert_auc,
        },
        "latest_forecast_day": str(latest) if latest else None,
    })


@api_endpoint(methods=("GET", "POST"))
def reports(request):
    if request.method == "POST":
        try:
            payload = json.loads(request.body or b"{}")
            if not isinstance(payload, dict):
                raise ValueError
        except ValueError:
            return JsonResponse({"error": "Send a JSON object."}, status=400)
        form = services.IncomingReportForm(payload, user=request.api_user)
        if not form.is_valid():
            return JsonResponse({"errors": form.errors.get_json_data(escape_html=True)}, status=400)
        try:
            report = services.ingest_report(form)
        except Exception as error:  # validation errors from the model rules
            detail = getattr(error, "message_dict", None) or {"error": list(getattr(error, "messages", [str(error)]))}
            return JsonResponse({"errors": detail}, status=400)
        return JsonResponse({"created": True, "report": _report_json(report)}, status=201)

    queryset = scope_by_district(CaseReport.objects.select_related("patient", "disease", "district"), request.api_user)
    if request.GET.get("disease"):
        key = request.GET["disease"]
        queryset = queryset.filter(disease__code__iexact=key) | queryset.filter(disease__name__iexact=key)
    if request.GET.get("district"):
        queryset = queryset.filter(district__name__iexact=request.GET["district"])
    if request.GET.get("from"):
        queryset = queryset.filter(date_reported__gte=request.GET["from"])
    if request.GET.get("to"):
        queryset = queryset.filter(date_reported__lte=request.GET["to"])
    return _page(request, queryset.order_by("-date_reported", "-id"), _report_json)


@api_endpoint()
def predictions(request):
    queryset = services.latest_predictions(request.api_user)
    if request.GET.get("disease"):
        key = request.GET["disease"]
        queryset = queryset.filter(disease__code__iexact=key) | queryset.filter(disease__name__iexact=key)
    if request.GET.get("district"):
        queryset = queryset.filter(district__name__iexact=request.GET["district"])
    try:
        minimum = float(request.GET.get("min_probability", 0))
    except ValueError:
        minimum = 0
    queryset = queryset.filter(alert_probability__gte=minimum).select_related("run")
    return _page(request, queryset.order_by("-alert_probability", "-expected_cases"), _prediction_json)


@api_endpoint()
def weather(request):
    try:
        days = min(max(int(request.GET.get("days", 7)), 1), 120)
    except ValueError:
        days = 7
    last = WeatherObservation.objects.order_by("-date").values_list("date", flat=True).first()
    queryset = scope_by_district(WeatherObservation.objects.select_related("district"), request.api_user)
    if last:
        queryset = queryset.filter(date__gt=last - timedelta(days=days))
    if request.GET.get("district"):
        queryset = queryset.filter(district__name__iexact=request.GET["district"])
    return _page(request, queryset.order_by("-date", "district__name"), lambda w: {
        "district": w.district.name, "date": str(w.date), "rainfall_mm": w.rainfall_mm,
        "temperature_c": w.temperature_c, "source": w.source}, default=200, maximum=2000)
