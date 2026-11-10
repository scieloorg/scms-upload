from functools import partial

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponseNotAllowed, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from wagtail.snippets.views.snippets import CreateView

from upload.models import NEWER_DOCUMENT, Package, PackageZip, UploadProcResult, choices
from upload.querysets import get_scoped_package_queryset
from upload.tasks import task_receive_packages


class PackageZipCreateView(CreateView):
    def form_valid(self, form):
        if not self.permission_policy.user_has_permission(
            self.request.user,
            "add",
        ):
            messages.error(
                self.request,
                _("Operation not available"),
            )
            return HttpResponseRedirect(self.get_success_url())

        pkg_zip = form.save_all(self.request.user)
        transaction.on_commit(
            partial(
                task_receive_packages.apply_async,
                kwargs=dict(
                    user_id=self.request.user.id,
                    pkg_zip_id=pkg_zip.id,
                ),
            )
        )
        documents_url = reverse("wagtailsnippets_upload_package:list")
        messages.success(
            self.request,
            format_html(
                '{} <a href="{}?pkg_zip_id={}">{}</a>',
                _(
                    "Package received. Processing runs in the background. "
                    "Follow its progress in Documents."
                ),
                documents_url,
                pkg_zip.pk,
                _("View documents"),
            ),
        )

        return HttpResponseRedirect(self.get_success_url())


@transaction.atomic
def retry_processing(request):
    if request.method not in ("GET", "POST"):
        return HttpResponseNotAllowed(["GET", "POST"])
    if not request.user.is_authenticated or not request.user.is_active:
        raise PermissionDenied
    package_id = (
        request.POST.get("package_id")
        if request.method == "POST"
        else request.GET.get("package_id")
    )
    submission_id = get_object_or_404(
        get_scoped_package_queryset(request.user), pk=package_id
    ).pkg_zip_id
    if submission_id:
        PackageZip.objects.select_for_update().get(pk=submission_id)
    package = get_object_or_404(Package.objects.select_for_update(), pk=package_id)
    destination = reverse("wagtailsnippets_upload_package:inspect", args=[package.pk])
    if not package.has_interrupted_reception:
        messages.error(request, _("No interrupted processing is available to retry."))
        return redirect(destination)
    if not package.can_retry_processing(request.user):
        raise PermissionDenied
    if package.has_newer_accepted_attempt():
        messages.error(request, NEWER_DOCUMENT)
        return redirect(destination)
    if not package.file or not package.file.storage.exists(package.file.name):
        messages.error(request, _("The submitted ZIP is no longer available."))
        return redirect(destination)
    if request.method == "GET":
        return render(
            request,
            "upload/admin/package/confirm_action.html",
            {
                "title": _("Reprocess"),
                "message": _(
                    "Process the existing ZIP again without creating a new submission?"
                ),
                "submit_label": _("Yes"),
                "package": package,
                "cancel_url": destination,
            },
        )
    attempt = UploadProcResult.create(request.user, package, "Try processing")
    attempt.detail = {
        "state": "queued",
        "previous_status": package.status,
        "validation_results": list(
            package.validation_report.values(
                "id",
                "title",
                "pkg_validation_result__status",
                "pkg_validation_result__message",
                "pkg_validation_result__data",
            )
        ),
    }
    attempt.save(update_fields=["detail"])
    package.status = choices.PS_SUBMITTED
    package.updated_by = request.user
    package.save(update_fields=["status", "updated_by", "updated"])
    transaction.on_commit(
        partial(
            task_receive_packages.apply_async,
            kwargs={
                "user_id": request.user.pk,
                "pkg_zip_id": package.pkg_zip_id,
                "retry_package_id": package.pk,
            },
        )
    )
    messages.success(request, _("Processing retry scheduled."))

    return redirect(destination)
