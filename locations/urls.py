from django.urls import path

from . import views

urlpatterns = [
    path("districts/", views.DistrictListView.as_view(), name="district_list"),
    path("districts/<int:pk>/", views.DistrictDetailView.as_view(), name="district_detail"),
]
