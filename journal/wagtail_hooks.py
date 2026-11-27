from django.utils.translation import gettext_lazy as _
from django_filters import BooleanFilter
from wagtail.admin.filters import WagtailFilterSet
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSet, SnippetViewSetGroup

from config.menu import get_menu_order
from core.users.permission_policies import TeamScopedSnippetViewSetMixin
from journal.models import Journal, JournalCollection, OfficialJournal


class OfficialJournalViewSet(TeamScopedSnippetViewSetMixin, SnippetViewSet):
    model = OfficialJournal
    allow_unscoped_queryset = True
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


class JournalViewSet(TeamScopedSnippetViewSetMixin, SnippetViewSet):
    model = Journal
    journal_field = "id"
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
    ordering = ["-updated"]
    search_fields = [
        "official_journal__issn_electronic",
        "official_journal__issn_print",
        "official_journal__title",
        "title",
        "journal_acron",
    ]
    filterset_class = JournalFilterSet


class JournalCollectionViewSet(TeamScopedSnippetViewSetMixin, SnippetViewSet):
    model = JournalCollection
    collection_field = "collection"
    journal_field = "journal"
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
        "journal__title",
        "collection__name",
        "collection__acron",
    )
    export_filename = "journal_collections"


class JournalViewSetGroup(SnippetViewSetGroup):
    menu_icon = "folder"
    menu_label = _("Journals")
    menu_order = get_menu_order("journal")

    items = [
        JournalViewSet,
        JournalCollectionViewSet,
    ]


register_snippet(JournalViewSetGroup)
# register_snippet(JournalCollectionViewSet)

