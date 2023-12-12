from django.contrib import messages
from django.http import HttpResponseRedirect
from django.shortcuts import redirect
from django.urls import include, path
from django.utils.translation import gettext as _
from wagtail import hooks
from wagtail.contrib.modeladmin.options import (
    ModelAdmin,
    ModelAdminGroup,
    modeladmin_register,
)
from wagtail.contrib.modeladmin.views import CreateView, InspectView

from config.menu import get_menu_order

from .button_helper import ArticleButtonHelper, RequestArticleChangeButtonHelper
from .models import Article, RelatedItem, RequestArticleChange, choices
from .permission_helper import ArticlePermissionHelper

# from upload import exceptions as upload_exceptions
# from upload.models import Package
# from upload.tasks import get_or_create_package


class ArticleCreateView(CreateView):
    def form_valid(self, form):
        self.object = form.save_all(self.request.user)
        return HttpResponseRedirect(self.get_success_url())


class RelatedItemCreateView(CreateView):
    def form_valid(self, form):
        self.object = form.save_all(self.request.user)
        return HttpResponseRedirect(self.get_success_url())


class RequestArticleChangeCreateView(CreateView):
    def get_instance(self):
        change_request_obj = super().get_instance()

        article_id = self.request.GET.get("article_id")
        if article_id:
            article = Article.objects.get(pk=article_id)

            if article:
                change_request_obj.pid_v3 = article.pid_v3

        return change_request_obj

    # # FIXME
    # def form_valid(self, form):
    #     pid_v3 = self.request.POST['pid_v3']

    #     try:
    #         package_id = get_or_create_package(
    #             pid_v3=pid_v3,
    #             user_id=self.request.user.id
    #         )
    #     except upload_exceptions.XMLUriIsUnavailableError as e:
    #         messages.error(
    #             self.request,
    #             _('It was not possible to submit the request. XML Uri is unavailable: %s.') % e.uri,
    #         )
    #         return redirect(self.request.META.get('HTTP_REFERER'))
    #     except upload_exceptions.PIDv3DoesNotExistInSiteDatabase:
    #         messages.error(
    #             self.request,
    #             _('It was not possible to submit the request. PIDv3 does not exist in the site database.'),
    #         )
    #         return redirect(self.request.META.get('HTTP_REFERER'))
    #     except upload_exceptions.SiteDatabaseIsUnavailableError:
    #         messages.error(
    #             self.request,
    #             _('It was not possible to submit the request. Site database is unavailable.'),
    #         )
    #         return redirect(self.request.META.get('HTTP_REFERER'))

    #     article = Package.objects.get(pk=package_id).article

    #     change_request_obj = form.save_all(self.request.user, article)

    #     if change_request_obj.change_type == choices.RCT_ERRATUM:
    #         article.status =  choices.AS_REQUIRE_ERRATUM
    #     elif change_request_obj.change_type ==  choices.RCT_UPDATE:
    #         article.status = choices.AS_REQUIRE_UPDATE

    #     article.save()

    #     messages.success(
    #         self.request,
    #         _('Change request submitted with success.')
    #     )
    #     return HttpResponseRedirect(self.get_success_url())


class ArticleAdminInspectView(InspectView):
    def get_context_data(self):
        data = {
            "status": self.instance.status,
            "packages": self.instance.package_set.all(),
        }

        if self.instance.status in (
            choices.AS_REQUIRE_UPDATE,
            choices.AS_REQUIRE_ERRATUM,
        ):
            data["requested_changes"] = []
            for rac in self.instance.requestarticlechange_set.all():
                data["requested_changes"].append(rac)

        return super().get_context_data(**data)


class ArticleModelAdmin(ModelAdmin):
    model = Article
    menu_label = _("Articles")
    create_view_class = ArticleCreateView
    button_helper_class = ArticleButtonHelper
    permission_helper_class = ArticlePermissionHelper
    inspect_view_enabled = True
    inspect_view_class = ArticleAdminInspectView
    menu_icon = "doc-full"
    menu_order = 200
    add_to_settings_menu = False
    exclude_from_explorer = False

    list_display = (
        "pid_v3",
        # "pid_v2",
        # "doi_list",
        # "aop_pid",
        # "article_type",
        "status",
        "issue",
        "journal",
        "created",
        "updated",
        # "updated_by",
    )
    list_filter = ("status",)
    search_fields = (
        "pid_v3",
        "issue__publication_year",
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
        "deadline",
        "article",
        "pid_v3",
        "change_type",
        "demanded_user",
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
            return qs.filter(demanded_user=request.user)

        return qs


class ArticleModelAdminGroup(ModelAdminGroup):
    menu_label = _("Articles")
    menu_icon = "folder-open-inverse"
    # menu_order = get_menu_order("article")
    menu_order = 400
    items = (
        ArticleModelAdmin,
        # RelatedItemModelAdmin,
        # RequestArticleChangeModelAdmin,
    )


# modeladmin_register(ArticleModelAdminGroup)
modeladmin_register(ArticleModelAdmin)


@hooks.register("register_admin_urls")
def register_disclosure_url():
    return [
        path("article/", include("article.urls", namespace="article")),
    ]
