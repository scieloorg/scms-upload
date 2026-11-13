from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.generic.edit import FormView
from wagtail.admin.views.generic.base import WagtailAdminTemplateMixin

from article.authorization import can_request_article_change
from article.models import RequestArticleChange
from upload.forms import RequestDocumentChangeForm
from upload.models import Package, UploadProcResult
from upload.permission_policies import UploadModelPermissionPolicy
from upload.querysets import get_scoped_package_queryset


class RequestArticleChangeView(WagtailAdminTemplateMixin, FormView):
    page_title = _("Request document change")
    header_icon = ""
    template_name = "upload/changes/request.html"
    form_class = RequestDocumentChangeForm

    def dispatch(self, request, *args, **kwargs):
        policy = UploadModelPermissionPolicy(Package)
        if not policy.user_has_any_permission(request.user, ("view", "change")):
            raise PermissionDenied

        self.package = get_object_or_404(
            get_scoped_package_queryset(request.user), pk=kwargs["pk"]
        )
        if not can_request_article_change(request.user, self.package.article):
            raise PermissionDenied

        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        return {
            **super().get_form_kwargs(),
            "user": self.request.user,
            "article": self.package.article,
        }

    def get_success_url(self):
        return reverse("wagtailsnippets_upload_package:inspect", args=[self.package.pk])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            document_identity=self.package.document_identity,
            document_url=self.get_success_url(),
            submit_button_label=_("Request document change"),
            submit_button_active_label=_("Saving…"),
        )
        return context

    def form_valid(self, form):
        try:
            with transaction.atomic():
                change_request = RequestArticleChange.request(
                    self.request.user,
                    self.package.article,
                    form.cleaned_data["change_type"],
                    form.cleaned_data["comment"],
                )
                event = UploadProcResult.create(
                    self.request.user, self.package, "request_article_change"
                )
                event.finish(
                    self.request.user,
                    completed=True,
                    detail={
                        "request_id": change_request.pk,
                        "change_type": change_request.change_type,
                        "comment": change_request.comment,
                        "status": change_request.status,
                    },
                )
        except ValidationError as error:
            form.add_error(None, ValidationError(error.messages))
            return self.form_invalid(form)

        messages.success(self.request, _("Document change requested."))
        return redirect(self.get_success_url())
