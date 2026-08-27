import logging

from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from wagtail.snippets.views.snippets import CreateView

from core.users.permission_policies import TeamScopedInspectView
from core.users.scoped_queryset import scope_by_membership

from .models import Article, choices


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
            scoped_qs = scope_by_membership(
                self.request.user,
                Article.objects.all(),
                journal_field="journal",
            )
            change_request_obj.article = get_object_or_404(scoped_qs, pk=article_id)
        return change_request_obj

    def form_valid(self, form):
        self.object = form.save_all(self.request.user)
        return HttpResponseRedirect(self.get_success_url())


class ArticleAdminInspectView(TeamScopedInspectView):
    def get_context_data(self, **kwargs):
        instance = getattr(self, "object", getattr(self, "instance", None))
        data = {
            "status": instance.status if instance else None,
        }

        if instance and instance.status in (
            choices.AS_REQUIRE_UPDATE,
            choices.AS_REQUIRE_ERRATUM,
        ):
            data["requested_changes"] = list(instance.requestarticlechange_set.all())

        kwargs.update(data)
        return super().get_context_data(**kwargs)


def download_package(request):
    """
    This view function enables the user to download the package through admin
    """
    article_id = request.GET.get("article_id")
    if not article_id:
        raise Http404

    scoped_qs = scope_by_membership(
        request.user,
        Article.objects.all(),
        journal_field="journal",
    )
    article = get_object_or_404(scoped_qs, pk=article_id)

    try:
        package = article.get_package()
        response = HttpResponse(package["content"], content_type="application/zip")
        response["Content-Disposition"] = "attachment; filename=" + package["filename"]
        return response
    except Exception as e:
        logging.exception(e)
        raise Http404
