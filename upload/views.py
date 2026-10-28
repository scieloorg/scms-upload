import logging
from functools import partial

from django.contrib import messages
from django.db import transaction
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.html import format_html
from django.utils.http import content_disposition_header
from django.utils.translation import gettext_lazy as _
from wagtail.snippets.views.snippets import CreateView

from collection.choices import WEBSITE_KIND
from core.users.permission_policies import TeamScopedEditView
from upload.authorization import user_can_act_on_package
from upload.models import Package, UploadProcResult, choices
from upload.permissions import (
    ASSIGN_PACKAGE,
    FINISH_DEPOSIT,
    PUBLISH_PACKAGE,
    REPUBLISH_PACKAGE,
    REQUEST_CORRECTION,
)
from upload.publication_status import (
    PUBLICATION_ATTEMPT_PREFIX,
    PUBLICATION_FAILED,
    PUBLICATION_QUEUED,
    publication_situation,
)
from upload.querysets import get_scoped_package_queryset
from upload.tasks import (
    task_receive_packages,
    task_republish_articles,
    task_upload_workflow_publish_article,
)
from upload.utils.package_utils import render_html


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
                    "Follow its progress in Document tracking."
                ),
                documents_url,
                pkg_zip.pk,
                _("View documents"),
            ),
        )

        return HttpResponseRedirect(self.get_success_url())


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


class PackageDecisionMixin:
    success_message = _("Decision recorded successfully")
    error_message = _("Unable to complete the operation. Check the form and try again.")
    permission_error_message = _("Operation not available")

    def get_success_url(self):
        return reverse("wagtailsnippets_upload_package:inspect", args=[self.object.pk])

    def get_task_function(self):
        return task_upload_workflow_publish_article

    def process_decision(self, package, user, force_journal, force_issue):
        return package.process_qa_decision(
            user, self.get_task_function(), force_journal, force_issue
        )

    def form_valid(self, form):
        decision = form.cleaned_data.get("qa_decision")
        if decision == choices.PS_PENDING_CORRECTION:
            permission = REQUEST_CORRECTION
        elif decision == choices.PS_PENDING_QA_DECISION:
            permission = ASSIGN_PACKAGE
        else:
            permission = PUBLISH_PACKAGE
        if not user_can_act_on_package(self.request.user, permission, form.instance):
            messages.error(self.request, self.permission_error_message)
            return HttpResponseRedirect(self.get_success_url())

        package = form.save_all(self.request.user)

        force_journal_publication = form.cleaned_data.get("force_journal_publication")
        if permission == PUBLISH_PACKAGE and not package.journal:
            messages.error(
                self.request,
                _(
                    "Package journal was not identified in the system or is not registered"
                ),
            )
            return HttpResponseRedirect(self.get_success_url())

        force_issue_publication = form.cleaned_data.get("force_issue_publication")
        if permission == PUBLISH_PACKAGE and not package.issue:
            messages.error(
                self.request,
                _(
                    "Package issue was not identified in the system or is not registered"
                ),
            )
            return HttpResponseRedirect(self.get_success_url())

        if self.process_decision(
            package,
            self.request.user,
            force_journal_publication,
            force_issue_publication,
        ):
            messages.success(self.request, self.success_message)
            return HttpResponseRedirect(self.get_success_url())
        messages.error(self.request, self.error_message)
        return self.form_invalid(form)


class QAPackageEditView(PackageDecisionMixin, TeamScopedEditView):
    pass


class ReadyToPublishPackageEditView(PackageDecisionMixin, TeamScopedEditView):
    pass


@transaction.atomic
def retry_publication(request):
    if not request.user.has_perm(f"upload.{PUBLISH_PACKAGE}"):
        messages.error(request, _("Operation not available"))
        return redirect("wagtailsnippets_upload_package:list")

    package_id = request.POST.get("package_id") or request.GET.get("package_id")
    package = get_object_or_404(
        Package.objects.filter(
            pk__in=get_scoped_package_queryset(request.user, PUBLISH_PACKAGE).values(
                "pk"
            ),
        ).select_for_update(),
        pk=package_id,
    )
    destination = reverse("wagtailsnippets_upload_package:inspect", args=[package.pk])
    purpose = "PUBLIC" if package.status == choices.PS_READY_TO_PUBLISH else "QA"
    if (
        package.status not in (choices.PS_READY_TO_PREVIEW, choices.PS_READY_TO_PUBLISH)
        or publication_situation(package, purpose)["state"] != PUBLICATION_FAILED
    ):
        messages.error(
            request, _("No failed publication attempt is available to retry.")
        )
        return redirect(destination)

    if request.method != "POST":
        return render(
            request,
            "upload/admin/package/confirm_action.html",
            {
                "title": _("Retry publication"),
                "message": _(
                    "Retry the failed publication using the existing authorization. "
                    "The document and its validation results will be preserved."
                ),
                "submit_label": _("Retry publication"),
                "package": package,
                "cancel_url": destination,
            },
        )

    attempt = UploadProcResult.create(
        request.user,
        package,
        f"{PUBLICATION_ATTEMPT_PREFIX} {[purpose]}",
    )
    attempt.detail = {"state": PUBLICATION_QUEUED, "websites": [purpose]}
    attempt.save(update_fields=["detail"])
    transaction.on_commit(
        partial(
            task_upload_workflow_publish_article.apply_async,
            kwargs={
                "user_id": request.user.pk,
                "username": request.user.username,
                "upload_package_id": package.pk,
                "websites": [purpose],
            },
        )
    )
    messages.success(request, _("Publication retry scheduled."))
    return redirect(destination)


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


def display_xml(request):
    package_id = request.GET.get("package_id")

    if package_id:
        package = get_object_or_404(
            get_scoped_package_queryset(request.user), pk=package_id
        )
        if request.GET.get("download") == "1":
            response = HttpResponse(
                package.xml, content_type="application/xml; charset=utf-8"
            )
            response["Content-Disposition"] = content_disposition_header(
                True,
                f"{package.package_name}.xml",
            )
            return response
        return render(
            request=request,
            template_name="modeladmin/upload/package/xml.html",
            context={"xml": package.xml},
        )

    return redirect(request.META.get("HTTP_REFERER"))


def preview_document(request):
    package_id = request.GET.get("package_id")

    if package_id:
        package = get_object_or_404(
            get_scoped_package_queryset(request.user), pk=package_id
        )
        language = request.GET.get("language")
        xml_path = request.GET.get("xml_path")

        document_html = render_html(package.file.name, xml_path, language)

        return render(
            request=request,
            template_name="modeladmin/upload/package/preview_document.html",
            context={"document": document_html, "package_status": package.status},
        )

    return redirect(request.META.get("HTTP_REFERER"))


def assign(request):
    package_id = request.GET.get("package_id")
    user = request.user

    if not user.has_perm(f"upload.{ASSIGN_PACKAGE}"):
        messages.error(request, _("You do not have permission to assign packages."))
        return redirect("wagtailsnippets_upload_package:list")

    if not package_id:
        messages.error(request, _("Package not informed"))
        return redirect("wagtailsnippets_upload_package:list")

    get_object_or_404(
        get_scoped_package_queryset(request.user, ASSIGN_PACKAGE), pk=package_id
    )

    return redirect("wagtailsnippets_upload_qapackage:edit", pk=package_id)


def archive_package(request):
    user = request.user

    if not user.has_perm("upload.change_package"):
        messages.error(request, _("You do not have permission to archive packages."))
        return redirect("wagtailsnippets_upload_package:list")

    package_id = request.POST.get("package_id") or request.GET.get("package_id")
    if not package_id:
        messages.error(request, _("Package not informed"))
        return redirect("wagtailsnippets_upload_package:list")

    package = get_object_or_404(
        get_scoped_package_queryset(request.user),
        pk=package_id,
    )

    if request.method != "POST":
        return render(
            request,
            "upload/admin/package/confirm_action.html",
            {
                "title": _("Archive package"),
                "message": _("Confirm archiving package '{}'?").format(package),
                "submit_label": _("Archive"),
                "package": package,
                "cancel_url": reverse("wagtailsnippets_upload_package:list"),
            },
        )

    if package.status == choices.PS_UNEXPECTED:
        package.status = choices.PS_ARCHIVED
        package.save()
        messages.success(request, _("Package was archived."))
    else:
        messages.warning(
            request,
            _("Unable to archive package which status = {}.").format(package.status),
        )

    return redirect("wagtailsnippets_upload_package:list")


def republish_selected(request):
    """
    Agenda republicação de um conjunto específico de pacotes selecionados na listagem.
    Os IDs dos pacotes chegam via GET (parâmetro package_ids, separados por vírgula)
    na primeira exibição do formulário, e via POST (campo oculto) na confirmação.
    """
    if not request.user.has_perm(f"upload.{REPUBLISH_PACKAGE}"):
        messages.error(request, _("Operation not available"))
        return redirect("wagtailsnippets_upload_package:list")

    if request.method == "POST":
        website_kind = request.POST.get("website_kind") or None
        package_ids_raw = request.POST.get("package_ids", "")
        package_ids = [
            int(pk) for pk in package_ids_raw.split(",") if pk.strip().isdigit()
        ]

        if not package_ids:
            messages.error(request, _("No packages selected."))
            return redirect("wagtailsnippets_upload_package:list")

        scoped_ids = set(
            get_scoped_package_queryset(request.user, REPUBLISH_PACKAGE)
            .filter(pk__in=package_ids)
            .values_list("pk", flat=True)
        )
        if scoped_ids != set(package_ids):
            messages.error(request, _("One or more packages are outside your scope."))
            return redirect("wagtailsnippets_upload_package:list")

        task_republish_articles.delay(
            username=request.user.username,
            user_id=request.user.id,
            website_kind=website_kind,
            package_ids=package_ids,
        )
        messages.success(
            request,
            _(
                "Batch republication of %(count)d package(s) scheduled for %(website)s website."
            )
            % {"count": len(package_ids), "website": website_kind or _("all")},
        )
        return redirect("wagtailsnippets_upload_package:list")

    package_ids_raw = request.GET.get("package_ids", "")
    package_ids = [pk for pk in package_ids_raw.split(",") if pk.strip().isdigit()]

    if not package_ids:
        messages.error(request, _("No packages selected."))
        return redirect("wagtailsnippets_upload_package:list")

    scoped_ids = set(
        get_scoped_package_queryset(request.user, REPUBLISH_PACKAGE)
        .filter(pk__in=package_ids)
        .values_list("pk", flat=True)
    )
    if scoped_ids != {int(pk) for pk in package_ids}:
        messages.error(request, _("One or more packages are outside your scope."))
        return redirect("wagtailsnippets_upload_package:list")

    return render(
        request,
        "upload/admin/package/republish_selected.html",
        {
            "website_kinds": WEBSITE_KIND,
            "package_ids": ",".join(package_ids),
            "package_count": len(package_ids),
        },
    )


def redirect_upload_url(request, model_name, subpath):
    url = reverse(f"wagtailsnippets_upload_{model_name}:list") + subpath
    query = request.META.get("QUERY_STRING")
    if query:
        url += "?" + query

    return redirect(url, preserve_request=request.method not in ("GET", "HEAD"))
