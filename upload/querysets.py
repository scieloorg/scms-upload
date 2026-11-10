from django.apps import apps
from django.contrib.auth import get_user_model
from django.db.models import Exists, OuterRef, Q
from django.db.models.functions import Coalesce

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
        colleague_contracts = active_contract_queryset().filter(
            company_id__in=membership["company_list_ids"],
            company__team_members__user_id=OuterRef("creator_id"),
            company__team_members__is_active_member=True,
            company__team_members__user__is_active=True,
            journal_id=Coalesce(
                OuterRef("journal_id"),
                OuterRef("issue__journal_id"),
                OuterRef("article__journal_id"),
            ),
        )
        responsible_q |= Q(Exists(colleague_contracts))

    if access_journal_ids:
        responsible_q |= package_journal_filter(access_journal_ids)

    return qs.filter(responsible_q).distinct()


def get_scoped_package_queryset(user, permission=None):
    Package = apps.get_model("upload", "Package")

    return scope_package_queryset(Package.objects.all(), user, permission=permission)


def correction_assignee_queryset(package):
    User = get_user_model()
    creator = package.creator
    journal = package.effective_journal
    journal_id = journal.pk if journal else None
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
    journal = package.effective_journal
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


def document_queue_filter(queue, user, status=None):
    if queue == "archived" or (queue == "all" and status in choices.ARCHIVED_STATUSES):
        return Q(status__in=choices.ARCHIVED_STATUSES)

    active = ~Q(status__in=choices.ARCHIVED_STATUSES)

    if queue == "mine":
        return active & Q(
            assignee=user,
            status__in=(*choices.REVIEW_STATUSES, choices.PS_PENDING_CORRECTION),
        )

    if queue == "review":
        return active & Q(status__in=choices.REVIEW_STATUSES)

    if queue == "corrections":
        return active & Q(status=choices.PS_PENDING_CORRECTION)

    return active
