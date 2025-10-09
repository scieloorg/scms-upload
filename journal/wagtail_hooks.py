# wagtail_hooks.py (ou views.py)
from django.http import HttpResponseRedirect
from django.utils.translation import gettext_lazy as _
from wagtail.admin.panels import FieldPanel, MultiFieldPanel
from wagtail.admin.ui.tables import UpdatedAtColumn
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSet, SnippetViewSetGroup
from wagtail import hooks

from config.menu import get_menu_order
from journal.models import Journal, OfficialJournal


class OfficialJournalViewSet(SnippetViewSet):
    model = OfficialJournal
    menu_label = _("Official Journals")
    menu_icon = "folder"
    menu_order = get_menu_order("journal")
    add_to_settings_menu = False
    add_to_admin_menu = True
    
    list_display = [
        "title",
        "issn_print",
        "issn_electronic",
        "issnl",
        "updated",
    ]
    list_filter = ["foundation_year"]
    search_fields = [
        "title",
        "title_iso",
        "issn_print",
        "issn_electronic",
        "issnl",
    ]
    list_per_page = 10
    inspect_view_enabled = True


class JournalViewSet(SnippetViewSet):
    model = Journal
    menu_label = _("Journal")
    menu_icon = "folder"
    menu_order = 200
    add_to_settings_menu = False
    add_to_admin_menu = False  # Será adicionado via grupo
    
    list_display = [
        "title",
        "journal_acron",
        "core_synchronized",
        "updated",
    ]
    search_fields = [
        "official_journal__issn_electronic",
        "official_journal__issn_print",
        "official_journal__title",
        "title",
        "journal_acron",
    ]
    list_filter = ["core_synchronized"]


# Grupo de ViewSets
class JournalViewSetGroup(SnippetViewSetGroup):
    menu_icon = "folder"
    menu_label = _("Journals")
    menu_order = get_menu_order("journal")
    
    items = [
        # OfficialJournalViewSet,  # Descomentado como no original
        JournalViewSet,
        # JournalProcViewSet,  # Se existir
    ]


# Registrar o grupo no menu
register_snippet(JournalViewSetGroup)
