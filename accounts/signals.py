from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import UserProfile
from .roles import ensure_groups


@receiver(post_save, sender=get_user_model())
def create_profile(sender, instance, created, **kwargs):
    """Every new user automatically gets an empty profile."""
    if created:
        UserProfile.objects.get_or_create(user=instance)


def create_groups(sender, **kwargs):
    """Runs after migrate so the three role groups always exist."""
    ensure_groups()
