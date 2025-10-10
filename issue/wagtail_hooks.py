from django.utils.translation import gettext_lazy as _
from wagtail.admin.panels import FieldPanel, InlinePanel, MultiFieldPanel
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSet, SnippetViewSetGroup
from wagtail import hooks

from config.menu import get_menu_order
from issue.views import IssueCreateView, TOCEditView
from .models import TOC, Issue


class IssueSnippetViewSet(SnippetViewSet):
    model = Issue
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
    
    # Paginação - máximo 50 por página
    list_per_page = 50
    
    # Ordenação padrão
    ordering = ["-publication_year", "-updated"]
    
    # Habilitar inspeção
    inspect_view_enabled = True
    
    # Configurações de exportação
    list_export = ["csv", "xlsx"]
    export_filename = "issues"


class TOCSnippetViewSet(SnippetViewSet):
    model = TOC
    icon = "folder"
    menu_label = _("Table of contents sections")
    menu_order = get_menu_order("issue") + 1
    add_to_settings_menu = False
    add_to_admin_menu = False
    
    # Configuração de listagem
    list_display = [
        "issue",
        "creator",
        "created",
        "updated_by",
        "updated",
    ]
    
    list_filter = ["ordered", "created", "updated"]
    
    search_fields = [
        "issue__journal__title",
        "issue__journal__official_journal__title",
        "issue__volume",
        "issue__number",
        "issue__supplement",
        "issue__publication_year",
    ]
    
    # Paginação - máximo 50 por página
    list_per_page = 50
    
    # Ordenação padrão
    ordering = ["-updated"]
    
    # Habilitar inspeção
    inspect_view_enabled = True
    
    # Configurações de exportação
    list_export = ["csv", "xlsx"]
    export_filename = "table_of_contents"


# Grupo de Snippets para Issues
class IssueSnippetViewSetGroup(SnippetViewSetGroup):
    menu_icon = "folder"
    menu_label = _("Issues")
    menu_order = get_menu_order("issue")
    
    # Itens do grupo
    items = (IssueSnippetViewSet, TOCSnippetViewSet)


# Registrar o grupo
register_snippet(IssueSnippetViewSetGroup)
