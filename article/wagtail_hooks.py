from django.contrib import messages
from django.http import HttpResponseRedirect
from django.shortcuts import redirect
from django.urls import include, path
from django.utils.translation import gettext as _

from wagtail.core import hooks
from wagtail.contrib.modeladmin.options import ModelAdmin, ModelAdminGroup, modeladmin_register
from wagtail.contrib.modeladmin.views import CreateView

from upload.controller import update_package_check_request_change
from upload.tasks import get_or_create_package

from .button_helper import ArticleButtonHelper
from .models import Article, RelatedItem, RequestArticleChange
from .permission_helper import ArticlePermissionHelper


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

        article_id = self.request.GET.get('article_id')
        if article_id:
            article = Article.objects.get(pk=article_id)

            if article:
                change_request_obj.article_id = article

        return change_request_obj

    def form_valid(self, form):
        article_id = self.request.POST['article']
        pid = self.request.POST['pid_v3']

        package_id = get_or_create_package(
            article_id=article_id, 
            pid=pid,
            user_id=self.request.user.id
        )

        if not package_id:
            messages.error(
                self.request,
                _('It was not possible to submit the request. Check the PID v3 code.')
            )
            return redirect(self.request.META.get('HTTP_REFERER'))

        change_request_obj = form.save_all(self.request.user)

        update_package_check_request_change(
            package_id=package_id,
            change_type=change_request_obj.change_type
        )

        messages.success(
            self.request, 
            _('Change request submitted with success.')
        )
        return HttpResponseRedirect(self.get_success_url())


class ArticleModelAdmin(ModelAdmin):
    model = Article
    menu_label = _('Articles')
    create_view_class = ArticleCreateView
    button_helper_class = ArticleButtonHelper
    permission_helper_class = ArticlePermissionHelper
    inspect_view_enabled=True
    menu_icon = 'doc-full'
    menu_order = 200
    add_to_settings_menu = False
    exclude_from_explorer = False

    def doi_list(self, obj):
        return ', '.join([str(dl) for dl in obj.doi_with_lang.all()])

    list_display = (
        'pid_v2',
        'pid_v3',
        'doi_list',
        'aop_pid',
        'article_type',
        'issue',
        'created',
        'updated',
        'updated_by',
    )
    list_filter = (
        'article_type',
    )
    search_fields = (
        'pid_v2',
        'pid_v3',
        'doi_with_lang__doi',
        'aop_pid',
    )
    inspect_view_fields = (
        'created',
        'updated',
        'creator',
        'updated_by',
        'pid_v3',
        'pid_v2',
        'aop_pid',
        'doi_with_lang',
        'article_type',
        'issue',
        'author',
        'title_with_lang',
        'elocation_id',
        'fpage',
        'lpage',
    )


class RelatedItemModelAdmin(ModelAdmin):
    model = RelatedItem
    menu_label = _('Related items')
    create_view_class = RelatedItemCreateView
    inspect_view_enabled=True
    menu_icon = 'doc-full'
    menu_order = 200
    add_to_settings_menu = False
    exclude_from_explorer = False

    list_display = (
        'item_type',
        'source_article',
        'target_article',
        'created',
        'updated',
        'updated_by',
    )
    list_filter = (
        'item_type',
        'target_article__issue',
    )
    search_fields = (
        'target_article__issue__journal_ISSNL',
    )
    inspect_view_fields = (
        'created',
        'updated',
        'creator',
        'updated_by',
        'item_type',
        'source_article',
        'target_article',
    )

class ArticleModelAdminGroup(ModelAdminGroup):
    menu_label = _('Articles')
    menu_icon = 'folder-open-inverse'
    menu_order = 200
    items = (ArticleModelAdmin, RelatedItemModelAdmin)


modeladmin_register(ArticleModelAdminGroup)


@hooks.register('register_admin_urls')
def register_disclosure_url():
    return [
        path('article/',
        include('article.urls', namespace='article')),
    ]
