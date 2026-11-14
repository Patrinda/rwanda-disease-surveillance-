from django.urls import path

from . import api, views

urlpatterns = [
    # pages
    path("forecast/", views.forecast_page, name="forecast"),
    path("forecast/refresh/", views.forecast_refresh, name="forecast_refresh"),
    path("api/guide/", views.api_guide, name="api_guide"),
    path("api/token/", views.api_token, name="api_token"),
    path("api/forecast-data/", views.forecast_data, name="forecast_data"),
    # JSON API, version 1
    path("api/v1/", api.index, name="api_index"),
    path("api/v1/status/", api.status, name="api_status"),
    path("api/v1/reports/", api.reports, name="api_reports"),
    path("api/v1/predictions/", api.predictions, name="api_predictions"),
    path("api/v1/weather/", api.weather, name="api_weather"),
]
