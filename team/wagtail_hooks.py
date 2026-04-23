from django.utils.translation import gettext_lazy as _
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSet, SnippetViewSetGroup

from config.menu import get_menu_order
from core.views import UserTrackingCreateView, UserTrackingEditView
from core.permission_helper import (
    ReadOnlyPolicy,
    StaffWritePolicy,
)
from .models import (
    CollectionTeamMember,
    Company,
    CompanyTeamMember,
    JournalCompanyContract,
    JournalTeamMember,
)
from .permission_helper import (
    user_is_collection_staff,
    user_can_manage_journals,
    get_user_journal_ids,
    get_user_company_ids,
)


# ===================================================================
# ViewSets — Collection (somente super gerencia)
# ===================================================================


class CollectionTeamMemberViewSet(SnippetViewSet):
    """
    view: qualquer logado (filtrado por collection do usuário)
    add/change: só super
    delete: só super
    """
    model = CollectionTeamMember
    permission_policy = ReadOnlyPolicy(CollectionTeamMember)
    menu_label = _("Collection Team Members")
    menu_icon = "group"
    add_to_settings_menu = False
    exclude_from_explorer = False
    add_view_class = UserTrackingCreateView
    edit_view_class = UserTrackingEditView

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
        if request.user.is_superuser:
            return qs
        # Usuário vê apenas membros das suas collections
        return CollectionTeamMember.members(request.user)


# ===================================================================
# ViewSets — Company (somente super gerencia, view filtrada)
# ===================================================================


class CompanyViewSet(SnippetViewSet):
    """
    view: qualquer logado (staff vê todas, company member vê a sua)
    add/change/delete: só super
    """
    model = Company
    permission_policy = ReadOnlyPolicy(Company)
    menu_label = _("Companies")
    menu_icon = "group"
    add_to_settings_menu = False
    exclude_from_explorer = False
    add_view_class = UserTrackingCreateView
    edit_view_class = UserTrackingEditView

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
        company_ids = get_user_company_ids(request.user)
        if company_ids is None:
            return qs  # super ou staff: vê todas
        if company_ids:
            return qs.filter(id__in=company_ids)
        return qs.none()


class CompanyTeamMemberViewSet(SnippetViewSet):
    """
    view: qualquer logado (filtrado pela company do usuário)
    add/change/delete: só super
    """
    model = CompanyTeamMember
    permission_policy = ReadOnlyPolicy(CompanyTeamMember)
    menu_label = _("Company Team Members")
    menu_icon = "user"
    add_to_settings_menu = False
    exclude_from_explorer = False
    add_view_class = UserTrackingCreateView
    edit_view_class = UserTrackingEditView

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
        company_ids = get_user_company_ids(request.user)
        if company_ids is None:
            return qs  # super ou staff: vê todos
        if company_ids:
            return qs.filter(company_id__in=company_ids)
        return qs.none()


# ===================================================================
# ViewSets — Journal (staff + journal admin gerenciam)
# ===================================================================


class JournalTeamMemberViewSet(SnippetViewSet):
    """
    view: qualquer logado (filtrado por journals acessíveis)
    add/change: super + collection staff + journal admin
    delete: só super
    """
    model = JournalTeamMember
    permission_policy = StaffWritePolicy(
        JournalTeamMember,
        staff_check=user_can_manage_journals,
    )
    menu_label = _("Journal Team Members")
    menu_icon = "user"
    add_to_settings_menu = False
    exclude_from_explorer = False
    add_view_class = UserTrackingCreateView
    edit_view_class = UserTrackingEditView

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
        journal_ids = get_user_journal_ids(request.user)
        if journal_ids is None:
            return qs  # superuser: vê todos
        if journal_ids:
            return qs.filter(journal_id__in=journal_ids)
        return qs.none()


class JournalCompanyContractViewSet(SnippetViewSet):
    """
    view: super + collection staff + journal admin (filtrado por journals)
    add/change: super + collection staff + journal admin
    delete: só super
    """
    model = JournalCompanyContract
    permission_policy = StaffWritePolicy(
        JournalCompanyContract,
        access_check=user_can_manage_journals,
        staff_check=user_can_manage_journals,
    )
    menu_label = _("Journal-Company Contracts")
    menu_icon = "doc-full"
    add_to_settings_menu = False
    exclude_from_explorer = False
    add_view_class = UserTrackingCreateView
    edit_view_class = UserTrackingEditView

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
        journal_ids = get_user_journal_ids(request.user)
        if journal_ids is None:
            return qs  # superuser: vê todos
        if journal_ids:
            return qs.filter(journal_id__in=journal_ids)
        return qs.none()


# ===================================================================
# Grupo de menu
# ===================================================================


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