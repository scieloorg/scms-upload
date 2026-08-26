from wagtail.admin.forms import WagtailAdminModelForm

from team.models import (
    CollectionTeamMember,
    CompanyTeamMember,
    JournalTeamMember,
    TeamRole,
)


class ManagedRelationAdminForm(WagtailAdminModelForm):
    membership_model = None
    relation_field = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.for_user and not self.for_user.is_superuser:
            relation_ids = self.membership_model.objects.filter(
                user=self.for_user,
                role=TeamRole.MANAGER,
                is_active_member=True,
                **{f"{self.relation_field}__isnull": False},
            ).values_list(self.relation_field, flat=True)
            field = self.fields[self.relation_field]
            field.queryset = field.queryset.filter(pk__in=relation_ids)


class CollectionTeamMemberAdminForm(ManagedRelationAdminForm):
    membership_model = CollectionTeamMember
    relation_field = "collection"


class JournalTeamMemberAdminForm(ManagedRelationAdminForm):
    membership_model = JournalTeamMember
    relation_field = "journal"


class CompanyTeamMemberAdminForm(ManagedRelationAdminForm):
    membership_model = CompanyTeamMember
    relation_field = "company"


class JournalCompanyContractAdminForm(ManagedRelationAdminForm):
    membership_model = JournalTeamMember
    relation_field = "journal"
