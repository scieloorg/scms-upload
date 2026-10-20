from django.apps import apps
from django.contrib.auth import get_user_model
from django.db.models import Q

from team.authorization import get_user_permission_journal_ids
from team.models import (
    CollectionTeamMember,
    CompanyTeamMember,
    JournalTeamMember,
    active_contract_queryset,
    get_user_membership_ids,
)
from upload import choices
from upload.permissions import ACCESS_PACKAGES, REQUEST_CORRECTION


def package_journal_filter(journal_ids):
    return (
        Q(journal__in=journal_ids)
        | Q(journal__isnull=True, issue__journal__in=journal_ids)
        | Q(
            journal__isnull=True,
            issue__journal__isnull=True,
            article__journal__in=journal_ids,
        )
    )


def scope_package_queryset(qs, user, permission=None):
    if not user or not user.is_authenticated or not user.is_active:
        return qs.none()

    if user.is_superuser:
        return qs

    if permission:
        journal_ids = get_user_permission_journal_ids(user, "upload", permission)
        qs = qs.filter(package_journal_filter(journal_ids))

    own_unexpected_q = Q(
        creator=user,
        status=choices.PS_UNEXPECTED,
    )

    membership = get_user_membership_ids(user)
    journal_list_ids = membership.get("journal_list_ids")

    if not journal_list_ids:
        return qs.filter(own_unexpected_q).distinct()

    scope_q = package_journal_filter(journal_list_ids)
    access_journal_ids = get_user_permission_journal_ids(
        user, "upload", ACCESS_PACKAGES
    )

    own_q = Q(creator=user) & (
        Q(journal__isnull=True) | scope_q | Q(status=choices.PS_UNEXPECTED)
    )
    responsible_q = own_q | (Q(assignee=user) & scope_q)
    if user.has_perm(f"upload.{REQUEST_CORRECTION}"):
        for company_id in membership["company_list_ids"]:
            colleague_ids = CompanyTeamMember.objects.filter(
                company_id=company_id,
                is_active_member=True,
                user__is_active=True,
            ).values_list("user_id", flat=True)
            journal_ids = (
                active_contract_queryset()
                .filter(
                    company_id=company_id,
                )
                .values_list("journal_id", flat=True)
            )
            company_scope = package_journal_filter(journal_ids)
            responsible_q |= Q(creator_id__in=colleague_ids) & company_scope

    if access_journal_ids:
        responsible_q |= package_journal_filter(access_journal_ids)

    return qs.filter(responsible_q | own_unexpected_q).distinct()


def get_scoped_package_queryset(user, permission=None):
    Package = apps.get_model("upload", "Package")

    return scope_package_queryset(Package.objects.all(), user, permission=permission)


def correction_assignee_queryset(package):
    User = get_user_model()
    creator = package.creator
    journal_id = package.journal_id
    if not journal_id and package.issue_id:
        journal_id = package.issue.journal_id
    if not journal_id and package.article_id:
        journal_id = package.article.journal_id
    if not creator or not journal_id:
        return User.objects.none()

    creator_scope = get_user_membership_ids(creator)
    company_ids = (
        active_contract_queryset()
        .filter(
            journal_id=journal_id,
            company_id__in=creator_scope["company_list_ids"],
        )
        .values_list("company_id", flat=True)
    )
    colleague_ids = CompanyTeamMember.objects.filter(
        company_id__in=company_ids,
        is_active_member=True,
    ).values_list("user_id", flat=True)
    candidates = Q(pk__in=colleague_ids)
    if journal_id in creator_scope["journal_list_ids"]:
        candidates |= Q(pk=creator.pk)
    return User.objects.filter(candidates, is_active=True).distinct()


def review_assignee_queryset(package):
    from_scope = correction_assignee_queryset(package)
    User = get_user_model()
    journal = package.journal or (package.issue.journal if package.issue_id else None)
    if not journal and package.article_id:
        journal = package.article.journal
    if not journal:
        return User.objects.none()

    collection_ids = journal.journal_collections.values_list("collection_id", flat=True)
    collection_users = CollectionTeamMember.objects.filter(
        collection_id__in=collection_ids,
        is_active_member=True,
    ).values_list("user_id", flat=True)
    journal_users = JournalTeamMember.objects.filter(
        journal=journal,
        is_active_member=True,
    ).values_list("user_id", flat=True)
    return User.objects.filter(
        Q(pk__in=collection_users) | Q(pk__in=journal_users) | Q(pk__in=from_scope),
        is_active=True,
    ).distinct()
