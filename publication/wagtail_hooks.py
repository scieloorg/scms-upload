from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSet

from .models import ArticleAvailability, MissingArticle


class ArticleAvailabilitySiteViewSet(SnippetViewSet):
    model = ArticleAvailability
    menu_icon = "folder"
    menu_order = 100
    add_to_settings_menu = False  # or True to add your model to the Settings sub-menu
    exclude_from_explorer = (
        False  # or True to exclude pages of this type from Wagtail's explorer view
    )
    list_display = "article"
    search_fields = (
        "article__pid_v3",
        "article__pid_v2",
    )


class ArticleAvailabilityFileViewSet(SnippetViewSet):
    model = MissingArticle
    menu_icon = "folder"
    menu_order = 200
    add_to_settings_menu = False  # or True to add your model to the Settings sub-menu
    exclude_from_explorer = (
        False  # or True to exclude pages of this type from Wagtail's explorer view
    )
    list_display = (
        "get_collection_name",
        "pid_v2",
    )


register_snippet(ArticleAvailabilitySiteViewSet)
register_snippet(ArticleAvailabilityFileViewSet)
