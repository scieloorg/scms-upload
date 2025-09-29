# =======================
# 3. core/templatetags/settings_tags.py
# =======================

from django import template
from django.conf import settings

register = template.Library()


@register.simple_tag
def get_setting(name, default=""):
    """
    Template tag para acessar qualquer configuração do settings
    Uso: {% get_setting 'COMPANY_NAME' %}
    """
    return getattr(settings, name, default)
