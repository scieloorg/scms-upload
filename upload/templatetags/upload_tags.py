from django import template


register = template.Library()


@register.filter()
def abbrev(text, delimiter='_'):
    return ''.join([c[0] for c in text.split(delimiter)])
