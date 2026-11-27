from django import forms
from django.utils.translation import gettext_lazy as _
from django_filters import MultipleChoiceFilter
from wagtail.admin.filters import WagtailFilterSet
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSetGroup

from config.menu import get_menu_order
from core.users.permission_policies import TeamScopedSnippetViewSetMixin
from core.views import CommonControlFieldViewSet
from files_storage.wagtail_hooks import MinioConfigurationViewSet
from migration.wagtail_hooks import ClassicWebsiteConfigurationViewSet

from . import choices
from .models import Collection, WebSiteConfiguration


class CollectionFilterSet(WagtailFilterSet):
    # django-filter não gera filtro automaticamente para ArrayField
    # (ChoiceArrayField), por isso network_classification é declarado aqui
    network_classification = MultipleChoiceFilter(
        choices=choices.NETWORK_CLASSIFICATION,
        method="filter_network_classification",
        label=_("Network classification"),
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = Collection
        fields = ["acron", "platform_status"]

    def filter_network_classification(self, queryset, name, value):
        if not value:
            return queryset
        # coleções que tenham ao menos uma das classificações selecionadas
        return queryset.filter(**{f"{name}__overlap": list(value)})


class CollectionViewSet(TeamScopedSnippetViewSetMixin, CommonControlFieldViewSet):
    model = Collection
    collection_field = "id"
    menu_label = _("Collections")
    menu_icon = "doc-full"
    menu_order = 100
    add_to_settings_menu = False

    list_display = (
        "acron",
        "name",
        "platform_status",
        "network_classification",
        "created",
        "updated",
        "updated_by",
    )
    filterset_class = CollectionFilterSet
    search_fields = (
        "name",
        "acron",
    )


class WebSiteConfigurationViewSet(TeamScopedSnippetViewSetMixin, CommonControlFieldViewSet):
    model = WebSiteConfiguration
    collection_field = "collection"
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
