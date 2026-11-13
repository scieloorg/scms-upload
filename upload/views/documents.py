import os

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import content_disposition_header
from django.utils.translation import gettext_lazy as _
from wagtail.admin.widgets import Button

from core.users.permission_policies import TeamScopedInspectView
from upload.admin_buttons import get_package_action_buttons, get_package_website_links
from upload.models import DELEGATION_EVENT, Package, PkgValidationResult, choices
from upload.publication_status import publication_situation
from upload.querysets import get_scoped_package_queryset
from upload.utils.package_utils import render_html

DOCUMENT_SECTIONS = (
    ("overview", _("Overview")),
    ("validations", _("Validations")),
    ("files", _("Files and data")),
    ("history", _("History")),
)


class PackageAdminInspectView(TeamScopedInspectView):
    page_title = _("Document")

    def get_fields(self):
        if self.request.GET.get("tab") != "files":
            return []
        return [field for field in super().get_fields() if field != "file"]

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

        active_tab = self.request.GET.get("tab", "overview")
        if active_tab not in dict(DOCUMENT_SECTIONS):
            active_tab = "overview"

        history = (
            self.object.upload_proc_result.filter(
                name__in=("process_qa_decision", DELEGATION_EVENT),
                completed=True,
            )
            .select_related("creator")
            .order_by("-created", "-pk")
        )

        summary = self.object.summary
        validation_in_progress = (
            self.object.status
            in (choices.PS_SUBMITTED, choices.PS_ENQUEUED_FOR_VALIDATION)
            or not summary["is_validation_finished"]
        )

        data = {
            "validation_in_progress": validation_in_progress,
            "active_tab": active_tab,
            "document_sections": [
                {"key": key, "label": label, "selected": key == active_tab}
                for key, label in DOCUMENT_SECTIONS
            ],
            "work_situation": self.object.work_situation(),
            "qa_publication": publication_situation(self.object, "QA"),
            "public_publication": publication_situation(self.object, "PUBLIC"),
            "decision_history": history,
            "latest_decision": history.filter(
                detail__decision=choices.PS_PENDING_CORRECTION
            ).first(),
            "processing_events": self.object.upload_proc_result.exclude(
                name__in=("process_qa_decision", DELEGATION_EVENT),
            ).order_by("-created", "-pk"),
            "pkg_zip_name": self.object.pkg_zip.name if self.object.pkg_zip else "",
            "linked": self.object.linked.all(),
            "package_id": self.object.id,
            "category": self.object.category,
            "summary": summary,
            "blocking_errors": blocking_errors,
            "website_links": get_package_website_links(self.object),
            "document_actions": get_package_action_buttons(
                self.request.user,
                self.object,
                Button,
                include_finish_deposit=True,
            ),
        }

        if active_tab == "validations":
            data.update(
                reports=list(self.object.reports),
                xml_error_reports=list(self.object.xml_error_reports),
                xml_info_reports=[
                    {
                        **report.data,
                        "file_url": report.file.url if report.file else None,
                    }
                    for report in self.object.xml_info_report.all()
                ],
            )

        if active_tab == "files":
            data["document_files"] = self.object.files_list()["files"]
            data["document_package_filename"] = os.path.basename(
                self.object.file.name or ""
            )
            if self.object.pkg_zip and self.object.pkg_zip.file:
                data["submitted_package_filename"] = os.path.basename(
                    self.object.pkg_zip.file.name
                )

        if active_tab == "files" and self.request.GET.get("show_xml") == "1":
            data.update(show_xml=True, xml=self.object.xml)

        return super().get_context_data(**data)


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
