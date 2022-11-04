from django.http import HttpResponseRedirect
from django.utils.translation import gettext as _
from wagtail.contrib.modeladmin.options import ModelAdmin, modeladmin_register
from wagtail.contrib.modeladmin.views import CreateView

from .models import OfficialJournal, NonOfficialJournalTitle
from config.menu import get_menu_order


class OfficialJournalCreateView(CreateView):

    def form_valid(self, form):
        self.object = form.save_all(self.request.user)
        return HttpResponseRedirect(self.get_success_url())


class OfficialJournalAdmin(ModelAdmin):
    model = OfficialJournal
    menu_label = _('Journals')
    create_view_class = OfficialJournalCreateView
    menu_icon = 'folder'
    menu_order = get_menu_order('journal')
    add_to_settings_menu = False
    exclude_from_explorer = False
    inspect_view_enabled = True

    list_per_page = 10
    list_display = (
        'title',
        'short_title',
        'foundation_date',
        'ISSN_print',
        'ISSN_electronic',
        'ISSNL',
    )
    # list_filter = (
    #     'foundation_date',
    # )
    search_fields = (
        'title',
        'title_iso',
        'short_title',
        'nlm_title',
        'ISSN_print',
        'ISSN_electronic',
        'ISSNL',
    )


class NonOfficialJournalTitleCreateView(CreateView):

    def form_valid(self, form):
        self.object = form.save_all(self.request.user)
        return HttpResponseRedirect(self.get_success_url())


class NonOfficialJournalTitleAdmin(ModelAdmin):
    model = NonOfficialJournalTitle
    inspect_view_enabled = True
    menu_label = _('Non Offical Journal Titles')
    create_view_class = NonOfficialJournalTitleCreateView
    menu_icon = 'folder'
    menu_order = get_menu_order('journal')
    add_to_settings_menu = False
    exclude_from_explorer = False

    list_display = (
        'official_journal_id',
        'non_official_journal_title',
    )
    list_filter = (
        'official_journal_id',
    )
    search_fields = (
        'official_journal_id',
        'non_official_journal_title',
    )


modeladmin_register(OfficialJournalAdmin)
modeladmin_register(NonOfficialJournalTitleAdmin)

