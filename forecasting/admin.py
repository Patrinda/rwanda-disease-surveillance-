from django.contrib import admin

from .models import ApiToken, ModelRun, Prediction, WeatherObservation


@admin.register(WeatherObservation)
class WeatherAdmin(admin.ModelAdmin):
    list_display = ("district", "date", "rainfall_mm", "temperature_c", "source")
    list_filter = ("source", "district__province", "district")
    date_hierarchy = "date"


@admin.register(ModelRun)
class ModelRunAdmin(admin.ModelAdmin):
    list_display = ("version", "algorithm", "trained_at", "mae", "baseline_mae", "alert_auc", "is_active")
    list_filter = ("is_active",)
    readonly_fields = ("feature_importance", "backtest")


@admin.register(Prediction)
class PredictionAdmin(admin.ModelAdmin):
    list_display = ("disease", "district", "as_of", "expected_cases", "alert_probability", "recent_cases", "run")
    list_filter = ("disease", "district__province", "as_of")
    search_fields = ("disease__name", "district__name")
    list_select_related = ("disease", "district", "run")


@admin.register(ApiToken)
class ApiTokenAdmin(admin.ModelAdmin):
    list_display = ("user", "created_at", "last_used_at")
    readonly_fields = ("key", "created_at", "last_used_at")
