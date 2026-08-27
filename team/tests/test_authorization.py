import pytest
from django.contrib.auth.models import Group

from team.authorization import get_user_accessible_apps, user_app_access
from team.authorization_matrix import (
    APP_ACCESS,
    FULL_ACCESS,
    GROUP_ACCESS,
    MANAGE_ACTIONS,
    NO_ACCESS,
    READ_ACCESS,
    build_group_access,
)
from team.constants import TeamGroups
from team.signals import system_group_update


def test_authorization_matrix_has_valid_complete_structure():
    assert set(GROUP_ACCESS) == set(TeamGroups.ALL)

    for groups in APP_ACCESS.values():
        assert set(groups) <= set(TeamGroups.ALL)
        for rules in groups.values():
            assert set(rules) <= {"access", "models", "custom"}
            if "access" in rules:
                assert rules["access"] in {FULL_ACCESS, READ_ACCESS}

    for group_access in GROUP_ACCESS.values():
        assert set(group_access) == {"apps", "models", "custom"}
        assert set(group_access["apps"].values()) <= {FULL_ACCESS, READ_ACCESS}
        assert set(group_access["models"]) <= set(group_access["apps"])


def test_build_group_access_converts_each_rule_section():
    app_access = {
        "example": {
            TeamGroups.COLLECTION_ADMIN: {
                "access": FULL_ACCESS,
                "models": {"item": MANAGE_ACTIONS},
                "custom": ("approve_item",),
            },
            TeamGroups.COLLECTION_MEMBER: {"access": READ_ACCESS},
        }
    }

    group_access = build_group_access(app_access)

    assert group_access[TeamGroups.COLLECTION_ADMIN] == {
        "apps": {"example": FULL_ACCESS},
        "models": {"example": {"item": MANAGE_ACTIONS}},
        "custom": {"example": ("approve_item",)},
    }
    assert group_access[TeamGroups.COLLECTION_MEMBER] == {
        "apps": {"example": READ_ACCESS},
        "models": {},
        "custom": {},
    }


@pytest.mark.django_db
def test_runtime_access_uses_highest_level_across_groups(django_user_model):
    user = django_user_model.objects.create_user(username="multiple-access-levels")
    with system_group_update():
        collection_group, _ = Group.objects.get_or_create(
            name=TeamGroups.COLLECTION_MEMBER
        )
        journal_group, _ = Group.objects.get_or_create(name=TeamGroups.JOURNAL_MEMBER)
        user.groups.add(collection_group, journal_group)

    assert user_app_access(user, "article") == FULL_ACCESS
    assert user_app_access(user, "files_storage") == NO_ACCESS
    assert "upload" in get_user_accessible_apps(user)
