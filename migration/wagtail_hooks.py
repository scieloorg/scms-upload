from django.http import HttpResponseRedirect
from django.urls import include, path
from django.utils.translation import gettext as _

from wagtail.core import hooks
from wagtail.contrib.modeladmin.options import ModelAdmin, ModelAdminGroup, modeladmin_register
from wagtail.contrib.modeladmin.views import InspectView

from .button_helper import MigrationFailureButtonHelper
from .models import MigrationFailure
from .permission_helper import MigrationFailurePermissionHelper


class MigrationFailureAdminInspectView(InspectView):
    def get_context_data(self):
        try:
            data = self.instance.data.copy()
        except AttributeError:
            data = {}

        return super().get_context_data(**data)


class MigrationFailureAdmin(ModelAdmin):
    model = MigrationFailure
    button_helper_class = MigrationFailureButtonHelper
    permission_helper_class = MigrationFailurePermissionHelper
    # create_view_class = MigrationFailureCreateView
    inspect_view_enabled = True
    inspect_view_class = MigrationFailureAdminInspectView
    menu_label = _('MigrationFailures')
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
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)

        if self.permission_helper.user_can_access_all_migration_failures(request.user, None):
            return qs
        return qs.filter(creator=request.user)


class MigrationModelAdmin(ModelAdminGroup):
    menu_icon = 'folder'
    menu_label = 'Migration'
    items = (MigrationFailureAdmin, )


modeladmin_register(MigrationModelAdmin)


@hooks.register('register_admin_urls')
def register_disclosure_url():
    return [
        path('migration/',
             include('migration.urls', namespace='migration')),
    ]
