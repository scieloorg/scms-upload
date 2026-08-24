from django.utils.translation import gettext_lazy as _
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSet

from config.menu import get_menu_order
from core.users.permission_policies import TeamScopedSnippetViewSetMixin

from .models import Researcher


class ResearcherViewSet(TeamScopedSnippetViewSetMixin, SnippetViewSet):
    model = Researcher
    allow_unscoped_queryset = True
    menu_label = _("Researcher")
    menu_icon = "folder"
    menu_order = get_menu_order("researcher")
    add_to_settings_menu = False


register_snippet(ResearcherViewSet)
