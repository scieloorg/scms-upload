from django.utils.translation import gettext_lazy as _
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSet, SnippetViewSetGroup

from config.menu import get_menu_order

from .models import (
    CollectionTeamMember,
    Company,
    CompanyTeamMember,
    JournalCompanyContract,
    JournalTeamMember,
)


class CollectionTeamMemberViewSet(SnippetViewSet):
    model = CollectionTeamMember
    menu_label = _("Collection Team Members")
    menu_icon = "group"
    add_to_settings_menu = False
    exclude_from_explorer = False

    list_display = (
        "user",
        "is_active_member",
        "collection",
        "updated",
    )
    list_filter = ("is_active_member", "collection")
    search_fields = (
        "collection__name",
        "collection__acron",
        "user__name",
        "user__username",
        "user__email",
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return CollectionTeamMember.members(request.user)


class CompanyViewSet(SnippetViewSet):
    model = Company
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


class JournalTeamMemberViewSet(SnippetViewSet):
    model = JournalTeamMember
    menu_label = _("Journal Team Members")
    menu_icon = "user"
    add_to_settings_menu = False
    exclude_from_explorer = False

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


class CompanyTeamMemberViewSet(SnippetViewSet):
    model = CompanyTeamMember
    menu_label = _("Company Team Members")
    menu_icon = "user"
    add_to_settings_menu = False
    exclude_from_explorer = False

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


class JournalCompanyContractViewSet(SnippetViewSet):
    model = JournalCompanyContract
    menu_label = _("Journal-Company Contracts")
    menu_icon = "doc-full"
    add_to_settings_menu = False
    exclude_from_explorer = False

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
    """
    Group of ViewSets for Team Management
    """
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

