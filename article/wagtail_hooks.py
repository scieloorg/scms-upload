import django_filters
from django.conf import settings
from django.contrib.admin import SimpleListFilter
from django.urls import include, path
from django.utils.translation import gettext_lazy as _
from wagtail import hooks
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSet, SnippetViewSetGroup

from article.views import (
    ArticleAdminInspectView,
    RelatedItemCreateView,
    RequestArticleChangeCreateView,
)
from config.menu import get_menu_order
from collection.models import Collection
from .models import Article, ArticleWebPage, RelatedItem, RequestArticleChange
from article import choices

# from upload import exceptions as upload_exceptions
# from upload.models import Package
# from upload.tasks import get_or_create_package


class ArticleFilterSet(django_filters.FilterSet):
    journal__journal_acron = django_filters.CharFilter(
        field_name="journal__journal_acron",
        label=_("Journal Acronym"),
        lookup_expr="exact",
    )
    status = django_filters.ChoiceFilter(
        field_name="status",
        label=_("Status"),
        choices=choices.ARTICLE_STATUS,  # ajuste para o nome real das choices
    )
    collection = django_filters.ModelChoiceFilter(
        field_name="journal__journalproc__collection",
        label=_("Collection"),
        queryset=Collection.objects.filter(
            journalproc__journal__article__isnull=False
        ).distinct(),
    )

    class Meta:
        model = Article
        fields = []


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
        "pid_v2",
        "status",
        "display_collections",
        "first_pubdate_iso",
        "updated",
        # "updated_by",
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
        "sps_pkg__articleproc__collection__acron",
        "sps_pkg__articleproc__collection__name",
    )
    # inspect_view_fields não é usado em SnippetViewSet, use inspect_view_class customizada

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        try:
            return qs.distinct()
        except AttributeError:
            return qs


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

        try:
            return qs.distinct()
        except AttributeError:
            return qs


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
        field_name="article_collection__collection",
        label=_("Collection"),
        queryset=Collection.objects.all(),
    )

    class Meta:
        model = ArticleWebPage
        fields = []


class ArticleWebPageSnippetViewSet(SnippetViewSet):
    model = ArticleWebPage
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
        "article_collection",
        "updated",
    )
    filterset_class = ArticleWebPageFilterSet
    search_fields = (
        "url",
        "article_collection__article__pid_v3",
        "article_collection__article__pid_v2",
        "article_collection__article__sps_pkg__sps_pkg_name",
    )
    ordering = ["-updated"]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        try:
            return qs.select_related(
                "article_collection__article",
                "article_collection__collection",
                "lang",
            ).distinct()
        except AttributeError:
            return qs


class ArticleSnippetViewSetGroup(SnippetViewSetGroup):
    menu_label = _("Articles")
    menu_icon = "folder-open-inverse"
    menu_order = get_menu_order("article")
    items = (
        ArticleSnippetViewSet,
        ArticleWebPageSnippetViewSet,
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
