import logging

from django.contrib import messages
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from wagtail.admin.widgets import Button
from wagtail.snippets.views.snippets import CreateView

from collection.choices import WEBSITE_KIND
from core.users.permission_policies import TeamScopedEditView, TeamScopedInspectView
from upload.admin_buttons import get_package_action_buttons
from upload.models import Package, PkgValidationResult, choices
from upload.permissions import (
    ASSIGN_PACKAGE,
    FINISH_DEPOSIT,
    PUBLISH_PACKAGE,
    REPUBLISH_PACKAGE,
)
from upload.querysets import get_scoped_package_queryset
from upload.tasks import (
    task_receive_packages,
    task_republish_articles,
    task_upload_workflow_publish_article,
)
from upload.utils import package_utils
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
        task_receive_packages.apply_async(
            kwargs=dict(
                user_id=self.request.user.id,
                pkg_zip_id=pkg_zip.id,
            )
        )
        if pkg_zip.show_package_validations:
            return redirect(f"/admin/snippets/upload/package/?q={pkg_zip.name}")

        return HttpResponseRedirect(self.get_success_url())


class PackageAdminInspectView(TeamScopedInspectView):
    def get_header_more_buttons(self):
        buttons = super().get_header_more_buttons()
        buttons.extend(
            get_package_action_buttons(
                self.request.user,
                self.object,
                Button,
                include_finish_deposit=self.model is Package,
            )
        )

        return sorted(buttons)

    def get_context_data(self, **kwargs):
        blocking_errors = list(
            PkgValidationResult.objects.filter(
                report__package=self.object,
                status=choices.VALIDATION_RESULT_BLOCKING,
            ).values_list("message", flat=True)
        )
        data = {
            "pkg_zip_name": self.object.pkg_zip.name,
            "linked": self.object.linked.all(),
            "validation_results": {},
            "package_id": self.object.id,
            "original_pkg": self.object.file.name,
            "status": self.object.status,
            "category": self.object.category,
            "languages": package_utils.get_languages(self.object.file.name),
            "pdfs": [],
            "reports": list(self.object.reports),
            "xml_error_reports": list(self.object.xml_error_reports),
            "xml_info_reports": list(self.object.xml_info_reports),
            "summary": self.object.summary,
            "xml": self.object.xml,
            "blocking_errors": blocking_errors,
        }

        return super().get_context_data(**data)


class XMLInfoReportEditView(TeamScopedEditView):
    def form_valid(self, form):
        form.save_all(self.request.user)

        messages.success(
            self.request,
            _("Success ..."),
        )

        return redirect(self.get_package_url())

    def get_package_url(self):
        report = self.object
        return f"/admin/snippets/upload/package/inspect/{report.package.id}/?#xi"


class ValidationReportEditView(XMLInfoReportEditView):
    def get_package_url(self):
        report = self.object
        return f"/admin/snippets/upload/package/inspect/{report.package.id}/?#vr{report.id}"


class XMLErrorReportEditView(XMLInfoReportEditView):
    def get_package_url(self):
        report = self.object
        return f"/admin/snippets/upload/package/inspect/{report.package.id}/?#xer{report.id}"


class PackageDecisionMixin:
    success_message = _("The decision was executed as planned")
    error_message = _("There was an impediment to executing the decision.")
    permission_error_message = _("Operation not available")
    required_permission = None

    def get_task_function(self):
        return task_upload_workflow_publish_article

    def process_decision(self, package, user, force_journal, force_issue):
        return package.process_qa_decision(
            user, self.get_task_function(), force_journal, force_issue
        )

    def form_valid(self, form):
        if not self.request.user.has_perm(f"upload.{self.required_permission}"):
            messages.error(self.request, self.permission_error_message)
            return HttpResponseRedirect(self.get_success_url())

        package = form.save_all(self.request.user)

        force_journal_publication = form.cleaned_data.get("force_journal_publication")
        if not package.journal:
            messages.error(
                self.request,
                _(
                    "Package journal was not identified in the system or is not registered"
                ),
            )
            return HttpResponseRedirect(self.get_success_url())

        force_issue_publication = form.cleaned_data.get("force_issue_publication")
        if not package.issue:
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
    required_permission = ASSIGN_PACKAGE


class ReadyToPublishPackageEditView(PackageDecisionMixin, TeamScopedEditView):
    required_permission = PUBLISH_PACKAGE
    success_message = _("Article successfully published")
    error_message = _("Failed to publish the article. Please try again.")


def finish_deposit(request):
    if not request.user.has_perm(f"upload.{FINISH_DEPOSIT}"):
        messages.error(request, _("Operation not available"))
        return redirect("/admin/snippets/upload/package/")

    package_id = request.POST.get("package_id") or request.GET.get("package_id")
    if not package_id:
        messages.error(request, _("Package not informed"))
        return redirect("/admin/snippets/upload/package/")

    package = get_object_or_404(
        get_scoped_package_queryset(request.user),
        pk=package_id,
    )

    if request.method != "POST":
        return render(
            request,
            "modeladmin/upload/package/confirm_action.html",
            {
                "title": _("Finish deposit"),
                "message": _("Confirm finishing the deposit for package '{}'?").format(
                    package
                ),
                "submit_label": _("Finish deposit"),
                "package": package,
                "cancel_url": (f"/admin/snippets/upload/package/inspect/{package_id}/"),
            },
        )

    if package.finish_deposit(task_upload_workflow_publish_article):
        messages.success(request, _("Package has been deposited"))
        return redirect("/admin/snippets/upload/package/")

    if not package.is_error_review_finished:
        messages.error(
            request,
            _("The XML package needs review and comment"),
        )
        return redirect(f"/admin/snippets/upload/package/inspect/{package_id}/")

    if not package.is_acceptable_package:
        messages.error(
            request,
            _("Package deposit failed due to errors"),
        )
        messages.error(
            request,
            _("Correct package based on report and resubmit"),
        )

    return redirect(f"/admin/snippets/upload/package/inspect/{package_id}/")


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
        return redirect("/admin/snippets/upload/package/")

    if not package_id:
        messages.error(request, _("Package not informed"))
        return redirect("/admin/snippets/upload/package/")

    get_object_or_404(get_scoped_package_queryset(request.user), pk=package_id)

    return redirect(f"/admin/snippets/upload/qapackage/edit/{package_id}/")


def archive_package(request):
    user = request.user

    if not user.has_perm("upload.change_package"):
        messages.error(request, _("You do not have permission to archive packages."))
        return redirect("/admin/snippets/upload/package/")

    package_id = request.POST.get("package_id") or request.GET.get("package_id")
    if not package_id:
        messages.error(request, _("Package not informed"))
        return redirect("/admin/snippets/upload/package/")

    package = get_object_or_404(
        get_scoped_package_queryset(request.user),
        pk=package_id,
    )

    if request.method != "POST":
        return render(
            request,
            "modeladmin/upload/package/confirm_action.html",
            {
                "title": _("Archive package"),
                "message": _("Confirm archiving package '{}'?").format(package),
                "submit_label": _("Archive"),
                "package": package,
                "cancel_url": "/admin/snippets/upload/package/",
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

    return redirect("/admin/snippets/upload/package/")


def republish_selected(request):
    """
    Agenda republicação de um conjunto específico de pacotes selecionados na listagem.
    Os IDs dos pacotes chegam via GET (parâmetro package_ids, separados por vírgula)
    na primeira exibição do formulário, e via POST (campo oculto) na confirmação.
    """
    if not request.user.has_perm(f"upload.{REPUBLISH_PACKAGE}"):
        messages.error(request, _("Operation not available"))
        return redirect("/admin/snippets/upload/readytopublishpackage/")

    if request.method == "POST":
        website_kind = request.POST.get("website_kind") or None
        package_ids_raw = request.POST.get("package_ids", "")
        package_ids = [
            int(pk) for pk in package_ids_raw.split(",") if pk.strip().isdigit()
        ]

        if not package_ids:
            messages.error(request, _("No packages selected."))
            return redirect("/admin/snippets/upload/readytopublishpackage/")

        scoped_ids = set(
            get_scoped_package_queryset(request.user)
            .filter(pk__in=package_ids)
            .values_list("pk", flat=True)
        )
        if scoped_ids != set(package_ids):
            messages.error(request, _("One or more packages are outside your scope."))
            return redirect("/admin/snippets/upload/readytopublishpackage/")

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
        return redirect("/admin/snippets/upload/readytopublishpackage/")

    package_ids_raw = request.GET.get("package_ids", "")
    package_ids = [pk for pk in package_ids_raw.split(",") if pk.strip().isdigit()]

    if not package_ids:
        messages.error(request, _("No packages selected."))
        return redirect("/admin/snippets/upload/readytopublishpackage/")

    scoped_ids = set(
        get_scoped_package_queryset(request.user)
        .filter(pk__in=package_ids)
        .values_list("pk", flat=True)
    )
    if scoped_ids != {int(pk) for pk in package_ids}:
        messages.error(request, _("One or more packages are outside your scope."))
        return redirect("/admin/snippets/upload/readytopublishpackage/")

    return render(
        request,
        "modeladmin/upload/package/republish_selected.html",
        {
            "website_kinds": WEBSITE_KIND,
            "package_ids": ",".join(package_ids),
            "package_count": len(package_ids),
        },
    )
