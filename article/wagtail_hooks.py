from django.urls import include, path
from django.utils.translation import gettext as _
from wagtail import hooks
from wagtail.contrib.modeladmin.options import (
    ModelAdmin,
    ModelAdminGroup,
    modeladmin_register,
)

from article.views import (
    ArticleAdminInspectView,
    ArticleCreateView,
    RelatedItemCreateView,
    RequestArticleChangeCreateView,
)
from config.menu import get_menu_order

from .button_helper import ArticleButtonHelper, RequestArticleChangeButtonHelper

from .models import Article, RelatedItem, RequestArticleChange, choices, ScieloSiteStatus
from .permission_helper import ArticlePermissionHelper

# from upload import exceptions as upload_exceptions
# from upload.models import Package
# from upload.tasks import get_or_create_package


class ArticleModelAdmin(ModelAdmin):
    model = Article
    menu_label = _("Articles")
    create_view_class = ArticleCreateView
    button_helper_class = ArticleButtonHelper
    permission_helper_class = ArticlePermissionHelper
    inspect_view_enabled = True
    inspect_view_class = ArticleAdminInspectView
    menu_icon = "doc-full"
    menu_order = get_menu_order("article")
    add_to_settings_menu = False
    exclude_from_explorer = False
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
    list_filter = ("status",)
    search_fields = (
        "sps_pkg__sps_pkg_name",
        "pid_v3",
        "issue__publication_year",
        "journal__official_journal__title",
        "journal__official_journal__issn_print",
        "journal__official_journal__issn_electronic",
        "title_with_lang__text",
    )
    inspect_view_fields = (
        "created",
        "updated",
        "creator",
        "updated_by",
        "pid_v3",
        # "pid_v2",
        # "aop_pid",
        "doi_with_lang",
        "article_type",
        "status",
        "issue",
        # "author",
        # "title_with_lang",
        "elocation_id",
        "fpage",
        "lpage",
    )


class RelatedItemModelAdmin(ModelAdmin):
    model = RelatedItem
    menu_label = _("Related items")
    create_view_class = RelatedItemCreateView
    inspect_view_enabled = True
    menu_icon = "doc-full"
    menu_order = 200
    add_to_settings_menu = False
    exclude_from_explorer = False

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
    inspect_view_fields = (
        "created",
        "updated",
        "creator",
        "updated_by",
        "item_type",
        "source_article",
        "target_article",
    )


class RequestArticleChangeModelAdmin(ModelAdmin):
    model = RequestArticleChange
    menu_label = _("Changes request")
    button_helper_class = RequestArticleChangeButtonHelper
    create_view_class = RequestArticleChangeCreateView
    permission_helper_class = ArticlePermissionHelper
    menu_icon = "doc-full"
    menu_order = 200
    add_to_settings_menu = False
    exclude_from_explorer = False

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

        if self.permission_helper.user_can_make_article_change(request.user, None):
            return qs

        return qs


class ArticleModelAdminGroup(ModelAdminGroup):
    menu_label = _("Articles")
    menu_icon = "folder-open-inverse"
    menu_order = get_menu_order("article")
    items = (
        ArticleModelAdmin,
        # RelatedItemModelAdmin,
        # omitir temporariamente RequestArticleChangeModelAdmin,
        # ApprovedArticleModelAdmin,
    )

class ScieloSiteStatusAdmin(ModelAdmin):
    model = ScieloSiteStatus
    menu_label = "Scielo Site Status"
    menu_icon = "doc-full"
    list_display = (
        "article",
        "url_site_scielo",
        "status",
        "check_date",
        "available",
        "type",
    )
    search_fields= (
        "url_site_scielo",
        "checkarticleavailability__article__pid_v3"
    )
    list_filter = (
        "type",
    )
    menu_order = 200
    add_to_settings_menu = False
    exclude_from_explorer = False
    
    def article(self, obj):
        return list(obj.checkarticleavailability_set.all())


    def get_queryset(self, request):
        return super().get_queryset(request).filter(available=False)



modeladmin_register(ScieloSiteStatusAdmin)
modeladmin_register(ArticleModelAdmin)
modeladmin_register(ArticleModelAdminGroup)



@hooks.register("register_admin_urls")
def register_disclosure_url():
    return [
        path("article/", include("article.urls", namespace="article")),
    ]
