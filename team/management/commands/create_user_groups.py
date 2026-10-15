from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand

from team.models import (
    GROUP_NAMES,
    COLLECTION_TEAM_ADMIN,
    JOURNAL_TEAM_ADMIN,
    CollectionTeamMember,
    Company,
    CompanyTeamMember,
    JournalCompanyContract,
    JournalTeamMember,
)


class Command(BaseCommand):
    help = "Create default user groups and assign permissions for team management"

    def handle(self, *args, **options):
        for name in GROUP_NAMES:
            Group.objects.get_or_create(name=name)
            self.stdout.write(f"Group '{name}' ensured.")

        self._assign_permissions()
        self.stdout.write(self.style.SUCCESS("User groups created/updated successfully."))

    def _assign_permissions(self):
        # COLLECTION_TEAM_ADMIN: can manage all team members and Company CRUD
        collection_admin_group, _ = Group.objects.get_or_create(name=COLLECTION_TEAM_ADMIN)
        collection_admin_permissions = self._get_model_permissions(
            [CollectionTeamMember, Company, JournalTeamMember, CompanyTeamMember, JournalCompanyContract]
        )
        collection_admin_group.permissions.set(collection_admin_permissions)

        # JOURNAL_TEAM_ADMIN: can manage journal team members and Company Contracts CRUD
        journal_admin_group, _ = Group.objects.get_or_create(name=JOURNAL_TEAM_ADMIN)
        journal_admin_permissions = self._get_model_permissions(
            [JournalTeamMember, JournalCompanyContract]
        )
        journal_admin_group.permissions.set(journal_admin_permissions)

        # COMPANY_TEAM_ADMIN: can manage company team members
        company_admin_group, _ = Group.objects.get_or_create(name=COMPANY_TEAM_ADMIN)
        company_admin_permissions = self._get_model_permissions([CompanyTeamMember])
        company_admin_group.permissions.set(company_admin_permissions)

    def _get_model_permissions(self, models):
        permissions = []
        for model in models:
            ct = ContentType.objects.get_for_model(model)
            permissions.extend(Permission.objects.filter(content_type=ct))
        return permissions
