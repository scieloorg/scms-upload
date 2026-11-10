import os

from django.contrib import messages
from django.contrib.admin.utils import quote
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import content_disposition_header
from django.utils.translation import gettext_lazy as _
from wagtail.admin.ui.tables import TitleColumn
from wagtail.admin.widgets import Button, ListingButton
from wagtail.snippets.views.snippets import IndexView as SnippetIndexView

from core.users.permission_policies import TeamScopedInspectView
from upload.admin_buttons import (
    DOCUMENT_SECTIONS,
    get_package_action_buttons,
    get_package_website_links,
)
from upload.filters import DocumentFilterSet
from upload.models import (
    DELEGATION_EVENT,
    Package,
    PackageZip,
    PkgValidationResult,
    choices,
)
from upload.publication_status import publication_situation
from upload.querysets import (
    document_queue_filter,
    get_scoped_package_queryset,
    scope_package_queryset,
)
from upload.utils.package_utils import render_html

HISTORY_PER_PAGE = 20


HISTORY_FILTERS = {"all", "decisions", "delegations", "processing"}


EVENT_LABELS = {
    "request_article_change": _("Request document change"),
    "Package.publish on QA": _("Publication task for QA"),
    "Package.publish on PUBLIC": _("Publication task for Production"),
    "upload_article_page_to_the_cloud": _("Send article page to storage"),
    "upload_xml_to_the_cloud": _("Send XML to storage"),
    "upload_zip_content_to_the_cloud": _("Send package files to storage"),
    "save_pkg_zip_file": _("Save package file"),
    "request_pid_for_xml_zip": _("Request document identifiers"),
    "prepare to publish": _("Prepare publication"),
    "SPSPkg.create_or_update": _("Register or update SPS package"),
    "check_xml_changed": _("Check XML changes"),
    "process_system_decision": _("Record workflow decision"),
    ">>> local registration": _("Register document in Upload"),
    ">>> core registration": _("Register document in Core"),
}


QUEUE_ICONS = {
    "all": "list-ul",
    "mine": "tasks",
    "review": "edit",
    "corrections": "warning",
    "archived": "history",
}


class PackageIndexView(SnippetIndexView):
    def get_list_more_buttons(self, instance):
        buttons = super().get_list_more_buttons(instance)
        buttons.extend(
            get_package_action_buttons(
                self.request.user,
                instance,
                ListingButton,
            )
        )

        return buttons

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        base = scope_package_queryset(Package.objects.all(), self.request.user)
        params = self.request.GET.copy()
        params.pop("p", None)
        params.pop("queue", None)
        selected = self.request.GET.get("queue", "all")
        context["document_queues"] = []
        for key, label in choices.QUEUE_LABELS:
            queue_base = base
            queue_base = DocumentFilterSet(
                self.request.GET, queryset=queue_base, request=self.request
            ).qs
            params["queue"] = key
            context["document_queues"].append(
                {
                    "label": label,
                    "icon": QUEUE_ICONS[key],
                    "url": "?" + params.urlencode(),
                    "selected": key == selected
                    or (key == "all" and selected not in dict(choices.QUEUE_LABELS)),
                    "count": queue_base.filter(
                        document_queue_filter(
                            key,
                            self.request.user,
                            status=self.request.GET.get("status"),
                        )
                    ).count(),
                }
            )

        pkg_zip_id = self.request.GET.get("pkg_zip_id", "")
        if pkg_zip_id.isdecimal():
            pending_zip = PackageZip.objects.filter(
                pk=pkg_zip_id,
                creator=self.request.user,
                packages__isnull=True,
            ).exists()
            if pending_zip:
                context["no_results_message"] = _(
                    "Documents from this ZIP are not available yet. "
                    "Processing runs in the background. Refresh shortly."
                )

        return context

    def _get_title_column(self, field_name, column_class=TitleColumn, **kwargs):
        column_class = self._get_title_column_class(column_class)

        def get_url(instance):
            if inspect_url := self.get_inspect_url(instance):
                return inspect_url
            return self.get_edit_url(instance)

        kwargs.setdefault(
            "get_title_id",
            lambda instance: f"snippet_{quote(instance.pk)}_title",
        )

        if not self.model:
            return column_class(
                "name", label="Name", accessor=str, get_url=get_url, **kwargs
            )

        return self._get_custom_column(
            field_name, column_class, get_url=get_url, **kwargs
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
