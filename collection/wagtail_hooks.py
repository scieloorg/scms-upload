from django.urls import include, path
from django.utils.translation import gettext_lazy as _
from wagtail import hooks
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSet, SnippetViewSetGroup

from config.menu import get_menu_order
from files_storage.wagtail_hooks import MinioConfigurationViewSet
from migration.wagtail_hooks import ClassicWebsiteConfigurationViewSet
from team.models import get_user_membership_ids

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

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        user = request.user
        if user.is_superuser:
            return qs
        membership = get_user_membership_ids(user)
        if membership.get("collection_list_ids"):
            return qs.filter(id__in=membership["collection_list_ids"])
        return qs.none()


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

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        user = request.user
        if user.is_superuser:
            return qs
        membership = get_user_membership_ids(user)
        if membership.get("collection_list_ids"):
            return qs.filter(collection_id__in=membership["collection_list_ids"])
        return qs.none()


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
