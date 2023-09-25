from django.http import HttpResponseRedirect
from django.utils.translation import gettext as _
from wagtail.contrib.modeladmin.options import (
    ModelAdmin,
    ModelAdminGroup,
    modeladmin_register,
)
from wagtail.contrib.modeladmin.views import CreateView

from config.menu import get_menu_order

from .models import Journal, SciELOJournal, OfficialJournal


class OfficialJournalCreateView(CreateView):
    def form_valid(self, form):
        self.object = form.save_all(self.request.user)
        return HttpResponseRedirect(self.get_success_url())


class OfficialJournalAdmin(ModelAdmin):
    model = OfficialJournal
    menu_label = _("Official Journals")
    create_view_class = OfficialJournalCreateView
    menu_icon = "folder"
    menu_order = get_menu_order("journal")
    add_to_settings_menu = False
    exclude_from_explorer = False
    inspect_view_enabled = True

    list_per_page = 10
    list_display = (
        "title",
        "title_iso",
        "foundation_year",
        "issn_print",
        "issn_electronic",
        "issnl",
    )
    # list_filter = (
    #     'foundation_date',
    # )
    search_fields = (
        "title",
        "title_iso",
        "nlm_title",
        "issn_print",
        "issn_electronic",
        "issnl",
    )


class JournalAdmin(ModelAdmin):
    model = Journal
    menu_label = _("Journal")
    menu_icon = "folder"
    menu_order = 200
    add_to_settings_menu = False
    exclude_from_explorer = False

    list_display = ("official_journal", "short_title")
    search_fields = ("official_journal__title", "short_title")


class SciELOJournalAdmin(ModelAdmin):
    model = SciELOJournal
    menu_label = _("SciELO Journal")
    menu_icon = "folder"
    menu_order = 200
    add_to_settings_menu = False
    exclude_from_explorer = False

    list_display = (
        "collection",
        "acron",
        "scielo_issn",
        "title",
        "availability_status",
        "publication_stage",
    )
    list_filter = (
        "availability_status",
        "publication_stage",
    )
    search_fields = (
        "acron",
        "availability_status",
        "collection__acron",
        "scielo_issn",
        "title",
    )


class JournalModelAdminGroup(ModelAdminGroup):
    menu_icon = "folder"
    menu_label = _("Journals")
    # menu_order = get_menu_order("journal")
    menu_order = 200
    items = (
        OfficialJournalAdmin,
        JournalAdmin,
        SciELOJournalAdmin,
    )
    menu_order = get_menu_order("journal")


modeladmin_register(JournalModelAdminGroup)
