# Create your views here.
import logging

from django.http import HttpResponseRedirect, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from wagtail.contrib.modeladmin.views import CreateView, EditView, InspectView

from .models import Article, RelatedItem, RequestArticleChange, choices


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
            change_request_obj.article = Article.objects.get(pk=article_id)
        return change_request_obj

    def form_valid(self, form):
        self.object = form.save_all(self.request.user)
        return HttpResponseRedirect(self.get_success_url())


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


def download_package(request):
    """
    This view function enables the user to download the package through admin
    """
    article_id = request.GET.get("article_id")

    if article_id:
        article = get_object_or_404(Article, pk=article_id)

    try:
        package = article.get_package()
        response = HttpResponse(package["content"], content_type="application/zip")
        response["Content-Disposition"] = "attachment; filename=" + package["filename"]
        return response
    except Exception as e:
        logging.exception(e)
        raise Http404
