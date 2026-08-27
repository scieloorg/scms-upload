from django.utils.translation import gettext_lazy as _
from wagtail.admin.panels import get_form_for_model
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSetGroup

from config.menu import get_menu_order
from core.users.permission_policies import TeamScopedSnippetViewSetMixin
from core.views import CommonControlFieldViewSet
from team.forms import (
    CollectionTeamMemberAdminForm,
    CompanyTeamMemberAdminForm,
    JournalCompanyContractAdminForm,
    JournalTeamMemberAdminForm,
)
from team.policies import (
    CollectionTeamMemberPolicy,
    CompanyPolicy,
    CompanyTeamMemberPolicy,
    JournalCompanyContractPolicy,
    JournalTeamMemberPolicy,
)

from .models import (
    CollectionTeamMember,
    Company,
    CompanyTeamMember,
    JournalCompanyContract,
    JournalTeamMember,
)


class TeamAdminFormViewSetMixin:
    def get_form_class(self, for_update=False):
        if not self._edit_handler:
            return super().get_form_class(for_update=for_update)

        return get_form_for_model(
            self.model,
            form_class=self.base_form_class,
            **self._edit_handler.get_form_options(),
        )


class CollectionTeamMemberViewSet(
    TeamScopedSnippetViewSetMixin,
    TeamAdminFormViewSetMixin,
    CommonControlFieldViewSet,
):
    model = CollectionTeamMember
    scope_policy = CollectionTeamMemberPolicy
    menu_label = _("Collection Team Members")
    menu_icon = "group"
    add_to_settings_menu = False
    exclude_from_explorer = False
    base_form_class = CollectionTeamMemberAdminForm

    list_display = (
        "user",
        "collection",
        "role",
        "is_active_member",
        "updated",
    )
    list_filter = ("role", "is_active_member", "collection")
    search_fields = (
        "collection__name",
        "collection__acron",
        "user__name",
        "user__username",
        "user__email",
    )


class CompanyViewSet(TeamScopedSnippetViewSetMixin, CommonControlFieldViewSet):
    model = Company
    scope_policy = CompanyPolicy
    menu_label = _("Companies")
    menu_icon = "group"
    add_to_settings_menu = False
    exclude_from_explorer = False

    list_display = (
        "name",
        "personal_contact",
        "contact_email",
        "certified_since",
        "is_active",
        "updated",
    )
    list_filter = ("is_active", "certified_since")
    search_fields = (
        "name",
        "personal_contact",
        "contact_email",
        "url",
    )


class JournalTeamMemberViewSet(
    TeamScopedSnippetViewSetMixin,
    TeamAdminFormViewSetMixin,
    CommonControlFieldViewSet,
):
    model = JournalTeamMember
    scope_policy = JournalTeamMemberPolicy
    menu_label = _("Journal Team Members")
    menu_icon = "user"
    add_to_settings_menu = False
    exclude_from_explorer = False
    base_form_class = JournalTeamMemberAdminForm

    list_display = (
        "user",
        "journal",
        "role",
        "is_active_member",
        "created",
    )
    list_filter = ("role", "is_active_member", "created")
    search_fields = (
        "user__username",
        "user__email",
        "user__name",
        "journal__title",
    )


class CompanyTeamMemberViewSet(
    TeamScopedSnippetViewSetMixin,
    TeamAdminFormViewSetMixin,
    CommonControlFieldViewSet,
):
    model = CompanyTeamMember
    scope_policy = CompanyTeamMemberPolicy
    menu_label = _("Company Team Members")
    menu_icon = "user"
    add_to_settings_menu = False
    exclude_from_explorer = False
    base_form_class = CompanyTeamMemberAdminForm

    list_display = (
        "user",
        "company",
        "role",
        "is_active_member",
        "created",
    )
    list_filter = ("role", "is_active_member", "created")
    search_fields = (
        "user__username",
        "user__email",
        "user__name",
        "company__name",
    )


class JournalCompanyContractViewSet(
    TeamScopedSnippetViewSetMixin,
    TeamAdminFormViewSetMixin,
    CommonControlFieldViewSet,
):
    model = JournalCompanyContract
    scope_policy = JournalCompanyContractPolicy
    menu_label = _("Journal-Company Contracts")
    menu_icon = "doc-full"
    add_to_settings_menu = False
    exclude_from_explorer = False
    base_form_class = JournalCompanyContractAdminForm

    list_display = (
        "journal",
        "company",
        "is_active",
        "start_date",
        "end_date",
    )
    list_filter = ("is_active", "start_date", "end_date")
    search_fields = (
        "journal__title",
        "company__name",
    )


class TeamViewSetGroup(SnippetViewSetGroup):
    items = [
        CollectionTeamMemberViewSet,
        CompanyViewSet,
        JournalTeamMemberViewSet,
        CompanyTeamMemberViewSet,
        JournalCompanyContractViewSet,
    ]
    menu_icon = "group"
    menu_label = _("Teams")
    menu_order = get_menu_order("team")


register_snippet(TeamViewSetGroup)
