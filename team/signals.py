import threading
from contextlib import contextmanager

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db.models.signals import post_delete, post_save, pre_delete, pre_save

from collection.models import Collection

from .constants import TeamGroups
from .models import CollectionTeamMember, CompanyTeamMember, JournalTeamMember, TeamRole

_TEAM_MEMBER_RELATIONS = {
    CollectionTeamMember: "collection",
    JournalTeamMember: "journal",
    CompanyTeamMember: "company",
}

_local_state = threading.local()


@contextmanager
def system_group_update():
    previous = getattr(_local_state, "in_system_group_update", False)
    _local_state.in_system_group_update = True
    try:
        yield
    finally:
        _local_state.in_system_group_update = previous


def is_system_group_update():
    return getattr(_local_state, "in_system_group_update", False)


def _roles_for_user(model_class, user):
    if user is None:
        return set()

    relation_field = _TEAM_MEMBER_RELATIONS[model_class]
    filters = {
        "user": user,
        "is_active_member": True,
        f"{relation_field}__isnull": False,
    }

    return set(model_class.objects.filter(**filters).values_list("role", flat=True))


def _sync_group(user, group_name, should_belong):
    if user is None:
        return

    with system_group_update():
        group, _ = Group.objects.get_or_create(name=group_name)
        if should_belong:
            user.groups.add(group)
        else:
            user.groups.remove(group)


def sync_user_groups(user):
    if user is None:
        return

    collection_roles = _roles_for_user(CollectionTeamMember, user)
    journal_roles = _roles_for_user(JournalTeamMember, user)
    company_roles = _roles_for_user(CompanyTeamMember, user)

    _sync_group(
        user,
        TeamGroups.COLLECTION_ADMIN,
        TeamRole.MANAGER in collection_roles,
    )
    _sync_group(
        user,
        TeamGroups.COLLECTION_MEMBER,
        TeamRole.MEMBER in collection_roles,
    )
    _sync_group(
        user,
        TeamGroups.JOURNAL_ADMIN,
        TeamRole.MANAGER in journal_roles,
    )
    _sync_group(
        user,
        TeamGroups.JOURNAL_MEMBER,
        TeamRole.MEMBER in journal_roles,
    )
    _sync_group(
        user,
        TeamGroups.COMPANY_ADMIN,
        TeamRole.MANAGER in company_roles,
    )
    _sync_group(
        user,
        TeamGroups.COMPANY_MEMBER,
        TeamRole.MEMBER in company_roles,
    )


def _pre_save_handler(sender, instance, **_kwargs):
    if not instance.pk:
        return

    try:
        old = sender.objects.get(pk=instance.pk)
    except sender.DoesNotExist:
        return

    if old.user_id and old.user_id != getattr(instance.user, "pk", None):
        instance._old_user = old.user


def _post_save_handler(instance, **_kwargs):
    sync_user_groups(instance.user)

    old_user = getattr(instance, "_old_user", None)

    if old_user:
        sync_user_groups(old_user)
        del instance._old_user


def _post_delete_handler(instance, **_kwargs):
    sync_user_groups(instance.user)


def _capture_collection_team_users(instance, **_kwargs):
    instance._team_user_ids = list(
        CollectionTeamMember.objects.filter(
            collection=instance,
            user__isnull=False,
        ).values_list("user", flat=True)
    )


def _sync_collection_team_users(instance, **_kwargs):
    User = get_user_model()

    for user in User.objects.filter(pk__in=getattr(instance, "_team_user_ids", ())):
        sync_user_groups(user)


def register_signals():
    for model in _TEAM_MEMBER_RELATIONS:
        model_label = model._meta.label_lower
        pre_save.connect(
            _pre_save_handler,
            sender=model,
            weak=False,
            dispatch_uid=f"team.capture_old_user.{model_label}",
        )
        post_save.connect(
            _post_save_handler,
            sender=model,
            weak=False,
            dispatch_uid=f"team.sync_groups_after_save.{model_label}",
        )
        post_delete.connect(
            _post_delete_handler,
            sender=model,
            weak=False,
            dispatch_uid=f"team.sync_groups_after_delete.{model_label}",
        )

    pre_delete.connect(
        _capture_collection_team_users,
        sender=Collection,
        weak=False,
        dispatch_uid="team.capture_collection_team_users",
    )
    post_delete.connect(
        _sync_collection_team_users,
        sender=Collection,
        weak=False,
        dispatch_uid="team.sync_groups_after_collection_delete",
    )
