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

from .models import (
    Collection,
    NewWebSiteConfiguration,
)


class CollectionCreateView(CreateView):

    def form_valid(self, form):
        self.object = form.save_all(self.request.user)
        return HttpResponseRedirect(self.get_success_url())


class CollectionModelAdmin(ModelAdmin):
    model = Collection
    menu_label = _('Collections')
    menu_icon = 'doc-full'
    menu_order = 100
    add_to_settings_menu = False
    exclude_from_explorer = False
    inspect_view_enabled = True

    create_view_class = CollectionCreateView

    list_display = (
        'acron',
        'created',
        'updated',
        'updated_by',
    )
    list_filter = (
        'acron',
    )
    search_fields = (
        'name',
        'acron',
    )
    inspect_view_fields = (
        'name',
        'acron',
    )


class NewWebSiteConfigurationCreateView(CreateView):

    def form_valid(self, form):
        self.object = form.save_all(self.request.user)
        return HttpResponseRedirect(self.get_success_url())


class NewWebSiteConfigurationModelAdmin(ModelAdmin):
    model = NewWebSiteConfiguration
    menu_label = _('New WebSites Configurations')
    menu_icon = 'doc-full'
    menu_order = 200
    exclude_from_explorer = False
    inspect_view_enabled = False

    create_view_class = NewWebSiteConfigurationCreateView

    list_display = (
        'url',
        'created',
        'updated',
        'updated_by',
    )
    list_filter = (
        'url',
    )
    search_fields = (
        'url',
    )


class CollectionModelAdminGroup(ModelAdminGroup):
    menu_label = _('Collections')
    menu_icon = 'folder-open-inverse'
    menu_order = get_menu_order('collection')
    items = (
        CollectionModelAdmin,
        NewWebSiteConfigurationModelAdmin,
    )


modeladmin_register(CollectionModelAdminGroup)


@hooks.register('register_admin_urls')
def register_disclosure_url():
    return [
        path('collection/',
        include('collection.urls', namespace='collection')),
    ]
