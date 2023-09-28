from django.http import HttpResponseRedirect
from django.urls import include, path
from django.utils.translation import gettext as _
from wagtail import hooks
from wagtail.contrib.modeladmin.options import (
    ModelAdmin,
    ModelAdminGroup,
    modeladmin_register,
)
from wagtail.contrib.modeladmin.views import CreateView

from config.menu import get_menu_order
from files_storage.models import MinioConfiguration
from migration.models import ClassicWebsiteConfiguration

from .models import Collection, WebSiteConfiguration


class CoreCreateView(CreateView):
    def form_valid(self, form):
        self.object = form.save_all(self.request.user)
        return HttpResponseRedirect(self.get_success_url())


class CollectionModelAdmin(ModelAdmin):
    model = Collection
    menu_label = _("Collections")
    menu_icon = "doc-full"
    menu_order = 100
    add_to_settings_menu = False
    exclude_from_explorer = False
    inspect_view_enabled = True

    create_view_class = CoreCreateView

    list_display = (
        "acron",
        "created",
        "updated",
        "updated_by",
    )
    list_filter = ("acron",)
    search_fields = (
        "name",
        "acron",
    )
    inspect_view_fields = (
        "name",
        "acron",
    )


class WebSiteConfigurationModelAdmin(ModelAdmin):
    model = WebSiteConfiguration
    menu_label = _("New WebSites Configurations")
    menu_icon = "doc-full"
    menu_order = 200
    exclude_from_explorer = False
    inspect_view_enabled = False

    create_view_class = CoreCreateView

    list_display = (
        "url",
        "purpose",
        "enabled",
        "created",
        "updated",
        "updated_by",
    )
    list_filter = (
        "purpose",
        "enabled",
    )
    search_fields = ("url",)


class MinioConfigurationModelAdmin(ModelAdmin):
    model = MinioConfiguration
    menu_label = _("Files Storage Configuration")
    menu_icon = "doc-full"
    menu_order = 200
    exclude_from_explorer = False
    inspect_view_enabled = False

    create_view_class = CoreCreateView

    list_display = (
        "host",
        "bucket_root",
        "created",
        "updated",
        "updated_by",
    )
    list_filter = (
        "host",
        "bucket_root",
    )
    search_fields = (
        "host",
        "bucket_root",
    )


class ClassicWebsiteConfigurationModelAdmin(ModelAdmin):
    model = ClassicWebsiteConfiguration
    menu_label = _("Classic Website Configuration")
    menu_icon = "doc-full"
    menu_order = 200
    exclude_from_explorer = False
    inspect_view_enabled = False

    create_view_class = CoreCreateView

    list_display = ("collection",)
    search_fields = (
        "collection__acron",
        "collection__name",
    )


class CollectionModelAdminGroup(ModelAdminGroup):
    menu_label = _("Collections")
    menu_icon = "folder-open-inverse"
    # menu_order = get_menu_order("collection")
    menu_order = 100
    items = (
        CollectionModelAdmin,
        WebSiteConfigurationModelAdmin,
        MinioConfigurationModelAdmin,
        ClassicWebsiteConfigurationModelAdmin,
    )


modeladmin_register(CollectionModelAdminGroup)


@hooks.register("register_admin_urls")
def register_disclosure_url():
    return [
        path("collection/", include("collection.urls", namespace="collection")),
    ]
