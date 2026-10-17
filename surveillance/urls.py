from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("map/", views.outbreak_map, name="outbreak_map"),
    path("api/map-data/", views.map_data, name="map_data"),
    path("api/chart-data/", views.chart_data, name="chart_data"),
    # diseases
    path("diseases/", views.DiseaseListView.as_view(), name="disease_list"),
    path("diseases/add/", views.DiseaseCreateView.as_view(), name="disease_add"),
    path("diseases/<int:pk>/", views.DiseaseDetailView.as_view(), name="disease_detail"),
    path("diseases/<int:pk>/edit/", views.DiseaseUpdateView.as_view(), name="disease_edit"),
    path("diseases/<int:pk>/delete/", views.DiseaseDeleteView.as_view(), name="disease_delete"),
    # patients
    path("patients/", views.PatientListView.as_view(), name="patient_list"),
    path("patients/add/", views.PatientCreateView.as_view(), name="patient_add"),
    path("patients/<int:pk>/", views.PatientDetailView.as_view(), name="patient_detail"),
    path("patients/<int:pk>/edit/", views.PatientUpdateView.as_view(), name="patient_edit"),
    path("patients/<int:pk>/delete/", views.PatientDeleteView.as_view(), name="patient_delete"),
    # case reports
    path("reports/", views.ReportListView.as_view(), name="report_list"),
    path("reports/add/", views.ReportCreateView.as_view(), name="report_add"),
    path("reports/export.csv", views.ReportExportView.as_view(), name="report_export"),
    path("reports/<int:pk>/", views.ReportDetailView.as_view(), name="report_detail"),
    path("reports/<int:pk>/edit/", views.ReportUpdateView.as_view(), name="report_edit"),
    path("reports/<int:pk>/delete/", views.ReportDeleteView.as_view(), name="report_delete"),
    # outbreaks and alerts
    path("outbreaks/", views.OutbreakListView.as_view(), name="outbreak_list"),
    path("outbreaks/declare/", views.OutbreakCreateView.as_view(), name="outbreak_declare"),
    path("outbreaks/<int:pk>/", views.OutbreakDetailView.as_view(), name="outbreak_detail"),
    path("outbreaks/<int:pk>/close/", views.OutbreakCloseView.as_view(), name="outbreak_close"),
]
