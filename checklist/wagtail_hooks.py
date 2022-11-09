from django.http import HttpResponseRedirect
from django.urls import include, path
from django.utils.translation import gettext as _

from wagtail.core import hooks
from wagtail.contrib.modeladmin.options import ModelAdmin, ModelAdminGroup, modeladmin_register
from wagtail.contrib.modeladmin.views import CreateView

from .models import ManualChecking, ManualCheckingItem


class ManualCheckingCreateView(CreateView):
    def form_valid(self, form):
        self.object = form.save_all(self.request.user)
        return HttpResponseRedirect(self.get_success_url())


class ManualCheckingAdmin(ModelAdmin):
    model = ManualChecking
    create_view_class = ManualCheckingCreateView
    inspect_view_enabled=True
    menu_label = _('Manual Checking')
    menu_icon = 'folder'
    menu_order = 200
    add_to_settings_menu = False
    exclude_from_explorer = False

    list_display = (
        'title',
        'validation_group',
        'version',
        'status',
    )
    list_filter = (
        'status',
    )
    search_fields = (
        'title',
        'validation_group',
        'item__name',
    )
    inspect_fields = (
        'title',
        'validation_group',
        'comment',
        'version',
        'status',
        'item',
    )


class ManualCheckingItemAdmin(ModelAdmin):
    model = ManualCheckingItem
    inspect_view_enabled=True
    menu_label = _('Manual Checking Items')
    menu_icon = 'folder'
    menu_order = 200
    add_to_settings_menu = False
    exclude_from_explorer = False

    list_display = (
        'name',
        'description',
        'response',
    )
    list_filter = ()
    search_fields = (
        'name'
    )
    inspect_fields = (
        'name',
        'description',
        'response',
    )


class ManualCheckingModelAdminGroup(ModelAdminGroup):
    menu_icon = 'folder'
    menu_label = 'Manual Checkings'
    items = (ManualCheckingAdmin, ManualCheckingItemAdmin)
    menu_order = 200


modeladmin_register(ManualCheckingModelAdminGroup)


@hooks.register('register_admin_urls')
def register_disclosure_url():
    return [
        path('checklist/',
        include('checklist.urls', namespace='checklist')),
    ]
