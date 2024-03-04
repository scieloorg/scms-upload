from django.http import HttpResponseRedirect
from wagtail import hooks
from wagtail.contrib.modeladmin.options import (
    ModelAdmin,
    ModelAdminGroup,
    modeladmin_register,
)
from wagtail.contrib.modeladmin.views import CreateView

from .models import CrossrefConfiguration, CrossrefDOIDepositRecord


class CrossrefCreateView(CreateView):
    def form_valid(self, form):
        self.object = form.save_all(self.request.user)
        return HttpResponseRedirect(self.get_success_url())


class CrossrefConfigurationAdmin(ModelAdmin):
    model = CrossrefConfiguration
    create_view_class = CrossrefCreateView
    menu_label = "Crossref"
    menu_icon = "folder-open-inverse"
    menu_order = 100
    add_to_settings_menu = False
    exclude_from_explorer = False

    list_display = (
        "prefix",
        "depositor_name",
        "depositor_email_address",
        "registrant",
    )
    list_filter = ("prefix",)
    search_fields = list_display


class CrossrefDOIDepositRecordAdmin(ModelAdmin):
    model = CrossrefDOIDepositRecord
    menu_label = "Crossref Doi Record"
    menu_icon = "folder-open-inverse"
    menu_order = 100
    add_to_settings_menu = False
    exclude_from_explorer = False


class CrossrefGroupAdmin(ModelAdminGroup):
    menu_label = "Crossref"
    menu_icon = "folder-open-inverse"
    menu_order = 500
    items = (
        CrossrefConfigurationAdmin,
        CrossrefDOIDepositRecordAdmin,
    )


modeladmin_register(CrossrefGroupAdmin)
