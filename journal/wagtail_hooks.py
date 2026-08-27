# wagtail_hooks.py (ou views.py)
from django.utils.translation import gettext_lazy as _
from django_filters import BooleanFilter
from wagtail.admin.filters import WagtailFilterSet
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSet, SnippetViewSetGroup

from config.menu import get_menu_order
from journal.models import Journal, OfficialJournal, JournalCollection


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


class JournalFilterSet(WagtailFilterSet):
    is_complete = BooleanFilter(
        method="filter_is_complete",
        label=_("Is complete"),
    )

    class Meta:
        model = Journal
        fields = ["core_synchronized"]  # campos reais de banco continuam normais aqui

    def filter_is_complete(self, queryset, name, value):
        if value is None:
            return queryset

        if value:
            ids = [obj.pk for obj in queryset if not obj.missing_fields]
        else:
            ids = [obj.pk for obj in queryset if obj.missing_fields]

        return queryset.filter(pk__in=ids)


class JournalViewSet(SnippetViewSet):
    model = Journal
    menu_label = _("Journal")
    menu_icon = "folder"
    menu_order = 200
    add_to_settings_menu = False
    add_to_admin_menu = False

    list_display = [
        "title",
        "journal_acron",
        "missing_fields",
        "updated",
    ]
    search_fields = [
        "official_journal__issn_electronic",
        "official_journal__issn_print",
        "official_journal__title",
        "title",
        "journal_acron",
    ]
    filterset_class = JournalFilterSet


class JournalCollectionViewSet(SnippetViewSet):
    model = JournalCollection
    menu_label = _("Journal Collection")
    menu_icon = "site"
    menu_order = get_menu_order("journal_collection")
    add_to_settings_menu = False

    list_display = (
        "journal",
        "collection",
        "creator",
        "updated",
        "created",
        "updated_by",
    )
    list_filter = (
        "collection",
    )
    search_fields = (
        "journal__title",     # ajuste para o campo textual real de Journal
        "collection__name",   # ajuste para o campo textual real de Collection
        "collection__acron", # se existir, ajuda muito na busca por sigla
    )
    export_filename = "journal_collections"


class JournalCollectionViewSet(SnippetViewSet):
    model = JournalCollection
    menu_label = _("Journal Collection")
    menu_icon = "site"
    menu_order = get_menu_order("journal_collection")
    add_to_settings_menu = False

    list_display = (
        "journal",
        "collection",
        "creator",
        "updated",
        "created",
        "updated_by",
    )
    list_filter = (
        "collection",
    )
    search_fields = (
        "journal__title",     # ajuste para o campo textual real de Journal
        "collection__name",   # ajuste para o campo textual real de Collection
        "collection__acron3", # se existir, ajuda muito na busca por sigla
    )
    export_filename = "journal_collections"


# Grupo de ViewSets
class JournalViewSetGroup(SnippetViewSetGroup):
    menu_icon = "folder"
    menu_label = _("Journals")
    menu_order = get_menu_order("journal")
    
    items = [
        # OfficialJournalViewSet,  # Descomentado como no original
        JournalViewSet,
        JournalCollectionViewSet,
        # JournalProcViewSet,  # Se existir
    ]


# # Registrar o grupo no menu
register_snippet(JournalViewSetGroup)
# register_snippet(JournalCollectionViewSet)

