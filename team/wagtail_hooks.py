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
    TeamRole,
)


class CollectionTeamMemberViewSet(SnippetViewSet):
    model = CollectionTeamMember
    menu_label = _("Collection Team Members")
    menu_icon = "group"
    add_to_settings_menu = False
    exclude_from_explorer = False

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

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        user = request.user
        if user.is_superuser:
            return qs
        # Managers see members of their own collections
        managed_collection_ids = CollectionTeamMember.objects.filter(
            user=user, role=TeamRole.MANAGER, is_active_member=True
        ).values_list("collection", flat=True)
        if managed_collection_ids:
            return qs.filter(collection__in=managed_collection_ids)
        # Regular members see only their own record
        return qs.filter(user=user)


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

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        user = request.user
        if user.is_superuser:
            return qs
        # COLLECTION_TEAM_ADMIN (collection managers) can manage all companies
        is_collection_manager = CollectionTeamMember.objects.filter(
            user=user, role=TeamRole.MANAGER, is_active_member=True
        ).exists()
        if is_collection_manager:
            return qs
        # Company members see only their own companies
        company_ids = CompanyTeamMember.objects.filter(
            user=user, is_active_member=True
        ).values_list("company", flat=True)
        return qs.filter(id__in=company_ids)


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

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        user = request.user
        if user.is_superuser:
            return qs
        # COLLECTION_TEAM_ADMIN sees all journal team members
        is_collection_manager = CollectionTeamMember.objects.filter(
            user=user, role=TeamRole.MANAGER, is_active_member=True
        ).exists()
        if is_collection_manager:
            return qs
        # JOURNAL_TEAM_ADMIN sees members of their managed journals
        managed_journal_ids = JournalTeamMember.objects.filter(
            user=user, role=TeamRole.MANAGER, is_active_member=True
        ).values_list("journal", flat=True)
        if managed_journal_ids:
            return qs.filter(journal__in=managed_journal_ids)
        # Regular members see only their own record
        return qs.filter(user=user)


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

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        user = request.user
        if user.is_superuser:
            return qs
        # COLLECTION_TEAM_ADMIN sees all company team members
        is_collection_manager = CollectionTeamMember.objects.filter(
            user=user, role=TeamRole.MANAGER, is_active_member=True
        ).exists()
        if is_collection_manager:
            return qs
        # COMPANY_TEAM_ADMIN sees members of their managed companies
        managed_company_ids = CompanyTeamMember.objects.filter(
            user=user, role=TeamRole.MANAGER, is_active_member=True
        ).values_list("company", flat=True)
        if managed_company_ids:
            return qs.filter(company__in=managed_company_ids)
        # Regular members see only their own record
        return qs.filter(user=user)


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

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        user = request.user
        if user.is_superuser:
            return qs
        # COLLECTION_TEAM_ADMIN sees all contracts
        is_collection_manager = CollectionTeamMember.objects.filter(
            user=user, role=TeamRole.MANAGER, is_active_member=True
        ).exists()
        if is_collection_manager:
            return qs
        # JOURNAL_TEAM_ADMIN sees contracts for their managed journals
        managed_journal_ids = JournalTeamMember.objects.filter(
            user=user, role=TeamRole.MANAGER, is_active_member=True
        ).values_list("journal", flat=True)
        return qs.filter(journal__in=managed_journal_ids)


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

