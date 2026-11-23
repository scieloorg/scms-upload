from django.contrib.auth.models import Group
from django.db.models.signals import post_delete, post_save

from .models import (
    COLLECTION_TEAM_ADMIN,
    COLLECTION_TEAM_MEMBER,
    COMPANY_MEMBER,
    COMPANY_TEAM_ADMIN,
    JOURNAL_TEAM_ADMIN,
    JOURNAL_TEAM_MEMBER,
    CollectionTeamMember,
    CompanyTeamMember,
    JournalTeamMember,
    TeamRole,
)


def _roles_for_user(model_class, user):
    """Return the set of active roles the user holds in a team model."""
    return set(
        model_class.objects.filter(user=user, is_active_member=True)
        .values_list("role", flat=True)
    )


def update_user_groups(user):
    """
    Synchronise a user's auth.Group memberships to reflect their current
    active team-member roles.  Called after any team member is saved or deleted.
    """
    if user is None:
        return

    collection_roles = _roles_for_user(CollectionTeamMember, user)
    journal_roles = _roles_for_user(JournalTeamMember, user)
    company_roles = _roles_for_user(CompanyTeamMember, user)

    _sync_group(user, COLLECTION_TEAM_ADMIN, TeamRole.MANAGER in collection_roles)
    _sync_group(user, COLLECTION_TEAM_MEMBER, TeamRole.MEMBER in collection_roles)
    _sync_group(user, JOURNAL_TEAM_ADMIN, TeamRole.MANAGER in journal_roles)
    _sync_group(user, JOURNAL_TEAM_MEMBER, TeamRole.MEMBER in journal_roles)
    _sync_group(user, COMPANY_TEAM_ADMIN, TeamRole.MANAGER in company_roles)
    _sync_group(user, COMPANY_MEMBER, TeamRole.MEMBER in company_roles)


def _sync_group(user, group_name, should_belong):
    """Add or remove a user from a group, creating the group if needed."""
    group, _ = Group.objects.get_or_create(name=group_name)
    if should_belong:
        user.groups.add(group)
    else:
        user.groups.remove(group)


def _make_signal_handler(description):
    def handler(sender, instance, **kwargs):
        update_user_groups(instance.user)
    handler.__name__ = description
    return handler


_TEAM_MODELS = [CollectionTeamMember, JournalTeamMember, CompanyTeamMember]

for _model in _TEAM_MODELS:
    post_save.connect(
        _make_signal_handler(f"sync_{_model.__name__.lower()}_groups_on_save"),
        sender=_model,
        weak=False,
    )
    post_delete.connect(
        _make_signal_handler(f"sync_{_model.__name__.lower()}_groups_on_delete"),
        sender=_model,
        weak=False,
    )
