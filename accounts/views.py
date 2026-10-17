from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView
from django.urls import reverse_lazy
from django.views.generic import UpdateView

from .forms import LoginForm, ProfileForm


class SignInView(LoginView):
    """Login page (AdminLTE login card)."""

    template_name = "registration/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True


class ProfileView(LoginRequiredMixin, UpdateView):
    """Shows the signed in user's profile and lets them edit job title and phone."""

    form_class = ProfileForm
    template_name = "accounts/profile.html"
    success_url = reverse_lazy("profile")

    def get_object(self, queryset=None):
        return self.request.user.profile

    def form_valid(self, form):
        messages.success(self.request, "Your profile was updated.")
        return super().form_valid(form)
