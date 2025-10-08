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
        UpdatedAtColumn(),
        "created",
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
    
    # Panels para o formulário de edição
    panels = [
        MultiFieldPanel([
            FieldPanel("title"),
            FieldPanel("title_iso"),
        ], heading=_("Title Information")),
        MultiFieldPanel([
            FieldPanel("issn_print"),
            FieldPanel("issn_electronic"),
            FieldPanel("issnl"),
        ], heading=_("ISSN Information")),
        FieldPanel("foundation_year"),
    ]
    
    def get_form_class(self, request, action):
        """Override para customizar o formulário se necessário"""
        form_class = super().get_form_class(request, action)
        
        # Se você tinha um método save_all no formulário anterior,
        # você pode customizar o form aqui
        if action in ['create', 'edit']:
            class CustomForm(form_class):
                def save(self, commit=True):
                    instance = super().save(commit=False)
                    # Adicione aqui a lógica do save_all se necessário
                    # Por exemplo, associar o usuário
                    if not instance.pk:  # Se é uma criação
                        instance.created_by = self.request.user
                    instance.updated_by = self.request.user
                    if commit:
                        instance.save()
                        self.save_m2m()
                    return instance
            
            # Passa o request para o form
            CustomForm.request = request
            return CustomForm
        
        return form_class


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
    
    # Panels para o formulário
    panels = [
        FieldPanel("official_journal"),
        FieldPanel("title"),
        FieldPanel("journal_acron"),
        FieldPanel("core_synchronized"),
    ]
    

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
