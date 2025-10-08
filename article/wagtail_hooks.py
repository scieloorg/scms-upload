from django.conf import settings
from django.contrib import messages
from django.urls import include, path
from django.utils.translation import gettext_lazy as _
from wagtail import hooks
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSet, SnippetViewSetGroup

from article.views import (
    ArticleAdminInspectView,
    ArticleCreateView,
    RelatedItemCreateView,
    RequestArticleChangeCreateView,
)
from config.menu import get_menu_order

from .button_helper import ArticleButtonHelper, RequestArticleChangeButtonHelper
from .models import Article, RelatedItem, RequestArticleChange
from .permission_helper import ArticlePermissionHelper

# from upload import exceptions as upload_exceptions
# from upload.models import Package
# from upload.tasks import get_or_create_package


class ArticleSnippetViewSet(SnippetViewSet):
    model = Article
    menu_label = _("Articles")
    # add_view_class = ArticleCreateView
    # button_helper_class = ArticleButtonHelper  # Precisa adaptar para SnippetViewSet
    # permission_helper_class = ArticlePermissionHelper  # Precisa adaptar para SnippetViewSet
    # inspect_view_enabled = True  # Habilitado por padrão em SnippetViewSet
    inspect_view_class = ArticleAdminInspectView
    menu_icon = "doc-full"
    menu_order = get_menu_order("article")
    add_to_settings_menu = False
    # exclude_from_explorer = False  # Não aplicável a SnippetViewSet
    list_per_page = 20

    list_display = (
        "__str__",
        "pid_v3",
        "status",
        "display_sections",
        "fpage",
        "position",
        "first_publication_date",
        "created",
        "updated",
        # "updated_by",
    )
    list_filter = ("status", "journal")
    search_fields = (
        "sps_pkg__sps_pkg_name",
        "pid_v3",
        "issue__publication_year",
        "journal__official_journal__title",
        "journal__official_journal__issn_print",
        "journal__official_journal__issn_electronic",
        "title_with_lang__text",
    )
    # inspect_view_fields não é usado em SnippetViewSet, use inspect_view_class customizada


class RelatedItemSnippetViewSet(SnippetViewSet):
    model = RelatedItem
    menu_label = _("Related items")
    add_view_class = RelatedItemCreateView
    # inspect_view_enabled = True  # Habilitado por padrão
    menu_icon = "doc-full"
    menu_order = 200
    add_to_settings_menu = False
    # exclude_from_explorer = False  # Não aplicável

    list_display = (
        "item_type",
        "source_article",
        "target_article",
        "created",
        "updated",
        "updated_by",
    )
    list_filter = (
        "item_type",
        "target_article__issue",
    )
    search_fields = ("target_article__issue__journal_ISSNL",)
    # inspect_view_fields não é usado em SnippetViewSet


class RequestArticleChangeSnippetViewSet(SnippetViewSet):
    model = RequestArticleChange
    menu_label = _("Changes request")
    # button_helper_class = RequestArticleChangeButtonHelper  # Precisa adaptar
    add_view_class = RequestArticleChangeCreateView
    # permission_helper_class = ArticlePermissionHelper  # Precisa adaptar
    menu_icon = "doc-full"
    menu_order = 200
    add_to_settings_menu = False
    # exclude_from_explorer = False  # Não aplicável

    list_display = (
        "creator",
        "created",
        "article",
        "change_type",
    )
    list_filter = ("change_type",)
    search_fields = (
        "article__pid_v2",
        "article__pid_v3",
        "article__doi_with_lang__doi",
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)

        # Temporariamente comentado - precisa adaptar permission_helper para SnippetViewSet
        # if self.permission_helper.user_can_make_article_change(request.user, None):
        #     return qs

        return qs


class ArticleSnippetViewSetGroup(SnippetViewSetGroup):
    menu_label = _("Articles")
    menu_icon = "folder-open-inverse"
    menu_order = get_menu_order("article")
    items = (
        ArticleSnippetViewSet,
        # RelatedItemSnippetViewSet,
        # omitir temporariamente RequestArticleChangeSnippetViewSet,
        # ApprovedArticleSnippetViewSet,
    )


register_snippet(ArticleSnippetViewSetGroup)


@hooks.register("register_admin_urls")
def register_disclosure_url():
    return [
        path("article/", include("article.urls", namespace="article")),
    ]
