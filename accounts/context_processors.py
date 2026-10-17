"""Adds role information and the alert badge to every template."""
from .roles import ADMIN, OFFICER, REPORTER, get_role, has_role


def navigation(request):
    user = request.user
    if not user.is_authenticated:
        return {"role": None}
    role = get_role(user)
    context = {
        "role": role,
        "role_label": {ADMIN: "National Administrator", OFFICER: "District Officer", REPORTER: "Facility Reporter"}.get(
            role, "No role assigned"
        ),
        "is_admin_role": role == ADMIN,
        "can_declare": has_role(user, OFFICER),
        "can_export": has_role(user, OFFICER),
        "can_add_data": has_role(user, REPORTER),
        "alert_count": 0,
    }
    try:
        from surveillance.alerts import current_alerts

        context["alert_count"] = len(current_alerts(min_level="alert"))
    except Exception:  # never break a page because of the badge
        pass
    return context
