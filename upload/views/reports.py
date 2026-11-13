import logging

from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from core.users.permission_policies import TeamScopedEditView
from upload.permissions import FINISH_DEPOSIT
from upload.querysets import get_scoped_package_queryset
from upload.tasks import task_upload_workflow_publish_article


class XMLInfoReportEditView(TeamScopedEditView):
    def get_success_url(self):
        return self.get_package_url()

    def get_breadcrumbs_items(self):
        items = super().get_breadcrumbs_items()
        items.insert(-1, {"url": self.get_package_url(), "label": _("Document")})

        return items

    def form_valid(self, form):
        form.save_all(self.request.user)

        messages.success(
            self.request,
            _("Success ..."),
        )

        return redirect(self.get_package_url())

    def get_package_url(self):
        report = self.object
        return (
            reverse("wagtailsnippets_upload_package:inspect", args=[report.package_id])
            + "?tab=validations#xi"
        )


class ValidationReportEditView(XMLInfoReportEditView):
    def get_package_url(self):
        report = self.object
        return (
            reverse("wagtailsnippets_upload_package:inspect", args=[report.package_id])
            + f"?tab=validations#vr{report.id}"
        )


class XMLErrorReportEditView(XMLInfoReportEditView):
    def get_package_url(self):
        report = self.object
        return (
            reverse("wagtailsnippets_upload_package:inspect", args=[report.package_id])
            + f"?tab=validations#xer{report.id}"
        )


def finish_deposit(request):
    if not request.user.has_perm(f"upload.{FINISH_DEPOSIT}"):
        messages.error(request, _("Operation not available"))
        return redirect("wagtailsnippets_upload_package:list")

    package_id = request.POST.get("package_id") or request.GET.get("package_id")
    if not package_id:
        messages.error(request, _("Package not informed"))
        return redirect("wagtailsnippets_upload_package:list")

    package = get_object_or_404(
        get_scoped_package_queryset(request.user, FINISH_DEPOSIT),
        pk=package_id,
    )

    if request.method != "POST":
        return render(
            request,
            "upload/admin/package/confirm_action.html",
            {
                "title": _("Submit validation responses"),
                "message": _(
                    "The ZIP has already been received. Submit the validation responses "
                    "to determine whether the document needs corrections or can proceed "
                    "with processing."
                ),
                "submit_label": _("Submit validation responses"),
                "package": package,
                "cancel_url": reverse(
                    "wagtailsnippets_upload_package:inspect", args=[package_id]
                ),
            },
        )

    if package.finish_deposit(task_upload_workflow_publish_article):
        messages.success(
            request, _("Validation responses processed. Check the document status.")
        )
        return redirect("wagtailsnippets_upload_package:list")

    if not package.is_error_review_finished:
        messages.error(
            request,
            _("The XML package needs review and comment"),
        )
        return redirect("wagtailsnippets_upload_package:inspect", pk=package_id)

    if not package.is_acceptable_package:
        messages.error(
            request,
            _("Package deposit failed due to errors"),
        )
        messages.error(
            request,
            _("Correct package based on report and resubmit"),
        )

    return redirect("wagtailsnippets_upload_package:inspect", pk=package_id)


def download_errors(request):
    package_id = request.GET.get("package_id")

    if package_id:
        package = get_object_or_404(
            get_scoped_package_queryset(request.user), pk=package_id
        )

    try:
        errors = package.get_errors_report_content()
        response = HttpResponse(errors["content"], content_type="text/csv")
        response["Content-Disposition"] = "inline; filename=" + errors["filename"]
        logging.info(errors)
        return response
    except Exception as e:
        logging.exception(e)
        raise Http404
