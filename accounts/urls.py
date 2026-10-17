from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

urlpatterns = [
    path("login/", views.SignInView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("profile/", views.ProfileView.as_view(), name="profile"),
]
