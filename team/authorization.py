import logging

from django.db import DatabaseError, OperationalError

from team.authorization_matrix import (
    FULL_ACCESS,
    GROUP_ACCESS,
    NO_ACCESS,
    READ_ACCESS,
    STAFF_APPS,
)
from team.models import get_user_membership_ids


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
