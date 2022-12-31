from django.http import HttpResponseRedirect
from django.utils.translation import gettext as _
from wagtail.contrib.modeladmin.options import (
    ModelAdmin,
    ModelAdminGroup,
    modeladmin_register,
)
from wagtail.contrib.modeladmin.views import CreateView

from .models import Configuration
from config.menu import get_menu_order


class ConfigurationCreateView(CreateView):

    def form_valid(self, form):
        self.object = form.save_all(self.request.user)
        return HttpResponseRedirect(self.get_success_url())


class ConfigurationAdmin(ModelAdmin):
    model = Configuration
    menu_label = _('Files Storage Configuration')
    create_view_class = ConfigurationCreateView
    menu_icon = 'folder'
    menu_order = get_menu_order('files_storage')
    add_to_settings_menu = False
    exclude_from_explorer = False
    inspect_view_enabled = True

    list_per_page = 10
    list_display = (
        'name',
        'host',
        'bucket_root',
    )
    search_fields = (
        'name',
        'host',
        'bucket_root',
        'bucket_app_subdir',
    )


class ModelsAdminGroup(ModelAdminGroup):
    menu_label = _('Files Storage')
    menu_icon = 'folder'
    menu_order = 1000
    items = (
        ConfigurationAdmin,
    )


modeladmin_register(ModelsAdminGroup)
