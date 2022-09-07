from django import template


register = template.Library()


@register.filter()
def groups_names(groups):
    return '; '.join([g.name for g in groups.all()])
