from django.db.models import Q

from team.models import get_user_membership_ids


def scope_by_membership(
    user,
    queryset,
    collection_field=None,
    journal_field=None,
    company_field=None,
):
    if not user or not user.is_authenticated:
        return queryset.none()
    if user.is_superuser:
        return queryset

    membership = get_user_membership_ids(user)
    collection_ids = membership.get("collection_list_ids") or []
    journal_ids = membership.get("journal_list_ids") or []
    company_ids = membership.get("company_list_ids") or []

    if not (collection_ids or journal_ids or company_ids):
        return queryset.none()

    query = Q()

    if collection_field and collection_ids:
        query |= Q(**{f"{collection_field}__in": collection_ids})

    if journal_field and journal_ids:
        query |= Q(**{f"{journal_field}__in": journal_ids})

    if company_field and company_ids:
        query |= Q(**{f"{company_field}__in": company_ids})

    if not query:
        return queryset.none()

    return queryset.filter(query)
