import json

from django import template
from django.utils.translation import gettext_lazy as _

register = template.Library()


@register.filter()
def abbrev(text, delimiter="_"):
    return "".join([c[0] for c in text.split(delimiter)])


@register.filter
def pretty_json(value):
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


@register.filter
def validation_value(value):
    if value is None:
        return _("Not provided")

    if isinstance(value, str):
        return value or _("Empty value")

    return pretty_json(value)
