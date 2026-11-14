"""Create (or show) the API key of a user.

    python manage.py create_api_token admin
    python manage.py create_api_token admin --new     replace the key with a new one
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from forecasting.models import ApiToken


class Command(BaseCommand):
    help = "Create or show the API key of a user."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--new", action="store_true", help="Replace the existing key.")

    def handle(self, *args, **options):
        user = get_user_model().objects.filter(username=options["username"]).first()
        if user is None:
            raise CommandError(f"There is no user called {options['username']}.")
        token, created = ApiToken.objects.get_or_create(user=user)
        if options["new"] and not created:
            token.regenerate()
        self.stdout.write(f"API key for {user.username}:")
        self.stdout.write(self.style.SUCCESS(token.key))
