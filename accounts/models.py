from django.conf import settings
from django.db import models


class UserProfile(models.Model):
    """Extra information for each user: the district they work in."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    district = models.ForeignKey(
        "locations.District", on_delete=models.SET_NULL, null=True, blank=True, related_name="staff"
    )
    job_title = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=15, blank=True)

    def __str__(self):
        return f"Profile of {self.user.username}"
