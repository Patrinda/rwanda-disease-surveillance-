"""Roles are Django Groups. This module holds their names and small helpers."""
from django.contrib.auth.models import Group

ROLE_REPORTER = "Facility Reporter"
ROLE_OFFICER = "District Officer"
ROLE_ADMIN = "National Administrator"
ALL_ROLES = (ROLE_REPORTER, ROLE_OFFICER, ROLE_ADMIN)

# Short keys used inside the code and templates
REPORTER, OFFICER, ADMIN = "reporter", "officer", "admin"
RANK = {REPORTER: 1, OFFICER: 2, ADMIN: 3}


def ensure_groups():
    """Create the three role groups if they do not exist yet."""
    for name in ALL_ROLES:
        Group.objects.get_or_create(name=name)


def get_role(user):
    """Return 'admin', 'officer', 'reporter' or None for the given user."""
    if not user.is_authenticated:
        return None
    if user.is_superuser:
        return ADMIN
    names = set(user.groups.values_list("name", flat=True))
    if ROLE_ADMIN in names:
        return ADMIN
    if ROLE_OFFICER in names:
        return OFFICER
    if ROLE_REPORTER in names:
        return REPORTER
    return None


def has_role(user, minimum):
    """True when the user's role is at least `minimum` (reporter < officer < admin)."""
    role = get_role(user)
    return role is not None and RANK[role] >= RANK[minimum]


def user_district(user):
    """District the user works in, or None."""
    profile = getattr(user, "profile", None)
    return profile.district if profile else None
