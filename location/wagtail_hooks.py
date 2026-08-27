from django.utils.translation import gettext_lazy as _
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSet

from config.menu import get_menu_order
from core.users.permission_policies import TeamScopedSnippetViewSetMixin

from .models import Location


class LocationViewSet(TeamScopedSnippetViewSetMixin, SnippetViewSet):
    model = Location
    allow_unscoped_queryset = True
    menu_label = _("Location")
    menu_icon = "folder"
    menu_order = get_menu_order("location")
    add_to_settings_menu = False

    list_display = (
        "country",
        "state",
        "city",
        "creator",
        "updated",
        "created",
    )
    search_fields = (
        "country",
        "state",
        "city",
    )
    list_export = (
        "country",
        "state",
        "city",
    )
    export_filename = "locations"


register_snippet(LocationViewSet)
