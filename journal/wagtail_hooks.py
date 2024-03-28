from django.http import HttpResponseRedirect
from django.utils.translation import gettext as _
from wagtail.contrib.modeladmin.options import (
    ModelAdmin,
    ModelAdminGroup,
    modeladmin_register,
)
from wagtail.contrib.modeladmin.views import CreateView

from config.menu import get_menu_order
from config.settings.base import JOURNAL_TEAM, ADMIN_SCIELO
from .models import Journal, OfficialJournal


class JournalBaseCreateView(CreateView):
    def form_valid(self, form):
        self.object = form.save_all(self.request.user)
        return HttpResponseRedirect(self.get_success_url())


class OfficialJournalAdmin(ModelAdmin):
    model = OfficialJournal
    menu_label = _("Official Journals")
    create_view_class = JournalBaseCreateView
    menu_icon = "folder"
    menu_order = get_menu_order("journal")
    add_to_settings_menu = False
    exclude_from_explorer = False
    inspect_view_enabled = True

    list_per_page = 10
    list_display = (
        "title",
        "issn_print",
        "issn_electronic",
        "issnl",
        "updated",
        "created",
    )
    list_filter = ("foundation_year",)
    search_fields = (
        "title",
        "title_iso",
        "issn_print",
        "issn_electronic",
        "issnl",
    )

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        
        user_groups = request.user.groups.values_list('name', flat=True)

        is_journal_team = JOURNAL_TEAM in user_groups
        is_admin_scielo= ADMIN_SCIELO in user_groups
        is_superuser = request.user.is_superuser

        if is_journal_team:
            journal_ids = Journal.objects.filter(id__in=request.user.journal.all().values_list("id", flat=True)).values_list('official_journal_id', flat=True)
            return queryset.filter(id__in=journal_ids)
        elif is_superuser or is_admin_scielo:
            return queryset
        return queryset.none()


class JournalCreateView(CreateView):
    def form_valid(self, form):
        self.object = form.save_all(self.request.user)
        return HttpResponseRedirect(self.get_success_url())


class JournalAdmin(ModelAdmin):
    model = Journal
    menu_label = _("Journal")
    create_view_class = JournalCreateView
    menu_icon = "folder"
    menu_order = 200
    create_view_class = JournalBaseCreateView
    add_to_settings_menu = False
    exclude_from_explorer = False

    list_display = ("title", "short_title")
    search_fields = ("official_journal__issn_electronic", "official_journal__issn_print", "short_title")

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        
        user_groups = request.user.groups.values_list('name', flat=True)

        is_journal_team = JOURNAL_TEAM in user_groups
        is_admin_scielo= ADMIN_SCIELO in user_groups
        is_superuser = request.user.is_superuser

        if is_journal_team:
            return queryset.filter(id__in=request.user.journal.all().values_list("id", flat=True))
        elif is_superuser or is_admin_scielo:
            return queryset
        return queryset.none()


class JournalModelAdminGroup(ModelAdminGroup):
    menu_icon = "folder"
    menu_label = _("Journals")
    menu_order = get_menu_order("journal")
    items = (
        OfficialJournalAdmin,
        JournalAdmin,
        # JournalProcAdmin,
    )


modeladmin_register(JournalModelAdminGroup)
