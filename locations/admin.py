from django.contrib import admin

from .models import District, Province


@admin.register(Province)
class ProvinceAdmin(admin.ModelAdmin):
    list_display = ("name", "district_count")
    search_fields = ("name",)

    @admin.display(description="Districts")
    def district_count(self, obj):
        return obj.districts.count()


@admin.register(District)
class DistrictAdmin(admin.ModelAdmin):
    list_display = ("name", "province", "latitude", "longitude")
    list_filter = ("province",)
    search_fields = ("name",)
