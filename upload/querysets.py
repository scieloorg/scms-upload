from django.apps import apps
from django.db.models import Q

from team.models import get_user_membership_ids
from upload import choices
from upload.permissions import ACCESS_ALL_PACKAGES


def scope_package_queryset(qs, user):
    if not user or not user.is_authenticated:
        return qs.none()

    if user.is_superuser:
        return qs

    own_unexpected_q = Q(
        creator=user,
        status=choices.PS_UNEXPECTED,
    )

    membership = get_user_membership_ids(user)
    journal_list_ids = membership.get("journal_list_ids")

    if not journal_list_ids:
        return qs.filter(own_unexpected_q).distinct()

    scope_q = (
        Q(journal__in=journal_list_ids)
        | Q(issue__journal__in=journal_list_ids)
        | Q(article__journal__in=journal_list_ids)
    )

    if user.has_perm(f"upload.{ACCESS_ALL_PACKAGES}"):
        return qs.filter(scope_q | own_unexpected_q).distinct()

    return qs.filter(
        Q(creator=user)
        & (
            Q(journal__isnull=True)
            | scope_q
            | Q(status=choices.PS_UNEXPECTED)
        )
    ).distinct()


def get_scoped_package_queryset(user):
    Package = apps.get_model("upload", "Package")

    return scope_package_queryset(Package.objects.all(), user)
