# Create your views here.
from django.http import HttpResponseRedirect
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
