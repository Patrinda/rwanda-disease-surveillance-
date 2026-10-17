from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.core.validators import RegexValidator

from .models import UserProfile

RW_PHONE = RegexValidator(
    r"^(\+?250|0)7[2389]\d{7}$",
    "Enter a Rwandan mobile number such as 0788123456 or +250788123456.",
)


class LoginForm(AuthenticationForm):
    """Login form with Bootstrap styling."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update({"class": "form-control", "placeholder": "Username", "autofocus": True})
        self.fields["password"].widget.attrs.update({"class": "form-control", "placeholder": "Password"})


class ProfileForm(forms.ModelForm):
    phone = forms.CharField(max_length=15, required=False, validators=[RW_PHONE])

    class Meta:
        model = UserProfile
        fields = ["job_title", "phone"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"
