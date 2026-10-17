from django.contrib import admin

from .models import CaseReport, Disease, Outbreak, Patient


@admin.register(Disease)
class DiseaseAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "category", "reporting", "alert_multiplier", "min_cases_for_alert", "is_active")
    list_filter = ("category", "reporting", "is_active")
    search_fields = ("name", "code")


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ("patient_code", "full_name", "age", "gender", "district")
    list_filter = ("gender", "district__province", "district")
    search_fields = ("patient_code", "full_name", "phone")
    readonly_fields = ("patient_code",)


@admin.register(CaseReport)
class CaseReportAdmin(admin.ModelAdmin):
    list_display = ("id", "patient", "disease", "district", "case_type", "status", "date_reported", "reported_by")
    list_filter = ("disease", "status", "case_type", "district__province", "district")
    search_fields = ("patient__full_name", "patient__patient_code")
    date_hierarchy = "date_reported"
    autocomplete_fields = ("patient",)
    list_select_related = ("patient", "disease", "district", "reported_by")


@admin.register(Outbreak)
class OutbreakAdmin(admin.ModelAdmin):
    list_display = ("disease", "district", "level", "status", "start_date", "end_date", "auto_detected")
    list_filter = ("status", "level", "disease", "district__province")
    filter_horizontal = ("cases",)
    date_hierarchy = "start_date"
