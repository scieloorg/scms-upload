from django.http import HttpResponseRedirect
from django.utils.translation import gettext as _
from wagtail.contrib.modeladmin.options import ModelAdmin, modeladmin_register
from wagtail.contrib.modeladmin.views import CreateView

from .models import Journal


class JournalCreateView(CreateView):

    def form_valid(self, form):
        self.object = form.save_all(self.request.user)
        return HttpResponseRedirect(self.get_success_url())


class JournalAdmin(ModelAdmin):
    model = Journal
    inspect_view_enabled = True
    menu_label = _('Journals')
    create_view_class = JournalCreateView
    menu_icon = 'folder'
    menu_order = 200
    add_to_settings_menu = False
    exclude_from_explorer = False

    list_display = (
        'official_title',
        'foundation_year',
        'ISSN_print',
        'ISSN_electronic',
        'ISSN_scielo',
        'ISSNL',
    )
    list_filter = (
        'foundation_year',
    )
    search_fields = (
        'foundation_year',
        'ISSN_print',
        'ISSN_electronic',
        'ISSN_scielo',
        'ISSNL',
        'creator',
        'updated_by',
    )


modeladmin_register(JournalAdmin)
