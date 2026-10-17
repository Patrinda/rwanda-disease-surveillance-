from django import template
from django.utils.html import format_html

register = template.Library()

STATUS_CLASSES = {"active": "warning", "recovered": "success", "deceased": "dark"}
STATUS_ICONS = {"active": "bi-activity", "recovered": "bi-check-circle", "deceased": "bi-heartbreak"}
LEVEL_CLASSES = {"alert": "danger", "watch": "warning", "normal": "success", "open": "danger", "contained": "warning", "closed": "secondary"}
LEVEL_ICONS = {"alert": "bi-exclamation-octagon-fill", "watch": "bi-eye-fill", "normal": "bi-check-circle-fill",
               "open": "bi-broadcast", "contained": "bi-shield-check", "closed": "bi-lock-fill"}


@register.simple_tag(takes_context=True)
def nav_active(context, *prefixes):
    """Return 'active' when the current URL name starts with one of the prefixes."""
    match = context["request"].resolver_match
    name = match.url_name if match else ""
    return "active" if name and any(name.startswith(p) for p in prefixes) else ""


@register.simple_tag
def status_badge(value, label=None):
    """Small coloured badge with an icon, so colour is never the only signal."""
    value = str(value)
    css = STATUS_CLASSES.get(value, "secondary")
    text_class = "text-dark" if css == "warning" else ""
    return format_html('<span class="badge text-bg-{} {}"><i class="bi {} me-1"></i>{}</span>', css, text_class,
                       STATUS_ICONS.get(value, "bi-dot"), label or value.title())


@register.simple_tag
def level_badge(value, label=None):
    value = str(value)
    css = LEVEL_CLASSES.get(value, "secondary")
    text_class = "text-dark" if css == "warning" else ""
    return format_html('<span class="badge text-bg-{} {}"><i class="bi {} me-1"></i>{}</span>', css, text_class,
                       LEVEL_ICONS.get(value, "bi-dot"), label or value.title())


@register.simple_tag(takes_context=True)
def url_replace(context, **kwargs):
    """Current query string with some values replaced (used by the pagination links)."""
    params = context["request"].GET.copy()
    for key, value in kwargs.items():
        params[key] = value
    return params.urlencode()
