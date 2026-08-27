from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from team.authorization_matrix import FULL_ACCESS, GROUP_ACCESS, MANAGE_ACTIONS
from team.constants import TeamGroups
from team.models import CollectionTeamMember, CompanyTeamMember, JournalTeamMember
from team.signals import sync_user_groups, system_group_update


class Command(BaseCommand):
    help = "Create canonical groups and reconcile their permissions and memberships"

    def add_arguments(self, parser):
        parser.add_argument(
            "--sync-users",
            action="store_true",
            help="Reconcile canonical groups for users with memberships or managed groups.",
        )

    @transaction.atomic
    def handle(self, **options):
        self.stdout.write("Ensuring user groups...")

        with system_group_update():
            self._merge_legacy_group()
            groups = self._ensure_groups()
            self._assign_permissions(groups)

            if options.get("sync_users", False):
                self._sync_all_users(groups)

        self.stdout.write(self.style.SUCCESS("Canonical groups reconciled."))

    def _merge_legacy_group(self):
        legacy_name = "COMPANY_TEAM_MEMBER"
        try:
            legacy = Group.objects.get(name=legacy_name)
        except Group.DoesNotExist:
            return

        canonical, _ = Group.objects.get_or_create(name=TeamGroups.COMPANY_MEMBER)
        canonical.user_set.add(*legacy.user_set.all())
        legacy.delete()
        self.stdout.write(
            self.style.WARNING(
                f"Merged legacy group '{legacy_name}' into '{TeamGroups.COMPANY_MEMBER}'."
            )
        )

    def _ensure_groups(self):
        groups = {}
        for name in TeamGroups.ALL:
            group, created = Group.objects.get_or_create(name=name)
            groups[name] = group
            if created:
                self.stdout.write(self.style.SUCCESS(f"Created group: {name}"))
        return groups

    def _assign_permissions(self, groups):
        for group_name, group in groups.items():
            group_access = GROUP_ACCESS[group_name]
            model_permissions = group_access["models"]
            permissions = set()

            for app_label, access in group_access["apps"].items():
                if app_label in model_permissions:
                    continue

                actions = MANAGE_ACTIONS if access == FULL_ACCESS else ("view",)
                permissions.update(self._standard_app_permissions(app_label, actions))

            for app_label, matrix in model_permissions.items():
                permissions.update(
                    self._model_permissions(app_label, matrix)
                )

            for app_label, codenames in group_access["custom"].items():
                permissions.update(
                    self._required_permission(app_label, codename)
                    for codename in codenames
                )

            group.permissions.set(permissions)
            self.stdout.write(
                f"Assigned {len(permissions)} permission(s) to '{group_name}'."
            )

    def _standard_app_permissions(self, app_label, actions):
        prefixes = tuple(f"{action}_" for action in actions)
        return {
            permission
            for permission in Permission.objects.filter(
                content_type__app_label=app_label
            ).select_related("content_type")
            if permission.codename.startswith(prefixes)
        }

    def _model_permissions(self, app_label, model_permissions):
        permissions = set()
        wildcard_actions = model_permissions.get("*", ())
        if wildcard_actions:
            permissions.update(
                self._standard_app_permissions(app_label, wildcard_actions)
            )

        for model_name, actions in model_permissions.items():
            if model_name == "*":
                continue
            for action in actions:
                codename = f"{action}_{model_name}"
                permissions.add(self._required_permission(app_label, codename))
        return permissions

    def _required_permission(self, app_label, codename):
        try:
            return Permission.objects.get(
                content_type__app_label=app_label,
                codename=codename,
            )
        except Permission.DoesNotExist as exc:
            raise CommandError(
                f"Configured permission does not exist: {app_label}.{codename}"
            ) from exc
        except Permission.MultipleObjectsReturned as exc:
            raise CommandError(
                f"Configured permission is ambiguous: {app_label}.{codename}"
            ) from exc

    def _sync_all_users(self, groups):
        user_ids = set()
        for model in (
            CollectionTeamMember,
            JournalTeamMember,
            CompanyTeamMember,
        ):
            user_ids.update(
                model.objects.filter(user__isnull=False).values_list("user", flat=True)
            )

        for group in groups.values():
            user_ids.update(group.user_set.values_list("pk", flat=True))

        User = CollectionTeamMember._meta.get_field("user").related_model
        for user in User.objects.filter(pk__in=user_ids):
            sync_user_groups(user)
            self.stdout.write(f"Synchronised groups for user: {user}")
