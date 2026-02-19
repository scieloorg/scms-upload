from django.urls import include, path
from django.utils.translation import gettext_lazy as _
from wagtail import hooks
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSet, SnippetViewSetGroup

from config.menu import get_menu_order
from files_storage.models import MinioConfiguration
from migration.models import ClassicWebsiteConfiguration

from .models import Collection, WebSiteConfiguration


class CollectionViewSet(SnippetViewSet):
    model = Collection
    menu_label = _("Collections")
    menu_icon = "doc-full"
    menu_order = 100
    add_to_settings_menu = False

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


class WebSiteConfigurationViewSet(SnippetViewSet):
    model = WebSiteConfiguration
    menu_label = _("New WebSites Configurations")
    menu_icon = "doc-full"
    menu_order = 200

    list_display = (
        "collection",
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
    search_fields = ("url", "collection__acron", "collection__name")


class MinioConfigurationViewSet(SnippetViewSet):
    model = MinioConfiguration
    menu_label = _("Files Storage Configuration")
    menu_icon = "doc-full"
    menu_order = 200

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


class ClassicWebsiteConfigurationViewSet(SnippetViewSet):
    model = ClassicWebsiteConfiguration
    menu_label = _("Classic Website Configuration")
    menu_icon = "doc-full"
    menu_order = 200

    list_display = ("collection",)
    search_fields = (
        "collection__acron",
        "collection__name",
    )


class CollectionViewSetGroup(SnippetViewSetGroup):
    menu_label = _("Collections")
    menu_icon = "folder-open-inverse"
    menu_order = get_menu_order("collection")
    items = [
        CollectionViewSet,
        WebSiteConfigurationViewSet,
        MinioConfigurationViewSet,
        ClassicWebsiteConfigurationViewSet,
    ]


register_snippet(CollectionViewSetGroup)


@hooks.register("register_admin_urls")
def register_disclosure_url():
    return [
        path("collection/", include("collection.urls", namespace="collection")),
    ]
