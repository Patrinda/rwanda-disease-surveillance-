"""Project level URL configuration.

Each app owns its own urls.py and is included here.
"""
from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "Rwanda Disease Surveillance Administration"
admin.site.site_title = "Surveillance Admin"
admin.site.index_title = "Manage surveillance records"

handler403 = "surveillance.views.permission_denied"
handler404 = "surveillance.views.page_not_found"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("locations/", include("locations.urls")),
    path("", include("surveillance.urls")),
]
