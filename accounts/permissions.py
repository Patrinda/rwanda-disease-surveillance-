"""Mixins used by the class based views to enforce roles and district scope."""
from django.contrib.auth.mixins import AccessMixin
from django.core.exceptions import PermissionDenied

from .roles import ADMIN, OFFICER, REPORTER, get_role, has_role, user_district


class RoleRequiredMixin(AccessMixin):
    """Require a login and at least `minimum_role` (reporter, officer or admin).

    Anonymous visitors are sent to the login page. Logged in users without a
    high enough role receive a 403 page.
    """

    minimum_role = REPORTER

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not has_role(request.user, self.minimum_role):
            raise PermissionDenied("Your role does not allow this action.")
        return super().dispatch(request, *args, **kwargs)


def scope_by_district(queryset, user, field="district"):
    """Limit a queryset to the user's district (national administrators see everything)."""
    role = get_role(user)
    if role == ADMIN:
        return queryset
    district = user_district(user)
    if district is None:
        return queryset.none()
    return queryset.filter(**{field: district})


def can_edit_report(user, report):
    """Reporters edit their own reports, officers edit reports in their district, admins edit all."""
    role = get_role(user)
    if role == ADMIN:
        return True
    if role == OFFICER:
        return user_district(user) is not None and report.district_id == user_district(user).id
    if role == REPORTER:
        return report.reported_by_id == user.id
    return False
