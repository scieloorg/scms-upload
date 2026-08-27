from io import StringIO

import pytest
from django.contrib.auth.models import Group, Permission

from team.authorization_matrix import (
    FULL_ACCESS,
    GROUP_ACCESS,
    MANAGE_ACTIONS,
    READ_ACCESS,
)
from team.constants import TeamGroups
from team.management.commands.create_user_groups import Command
from team.signals import system_group_update

pytestmark = pytest.mark.django_db


def expected_permissions(group_name):
    group_access = GROUP_ACCESS[group_name]
    expected = set()
    action_by_access = {
        FULL_ACCESS: MANAGE_ACTIONS,
        READ_ACCESS: ("view",),
    }

    for app_label, access in group_access["apps"].items():
        if app_label in group_access["models"]:
            continue

        prefixes = tuple(f"{action}_" for action in action_by_access[access])
        expected.update(
            (permission.content_type.app_label, permission.codename)
            for permission in Permission.objects.filter(
                content_type__app_label=app_label
            ).select_related("content_type")
            if permission.codename.startswith(prefixes)
        )

    for app_label, matrix in group_access["models"].items():
        wildcard_actions = matrix.get("*", ())
        if wildcard_actions:
            prefixes = tuple(f"{action}_" for action in wildcard_actions)
            expected.update(
                (permission.content_type.app_label, permission.codename)
                for permission in Permission.objects.filter(
                    content_type__app_label=app_label
                ).select_related("content_type")
                if permission.codename.startswith(prefixes)
            )

        expected.update(
            (app_label, f"{action}_{model_name}")
            for model_name, actions in matrix.items()
            if model_name != "*"
            for action in actions
        )

    expected.update(
        (app_label, codename)
        for app_label, codenames in group_access["custom"].items()
        for codename in codenames
    )

    return expected


@pytest.mark.parametrize("group_name", TeamGroups.ALL)
def test_command_applies_exact_permission_matrix(group_name):
    Command().handle(stdout=StringIO(), sync_users=False)

    group = Group.objects.get(name=group_name)
    actual = set(group.permissions.values_list("content_type__app_label", "codename"))

    assert actual == expected_permissions(group_name)


def test_command_is_idempotent():
    command = Command()
    command.handle(stdout=StringIO(), sync_users=True)
    first_state = {
        group.name: set(group.permissions.values_list("pk", flat=True))
        for group in Group.objects.filter(name__in=TeamGroups.ALL)
    }

    command.handle(stdout=StringIO(), sync_users=True)
    second_state = {
        group.name: set(group.permissions.values_list("pk", flat=True))
        for group in Group.objects.filter(name__in=TeamGroups.ALL)
    }

    assert second_state == first_state


def test_command_does_not_assign_delete_permissions():
    Command().handle(stdout=StringIO(), sync_users=False)

    for group in Group.objects.filter(name__in=TeamGroups.ALL):
        assert not group.permissions.filter(codename__startswith="delete_").exists()


def test_command_removes_group_without_active_membership(django_user_model):
    user = django_user_model.objects.create_user(username="stale-group")
    with system_group_update():
        group, _ = Group.objects.get_or_create(name=TeamGroups.COLLECTION_ADMIN)
        user.groups.add(group)

    Command().handle(stdout=StringIO(), sync_users=True)

    assert not user.groups.filter(name=TeamGroups.COLLECTION_ADMIN).exists()
