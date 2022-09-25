from django.http import HttpResponseRedirect
from django.urls import include, path
from django.utils.translation import gettext as _

from config.menu import get_menu_order
from wagtail.core import hooks
from wagtail.contrib.modeladmin.views import CreateView
from wagtail.contrib.modeladmin.options import (
    ModelAdmin,
    ModelAdminGroup,
    modeladmin_register,
)

from . import models


class MigrationFailureAdmin(ModelAdmin):
    model = models.MigrationFailure
    inspect_view_enabled = True
    menu_label = _('Migration Failures')
    menu_icon = 'folder'
    menu_order = 200
    add_to_settings_menu = False
    exclude_from_explorer = False

    list_display = (
        'action_name',
        'object_name',
        'pid',
        'exception_type',
    )
    list_filter = (
        'action_name',
        'object_name',
        'exception_type',
    )
    search_fields = (
        'action_name',
        'object_name',
        'pid',
        'exception_type',
    )
    inspect_view_fields = (
        'action_name',
        'object_name',
        'pid',
        'exception_type',
        'exception_msg',
        'traceback',
    )


class CoreCreateView(CreateView):

    def form_valid(self, form):
        self.object = form.save_all(self.request.user)
        return HttpResponseRedirect(self.get_success_url())


class MigrationConfigurationModelAdmin(ModelAdmin):
    model = models.MigrationConfiguration
    menu_label = _('Migration Configuration')
    menu_icon = 'doc-full'
    menu_order = 100
    add_to_settings_menu = False
    exclude_from_explorer = False
    inspect_view_enabled = False

    create_view_class = CoreCreateView

    list_display = (
        'classic_website_config',
        'created',
        'updated',
        'updated_by',
    )
    list_filter = (
        'classic_website_config__collection__acron',
    )
    search_fields = (
        'classic_website_config__collection__acron',
    )


class MigrationModelAdmin(ModelAdminGroup):
    menu_icon = 'folder'
    menu_label = 'Migration'
    items = (
        MigrationConfigurationModelAdmin,
        MigrationFailureAdmin,
    )
    menu_order = get_menu_order('migration')


modeladmin_register(MigrationModelAdmin)


@hooks.register('register_admin_urls')
def register_disclosure_url():
    return [
        path('migration/',
             include('migration.urls', namespace='migration')),
    ]
