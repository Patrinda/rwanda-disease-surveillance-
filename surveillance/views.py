import csv
from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, ProtectedError, Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from accounts.permissions import RoleRequiredMixin, can_edit_report, scope_by_district
from accounts.roles import ADMIN, OFFICER, REPORTER, get_role, has_role
from locations.models import District, Province

from . import analytics
from .alerts import current_alerts, get_as_of_date
from .forms import CaseReportForm, DiseaseForm, OutbreakForm, PatientForm
from .models import CaseReport, Disease, Outbreak, Patient


# --------------------------------------------------------------------------
# Error pages
# --------------------------------------------------------------------------
def permission_denied(request, exception=None):
    return render(request, "403.html", {"message": str(exception) if exception else ""}, status=403)


def page_not_found(request, exception=None):
    return render(request, "404.html", status=404)


# --------------------------------------------------------------------------
# Home, dashboard, map (function based views)
# --------------------------------------------------------------------------
def home(request):
    """Public landing page: national totals only, no patient information."""
    today = timezone.localdate()
    context = {
        "disease_count": Disease.objects.filter(is_active=True).count(),
        "district_count": District.objects.count(),
        "reports_30_days": CaseReport.objects.filter(date_reported__gte=today - timedelta(days=30)).count(),
        "alert_count": len(current_alerts(min_level="alert")),
        "as_of": get_as_of_date(),
    }
    return render(request, "surveillance/home.html", context)


def _require_role(request, minimum=REPORTER):
    """Used by function views: login first, then a role check."""
    if not request.user.is_authenticated:
        return redirect(f"{reverse('login')}?next={request.path}")
    if not has_role(request.user, minimum):
        raise PermissionDenied("Your account has no role yet. Ask a National Administrator to assign one.")
    return None


def dashboard(request):
    denied = _require_role(request)
    if denied:
        return denied
    filters = analytics.parse_filters(request.GET)
    reports = analytics.filtered_reports(filters)
    numbers = analytics.summary_numbers(reports)
    as_of = get_as_of_date()
    alerts = current_alerts(as_of=as_of)
    context = {
        "filters": filters,
        "numbers": numbers,
        "as_of": as_of,
        "is_stale": as_of != timezone.localdate(),
        "disease_count": Disease.objects.filter(is_active=True).count(),
        "patient_count": scope_by_district(Patient.objects.all(), request.user).count(),
        "open_outbreaks": Outbreak.objects.filter(status="open").count(),
        "alerts": alerts,
        "alert_level_count": sum(1 for a in alerts if a["level"] == "alert"),
        "recent_reports": scope_by_district(CaseReport.objects.select_related("patient", "disease", "district"), request.user)[:8],
        "diseases": Disease.objects.filter(is_active=True),
        "provinces": Province.objects.all(),
    }
    return render(request, "surveillance/dashboard.html", context)


def chart_data(request):
    denied = _require_role(request)
    if denied:
        return JsonResponse({"error": "Sign in first."}, status=403)
    return JsonResponse(analytics.chart_payload(analytics.parse_filters(request.GET)))


def outbreak_map(request):
    denied = _require_role(request)
    if denied:
        return denied
    context = {
        "diseases": Disease.objects.filter(is_active=True),
        "selected": request.GET.get("disease", ""),
        "as_of": get_as_of_date(),
    }
    return render(request, "surveillance/map.html", context)


def map_data(request):
    denied = _require_role(request)
    if denied:
        return JsonResponse({"error": "Sign in first."}, status=403)
    disease = None
    raw = request.GET.get("disease", "")
    if raw.isdigit():
        disease = Disease.objects.filter(pk=raw).first()
    payload = analytics.map_payload(
        disease=disease,
        date_from=parse_date(request.GET.get("date_from", "") or ""),
        date_to=parse_date(request.GET.get("date_to", "") or ""),
    )
    return JsonResponse(payload)


# --------------------------------------------------------------------------
# Diseases (admin manages, everyone signed in can read)
# --------------------------------------------------------------------------
class DiseaseListView(RoleRequiredMixin, ListView):
    model = Disease
    template_name = "surveillance/disease_list.html"
    context_object_name = "diseases"
    paginate_by = 15

    def get_queryset(self):
        qs = Disease.objects.annotate(report_total=Count("cases")).order_by("name")
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(code__icontains=q))
        for key in ("category", "reporting"):
            value = self.request.GET.get(key, "")
            if value:
                qs = qs.filter(**{key: value})
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(categories=Disease.Category.choices, reportings=Disease.Reporting.choices, q=self.request.GET.get("q", ""))
        return ctx


class DiseaseDetailView(RoleRequiredMixin, DetailView):
    model = Disease
    template_name = "surveillance/disease_detail.html"
    context_object_name = "disease"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        reports = self.object.cases.all()
        ctx["numbers"] = analytics.summary_numbers(reports)
        ctx["by_district"] = reports.values("district__name", "district_id").annotate(n=Count("id")).order_by("-n")[:8]
        ctx["recent_reports"] = scope_by_district(reports.select_related("patient", "district"), self.request.user)[:8]
        ctx["alerts"] = [a for a in current_alerts() if a["disease"].id == self.object.id]
        return ctx


class DiseaseFormMixin(RoleRequiredMixin):
    minimum_role = ADMIN
    model = Disease
    form_class = DiseaseForm
    template_name = "surveillance/form.html"
    success_url = reverse_lazy("disease_list")


class DiseaseCreateView(DiseaseFormMixin, CreateView):
    extra_context = {"title": "Add disease", "cancel_url": reverse_lazy("disease_list")}

    def form_valid(self, form):
        messages.success(self.request, f"Disease \"{form.instance.name}\" was added.")
        return super().form_valid(form)


class DiseaseUpdateView(DiseaseFormMixin, UpdateView):
    extra_context = {"title": "Edit disease", "cancel_url": reverse_lazy("disease_list")}

    def form_valid(self, form):
        messages.success(self.request, f"Disease \"{form.instance.name}\" was updated.")
        return super().form_valid(form)


class ConfirmDeleteMixin(RoleRequiredMixin):
    """Delete with a confirmation page and a friendly message when records depend on the object."""

    minimum_role = ADMIN
    template_name = "surveillance/confirm_delete.html"
    object_label = "record"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(object_label=self.object_label, cancel_url=self.get_success_url())
        return ctx

    def form_valid(self, form):
        try:
            response = super().form_valid(form)
        except ProtectedError:
            messages.error(self.request, f"This {self.object_label} cannot be deleted because other records depend on it.")
            return redirect(self.get_success_url())
        messages.success(self.request, f"The {self.object_label} was deleted.")
        return response


class DiseaseDeleteView(ConfirmDeleteMixin, DeleteView):
    model = Disease
    object_label = "disease"
    success_url = reverse_lazy("disease_list")


# --------------------------------------------------------------------------
# Patients
# --------------------------------------------------------------------------
class PatientScopeMixin(RoleRequiredMixin):
    model = Patient

    def get_queryset(self):
        return scope_by_district(Patient.objects.select_related("district"), self.request.user)


class PatientListView(PatientScopeMixin, ListView):
    template_name = "surveillance/patient_list.html"
    context_object_name = "patients"
    paginate_by = 15

    def get_queryset(self):
        qs = super().get_queryset().annotate(case_total=Count("cases")).order_by("-id")
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(Q(full_name__icontains=q) | Q(patient_code__icontains=q) | Q(phone__icontains=q))
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = self.request.GET.get("q", "")
        return ctx


class PatientDetailView(PatientScopeMixin, DetailView):
    template_name = "surveillance/patient_detail.html"
    context_object_name = "patient"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["cases"] = self.object.cases.select_related("disease", "district")
        return ctx


class PatientCreateView(PatientScopeMixin, CreateView):
    form_class = PatientForm
    template_name = "surveillance/form.html"
    extra_context = {"title": "Register patient", "cancel_url": reverse_lazy("patient_list")}

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"Patient {self.object.patient_code} was registered.")
        return response

    def get_success_url(self):
        return reverse("patient_detail", args=[self.object.pk])


class PatientUpdateView(PatientScopeMixin, UpdateView):
    form_class = PatientForm
    template_name = "surveillance/form.html"
    extra_context = {"title": "Edit patient", "cancel_url": reverse_lazy("patient_list")}

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, f"Patient {self.object.patient_code} was updated.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("patient_detail", args=[self.object.pk])


class PatientDeleteView(ConfirmDeleteMixin, DeleteView):
    model = Patient
    object_label = "patient"
    success_url = reverse_lazy("patient_list")


# --------------------------------------------------------------------------
# Case reports
# --------------------------------------------------------------------------
def filter_reports(params, queryset):
    """Apply the search and filter form of the report list (also used by the CSV export)."""
    q = (params.get("q") or "").strip()
    if q:
        queryset = queryset.filter(Q(patient__full_name__icontains=q) | Q(patient__patient_code__icontains=q))
    for key in ("disease", "district", "status", "case_type"):
        value = params.get(key) or ""
        if value:
            queryset = queryset.filter(**{key: value})
    date_from, date_to = parse_date(params.get("date_from") or ""), parse_date(params.get("date_to") or "")
    if date_from:
        queryset = queryset.filter(date_reported__gte=date_from)
    if date_to:
        queryset = queryset.filter(date_reported__lte=date_to)
    return queryset


class ReportScopeMixin(RoleRequiredMixin):
    model = CaseReport

    def get_queryset(self):
        qs = CaseReport.objects.select_related("patient", "disease", "district", "reported_by")
        return scope_by_district(qs, self.request.user)


class ReportListView(ReportScopeMixin, ListView):
    template_name = "surveillance/report_list.html"
    context_object_name = "reports"
    paginate_by = 15

    def get_queryset(self):
        return filter_reports(self.request.GET, super().get_queryset())

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        params = self.request.GET.copy()
        params.pop("page", None)
        ctx.update(
            diseases=Disease.objects.all(),
            districts=District.objects.all(),
            statuses=CaseReport.Status.choices,
            case_types=CaseReport.CaseType.choices,
            f=self.request.GET,
            querystring=params.urlencode(),
        )
        return ctx


class ReportDetailView(ReportScopeMixin, DetailView):
    template_name = "surveillance/report_detail.html"
    context_object_name = "report"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["can_edit"] = can_edit_report(self.request.user, self.object)
        ctx["outbreaks"] = self.object.outbreaks.select_related("disease", "district")
        return ctx


class ReportCreateView(ReportScopeMixin, CreateView):
    form_class = CaseReportForm
    template_name = "surveillance/form.html"
    extra_context = {"title": "New case report", "cancel_url": reverse_lazy("report_list")}

    def get_initial(self):
        initial = super().get_initial()
        patient_id = self.request.GET.get("patient", "")
        if patient_id.isdigit():
            initial["patient"] = patient_id
        return initial

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        form.instance.reported_by = self.request.user
        response = super().form_valid(form)
        messages.success(self.request, "Case report created.")
        return response

    def get_success_url(self):
        return reverse("report_detail", args=[self.object.pk])


class ReportUpdateView(ReportScopeMixin, UpdateView):
    form_class = CaseReportForm
    template_name = "surveillance/form.html"
    extra_context = {"title": "Edit case report", "cancel_url": reverse_lazy("report_list")}

    def get_object(self, queryset=None):
        report = super().get_object(queryset)
        if not can_edit_report(self.request.user, report):
            raise PermissionDenied("You can only edit reports that you filed or that belong to your district.")
        return report

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, "Case report updated.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("report_detail", args=[self.object.pk])


class ReportDeleteView(ConfirmDeleteMixin, DeleteView):
    model = CaseReport
    object_label = "case report"
    success_url = reverse_lazy("report_list")


class ReportExportView(RoleRequiredMixin, View):
    """Download the filtered reports as a CSV file (no names or phone numbers)."""

    minimum_role = OFFICER

    def get(self, request):
        qs = scope_by_district(
            CaseReport.objects.select_related("patient", "disease", "district__province", "reported_by"), request.user
        )
        qs = filter_reports(request.GET, qs)
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="case_reports_{timezone.localdate()}.csv"'
        writer = csv.writer(response)
        writer.writerow(["report_id", "patient_code", "age", "gender", "disease", "district", "province",
                         "case_type", "status", "date_onset", "date_reported", "reported_by"])
        for r in qs.iterator():
            writer.writerow([
                r.id, r.patient.patient_code, r.patient.age, r.patient.get_gender_display(), r.disease.name,
                r.district.name, r.district.province.name, r.get_case_type_display(), r.get_status_display(),
                r.date_onset, r.date_reported, r.reported_by.username if r.reported_by else "",
            ])
        return response


# --------------------------------------------------------------------------
# Outbreaks and alerts
# --------------------------------------------------------------------------
class OutbreakListView(RoleRequiredMixin, ListView):
    model = Outbreak
    template_name = "surveillance/outbreak_list.html"
    context_object_name = "outbreaks"
    paginate_by = 12

    def get_queryset(self):
        qs = Outbreak.objects.select_related("disease", "district__province", "declared_by").annotate(case_total=Count("cases")).order_by("-start_date", "-id")
        status = self.request.GET.get("status", "")
        if status:
            qs = qs.filter(status=status)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        as_of = get_as_of_date()
        open_pairs = set(Outbreak.objects.filter(status="open").values_list("disease_id", "district_id"))
        alerts = current_alerts(as_of=as_of)
        for a in alerts:
            a["declared"] = (a["disease"].id, a["district"].id) in open_pairs
        ctx.update(alerts=alerts, as_of=as_of, statuses=Outbreak.Status.choices, selected_status=self.request.GET.get("status", ""))
        return ctx


class OutbreakDetailView(RoleRequiredMixin, DetailView):
    model = Outbreak
    template_name = "surveillance/outbreak_detail.html"
    context_object_name = "outbreak"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["linked_cases"] = scope_by_district(
            self.object.cases.select_related("patient", "district", "disease"), self.request.user
        )
        ctx["linked_total"] = self.object.cases.count()
        return ctx


class OutbreakCreateView(RoleRequiredMixin, CreateView):
    minimum_role = OFFICER
    model = Outbreak
    form_class = OutbreakForm
    template_name = "surveillance/form.html"
    extra_context = {"title": "Declare outbreak", "cancel_url": reverse_lazy("outbreak_list")}

    def get_initial(self):
        initial = super().get_initial()
        for key in ("disease", "district", "level"):
            value = self.request.GET.get(key, "")
            if value:
                initial[key] = value
        return initial

    def form_valid(self, form):
        outbreak = form.instance
        outbreak.declared_by = self.request.user
        outbreak.status = Outbreak.Status.OPEN
        outbreak.auto_detected = any(
            a["disease"].id == outbreak.disease_id and a["district"].id == outbreak.district_id for a in current_alerts()
        )
        response = super().form_valid(form)
        # Link the recent reports (last 35 days) that belong to this disease and district.
        since = get_as_of_date() - timedelta(days=35)
        self.object.cases.set(
            CaseReport.objects.filter(disease=outbreak.disease, district=outbreak.district, date_reported__gte=since)
        )
        messages.success(self.request, f"Outbreak declared. {self.object.cases.count()} recent reports were linked to it.")
        return response

    def get_success_url(self):
        return reverse("outbreak_detail", args=[self.object.pk])


class OutbreakCloseView(RoleRequiredMixin, View):
    minimum_role = OFFICER

    def post(self, request, pk):
        outbreak = get_object_or_404(Outbreak, pk=pk)
        if outbreak.status == Outbreak.Status.OPEN:
            outbreak.status = Outbreak.Status.CLOSED
            outbreak.end_date = timezone.localdate()
            outbreak.save(update_fields=["status", "end_date"])
            messages.success(request, "The outbreak was closed.")
        return redirect("outbreak_detail", pk=pk)

    def get(self, request, pk):
        raise Http404
