import django_filters
from django.urls import include, path
from django.utils.translation import gettext_lazy as _
from wagtail import hooks
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSet, SnippetViewSetGroup

from article import choices
from article.models import Article, ArticleWebPage, RelatedItem, RequestArticleChange
from article.views import (
    ArticleAdminInspectView,
    RelatedItemCreateView,
    RequestArticleChangeCreateView,
)
from collection.models import Collection
from config.menu import get_menu_order
from core.users.permission_policies import TeamScopedSnippetViewSetMixin


class ArticleFilterSet(django_filters.FilterSet):
    journal__journal_acron = django_filters.CharFilter(
        field_name="journal__journal_acron",
        label=_("Journal Acronym"),
        lookup_expr="exact",
    )
    status = django_filters.ChoiceFilter(
        field_name="status",
        label=_("Status"),
        choices=choices.ARTICLE_STATUS,
    )
    collection = django_filters.ModelChoiceFilter(
        field_name="article_collections__collection",
        label=_("Collection"),
        queryset=Collection.objects.filter(
            articlecollection__article__isnull=False
        ).distinct(),
    )

    class Meta:
        model = Article
        fields = []


class ArticleSnippetViewSet(TeamScopedSnippetViewSetMixin, SnippetViewSet):
    model = Article
    journal_field = "journal"
    menu_label = _("Articles")
    inspect_view_class = ArticleAdminInspectView
    menu_icon = "doc-full"
    menu_order = get_menu_order("article")
    add_to_settings_menu = False
    list_per_page = 20
    list_display = (
        "sps_pkg__sps_pkg_name",
        "pid_v3",
        "pid_v2",
        "status",
        "display_collections",
        "first_pubdate_iso",
        "updated",
    )
    filterset_class = ArticleFilterSet
    search_fields = (
        "sps_pkg__sps_pkg_name",
        "pid_v2",
        "pid_v3",
        "issue__publication_year",
        "journal__official_journal__title",
        "journal__official_journal__issn_print",
        "journal__official_journal__issn_electronic",
        "title_with_lang__text",
        "article_collections__collection__acron",
        "article_collections__collection__name",
    )


class RelatedItemSnippetViewSet(TeamScopedSnippetViewSetMixin, SnippetViewSet):
    model = RelatedItem
    journal_field = "source_article__journal"
    menu_label = _("Related items")
    add_view_class = RelatedItemCreateView
    menu_icon = "doc-full"
    menu_order = 200
    add_to_settings_menu = False

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


class RequestArticleChangeSnippetViewSet(TeamScopedSnippetViewSetMixin, SnippetViewSet):
    model = RequestArticleChange
    journal_field = "article__journal"
    menu_label = _("Changes request")
    add_view_class = RequestArticleChangeCreateView
    menu_icon = "doc-full"
    menu_order = 200
    add_to_settings_menu = False

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


class ArticleWebPageFilterSet(django_filters.FilterSet):
    purpose = django_filters.ChoiceFilter(
        field_name="purpose",
        label=_("Purpose"),
        choices=choices.ARTICLE_WEBPAGE_PURPOSE,
    )
    status = django_filters.ChoiceFilter(
        field_name="status",
        label=_("Status"),
        choices=choices.ARTICLE_WEBPAGE_STATUS,
    )
    fmt = django_filters.CharFilter(
        field_name="fmt",
        label=_("Format"),
        lookup_expr="exact",
    )
    collection = django_filters.ModelChoiceFilter(
        field_name="collection",
        label=_("Collection"),
        queryset=Collection.objects.all(),
    )

    class Meta:
        model = ArticleWebPage
        fields = []


class ArticleWebPageSnippetViewSet(TeamScopedSnippetViewSetMixin, SnippetViewSet):
    model = ArticleWebPage
    collection_field = "collection"
    menu_label = _("Web Pages")
    menu_icon = "globe"
    menu_order = 300
    add_to_settings_menu = False
    inspect_view_enabled = True
    list_per_page = 20

    list_display = (
        "url",
        "purpose",
        "fmt",
        "lang",
        "status",
        "article",
        "collection",
        "updated",
    )
    filterset_class = ArticleWebPageFilterSet
    search_fields = (
        "url",
        "article__pid_v3",
        "article__pid_v2",
        "article__sps_pkg__sps_pkg_name",
    )
    ordering = ["-updated"]


class ArticleSnippetViewSetGroup(SnippetViewSetGroup):
    menu_label = _("Articles")
    menu_icon = "folder-open-inverse"
    menu_order = get_menu_order("article")
    items = (
        ArticleSnippetViewSet,
        ArticleWebPageSnippetViewSet,
    )


register_snippet(ArticleSnippetViewSetGroup)


@hooks.register("register_admin_urls")
def register_disclosure_url():
    return [
        path("article/", include("article.urls", namespace="article")),
    ]
