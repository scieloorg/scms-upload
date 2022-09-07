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

