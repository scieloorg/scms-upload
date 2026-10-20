import logging

from django.db import DatabaseError, OperationalError

from journal.models import JournalCollection
from team.authorization_matrix import (
    APP_ACCESS,
    FULL_ACCESS,
    GROUP_ACCESS,
    NO_ACCESS,
    READ_ACCESS,
    STAFF_APPS,
)
from team.constants import TeamGroups
from team.models import (
    CollectionTeamMember,
    CompanyTeamMember,
    JournalTeamMember,
    TeamRole,
    active_contract_queryset,
    get_user_membership_ids,
)

TEAM_PERMISSION_SCOPES = (
    (
        CollectionTeamMember,
        "collection_id",
        {
            TeamRole.MANAGER: TeamGroups.COLLECTION_ADMIN,
            TeamRole.MEMBER: TeamGroups.COLLECTION_MEMBER,
        },
    ),
    (
        JournalTeamMember,
        "journal_id",
        {
            TeamRole.MANAGER: TeamGroups.JOURNAL_ADMIN,
            TeamRole.MEMBER: TeamGroups.JOURNAL_MEMBER,
        },
    ),
    (
        CompanyTeamMember,
        "company_id",
        {
            TeamRole.MANAGER: TeamGroups.COMPANY_ADMIN,
            TeamRole.MEMBER: TeamGroups.COMPANY_MEMBER,
        },
    ),
)


def get_user_permission_journal_ids(user, app_label, permission):
    """Resolve custom permissions through the active role in each journal context."""
    if not user or not user.is_active or not user.has_perm(f"{app_label}.{permission}"):
        return set()

    rules = APP_ACCESS.get(app_label, {})
    journal_ids = set()
    for model, field, groups in TEAM_PERMISSION_SCOPES:
        roles = [
            role
            for role, group in groups.items()
            if permission in rules.get(group, {}).get("custom", ())
        ]
        if not roles:
            continue

        memberships = model.objects.filter(
            user=user,
            is_active_member=True,
            role__in=roles,
        ).values_list(field, flat=True)

        if model is CollectionTeamMember:
            ids = JournalCollection.objects.filter(
                collection_id__in=memberships,
            ).values_list("journal_id", flat=True)
        elif model is CompanyTeamMember:
            ids = (
                active_contract_queryset()
                .filter(
                    company_id__in=memberships,
                )
                .values_list("journal_id", flat=True)
            )
        else:
            ids = memberships

        journal_ids.update(ids)

    return journal_ids


def get_user_group_names(user):
    if not user or not user.is_authenticated:
        return set()

    return set(user.groups.values_list("name", flat=True))


def user_app_access(user, app_label):
    if not user or not user.is_authenticated:
        return NO_ACCESS
    if user.is_superuser:
        return FULL_ACCESS
    if user.is_staff and app_label in STAFF_APPS:
        return FULL_ACCESS

    levels = {
        GROUP_ACCESS[group_name]["apps"].get(app_label)
        for group_name in get_user_group_names(user)
        if group_name in GROUP_ACCESS
    }

    if FULL_ACCESS in levels:
        return FULL_ACCESS
    if READ_ACCESS in levels:
        return READ_ACCESS
    return NO_ACCESS


def get_user_accessible_apps(user):
    if not user or not user.is_authenticated:
        return set()
    if user.is_superuser:
        return {
            app_label
            for group_access in GROUP_ACCESS.values()
            for app_label in group_access["apps"]
        } | STAFF_APPS

    accessible_apps = {
        app_label
        for group_name in get_user_group_names(user)
        if group_name in GROUP_ACCESS
        for app_label in GROUP_ACCESS[group_name]["apps"]
    }
    if user.is_staff:
        accessible_apps.update(STAFF_APPS)

    return accessible_apps


def user_has_active_journal_scope(user):
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser:
        return True

    try:
        membership = get_user_membership_ids(user)
    except (OperationalError, DatabaseError):
        logging.exception("Unable to resolve authorization scope for user %s", user)
        return False

    return bool(
        membership.get("collection_list_ids") or membership.get("journal_list_ids")
    )
