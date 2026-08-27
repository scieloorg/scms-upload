from django.utils.translation import gettext_lazy as _
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSet

from config.menu import get_menu_order
from core.users.permission_policies import TeamScopedSnippetViewSetMixin

from .models import Institution


class InstitutionViewSet(TeamScopedSnippetViewSetMixin, SnippetViewSet):
    model = Institution
    allow_unscoped_queryset = True
    menu_label = _("Institution")
    menu_icon = "folder"
    menu_order = get_menu_order("institution")
    add_to_settings_menu = False

    list_display = (
        "name",
        "institution_type",
        "creator",
        "updated",
        "created",
        "updated_by",
    )
    search_fields = (
        "name",
    )
    list_filter = (
        "institution_type",
    )
    list_export = (
        "name",
        "institution_type",
        "level_1",
        "level_2",
        "level_3",
        "creator",
        "updated",
        "created",
        "updated_by",
    )
    export_filename = "institutions"


register_snippet(InstitutionViewSet)
