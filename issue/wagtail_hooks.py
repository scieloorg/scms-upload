from django.utils.translation import gettext_lazy as _
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSet, SnippetViewSetGroup

from config.menu import get_menu_order
from core.users.permission_policies import TeamScopedSnippetViewSetMixin
from issue.models import TOC, Issue
from issue.views import IssueCreateView


class IssueSnippetViewSet(TeamScopedSnippetViewSetMixin, SnippetViewSet):
    model = Issue
    journal_field = "journal"
    icon = "folder"
    menu_label = _("Issues")
    menu_order = get_menu_order("issue")
    add_to_settings_menu = False
    add_to_admin_menu = False

    # Views customizadas
    create_view_class = IssueCreateView

    # Configuração de listagem
    list_display = [
        "journal",
        "publication_year",
        "order",
        "volume",
        "number",
        "supplement",
        "updated",
    ]

    list_filter = ["publication_year", "journal"]

    search_fields = [
        "journal__journal_acron",
        "journal__official_journal__title",
        "journal__official_journal__issn_electronic",
        "journal__official_journal__issn_print",
        "publication_year",
        "volume",
        "number",
        "supplement",
    ]

    list_per_page = 50
    ordering = ["-publication_year", "-updated"]
    inspect_view_enabled = True
    list_export = ["csv", "xlsx"]
    export_filename = "issues"


class TOCSnippetViewSet(TeamScopedSnippetViewSetMixin, SnippetViewSet):
    model = TOC
    journal_field = "issue__journal"
    icon = "folder"
    menu_label = _("Table of contents sections")
    menu_order = get_menu_order("issue") + 1
    add_to_settings_menu = False
    add_to_admin_menu = False

    list_display = [
        "issue",
        "issue__publication_year",
        "issue__volume",
        "updated",
    ]

    list_filter = [
        "issue__journal__journal_acron",
        "issue__publication_year",
        "ordered",
        "created",
        "updated",
    ]

    search_fields = [
        "issue__journal__journalproc__acron",
        "issue__journal__title",
        "issue__journal__official_journal__title",
        "issue__volume",
        "issue__number",
        "issue__supplement",
        "issue__publication_year",
    ]

    list_per_page = 50
    ordering = ["-updated"]
    inspect_view_enabled = True
    list_export = ["csv", "xlsx"]
    export_filename = "table_of_contents"


class IssueSnippetViewSetGroup(SnippetViewSetGroup):
    menu_icon = "folder"
    menu_label = _("Issues")
    menu_order = get_menu_order("issue")
    items = (IssueSnippetViewSet, TOCSnippetViewSet)


register_snippet(IssueSnippetViewSetGroup)
