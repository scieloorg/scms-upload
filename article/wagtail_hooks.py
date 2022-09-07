from django.http import HttpResponseRedirect
from django.urls import include, path
from django.utils.translation import gettext as _

from wagtail.core import hooks
from wagtail.contrib.modeladmin.options import ModelAdmin, modeladmin_register
from wagtail.contrib.modeladmin.views import CreateView

from .models import Article


class ArticleCreateView(CreateView):
    def form_valid(self, form):
        self.object = form.save_all(self.request.user)
        return HttpResponseRedirect(self.get_success_url())


class ArticleModelAdmin(ModelAdmin):
    model = Article
    menu_label = _('Articles')
    create_view_class = ArticleCreateView
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
        'journal',
        'created',
        'updated',
        'updated_by',
    )
    list_filter = (
        'journal',
    )
    search_fields = (
        'pid_v2',
        'pid_v3',
        'doi_with_lang__doi',
        'aop_pid',
        'journal__title',
        'journal__ISSNL',
    )
    inspect_view_fields = (
        'created',
        'updated',
        'creator',
        'updated_by',
        'pid_v3',
        'pid_v2',
        'doi_with_lang',
        'aop_pid',
        'related_item',
        'author',
        'title_with_lang',
        'pub_year',
        'volume',
        'number',
        'suppl',
        'elocation_id',
        'fpage',
        'lpage',
        'journal',
    )

