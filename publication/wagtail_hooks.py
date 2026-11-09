from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSet

from .models import ArticleAvailability


class ArticleAvailabilitySiteViewSet(SnippetViewSet):
    model = ArticleAvailability
    menu_icon = "folder"
    menu_order = 100
    add_to_settings_menu = False  # or True to add your model to the Settings sub-menu
    exclude_from_explorer = (
        False  # or True to exclude pages of this type from Wagtail's explorer view
    )
    list_display = (
        "article",
        "completed",
        "published_by",
        "publication_rule",
    )
    search_fields = (
        "article__sps_pkg__sps_pkg_name",
        "article__pid_v3",
        "article__pid_v2",
    )
    list_filter = (
        "completed",
        "published_by",
        "publication_rule",
    )


register_snippet(ArticleAvailabilitySiteViewSet)
