import os
from collections import Counter

from django.contrib import messages
from django.contrib.admin.utils import quote
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import content_disposition_header
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_GET
from wagtail.admin.ui.tables import TitleColumn
from wagtail.admin.widgets import Button, ListingButton
from wagtail.snippets.views.snippets import IndexView as SnippetIndexView

from core.users.permission_policies import TeamScopedInspectView
from upload.admin_buttons import (
    DOCUMENT_SECTIONS,
    get_document_downloads,
    get_document_sections,
    get_package_action_buttons,
    get_package_website_links,
)
from upload.filters import DocumentFilterSet
from upload.models import (
    DELEGATION_EVENT,
    BaseValidationReport,
    Package,
    PackageZip,
    PkgValidationResult,
    XMLError,
    XMLErrorReport,
    XMLInfo,
    choices,
)
from upload.permission_policies import UploadModelPermissionPolicy
from upload.publication_results import PUBLICATION_ATTEMPT_PREFIX
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

    def get_overview_context(self, decisions):
        reports = self.object.xml_error_report.all()
        return {
            "pending_review_count": reports.filter(
                creation=choices.REPORT_CREATION_DONE, xml_producer_ack=False
            ).count(),
            "completed_review_count": reports.filter(xml_producer_ack=True).count(),
            "latest_activity": decisions.first(),
            "submitted_package_filename": (
                os.path.basename(self.object.pkg_zip.file.name)
                if self.object.pkg_zip_id and self.object.pkg_zip.file
                else ""
            ),
        }

    def get_event_context(self, event, processing_in_progress=False):
        is_decision = event.name == "process_qa_decision"
        is_delegation = event.name == DELEGATION_EVENT
        detail = event.detail if isinstance(event.detail, dict) else {}
        label = (
            event.decision_display
            if is_decision
            else EVENT_LABELS.get(event.name, event.name)
        )
        if is_delegation:
            label = _("Delegate review")
        if event.name.startswith(PUBLICATION_ATTEMPT_PREFIX):
            environments = [
                str(choices.WEBSITE_ENVIRONMENT_LABELS.get(kind, kind))
                for kind in detail.get("websites", [])
            ]
            label = _("Publish and check availability")
            if environments:
                label = f"{label} · {', '.join(environments)}"

        if event.completed is True:
            state = {"kind": "success", "label": _("Task completed"), "icon": "check"}
        elif event.completed is False and (
            event.updated_by_id
            or any(
                detail.get(key)
                for key in ("exception_message", "exception_type", "traceback")
            )
        ):
            state = {
                "kind": "error",
                "label": _("Processing failed"),
                "icon": "warning",
            }
        elif (
            processing_in_progress and event.detail is None and not event.updated_by_id
        ):
            state = {"kind": "processing", "label": _("Processing"), "icon": "rotate"}
        else:
            state = {
                "kind": "neutral",
                "label": _("Status unavailable"),
                "icon": "info-circle",
            }

        return {
            "state": state,
            "is_decision": is_decision,
            "is_delegation": is_delegation,
            "previous_assignee": detail.get("previous_assignee"),
            "comment": detail.get("comment"),
            "assignee": detail.get("assignee"),
            "label": label,
            "name": event.name,
            "created": event.created,
            "creator": event.creator,
            "detail": event.detail,
        }

    def get_history_context(self, validation_in_progress):
        events = self.object.upload_proc_result.select_related("creator").order_by(
            "-created", "-pk"
        )
        latest_validation = events.filter(name="xml_data_checker").first()
        # An old unfinished record is not evidence of a currently running task.
        validation_started = (
            latest_validation.created
            if validation_in_progress
            and latest_validation is not None
            and latest_validation.completed is not True
            and latest_validation.detail is None
            and latest_validation.updated_by_id is None
            else None
        )
        history_filter = self.request.GET.get("event_type", "all")
        if history_filter not in HISTORY_FILTERS:
            history_filter = "all"
        if history_filter == "decisions":
            events = events.filter(name="process_qa_decision")
        elif history_filter == "delegations":
            events = events.filter(name=DELEGATION_EVENT)
        elif history_filter == "processing":
            events = events.exclude(name__in=("process_qa_decision", DELEGATION_EVENT))
        page = Paginator(events, HISTORY_PER_PAGE).get_page(
            self.request.GET.get("p", self.request.GET.get("page"))
        )

        return {
            "history_filter": history_filter,
            "timeline_events": [
                self.get_event_context(
                    event,
                    processing_in_progress=(
                        validation_started is not None
                        and event.created >= validation_started
                    ),
                )
                for event in page
            ],
            "page_obj": page,
            "pagination_pages": list(
                page.paginator.get_elided_page_range(
                    page.number, on_each_side=1, on_ends=1
                )
            ),
        }

    def get_validation_context(self, validation_in_progress):
        counts = Counter()
        for model in (PkgValidationResult, XMLError, XMLInfo):
            for result in (
                model.objects.filter(report__package=self.object)
                .order_by()
                .values("status")
                .annotate(total=Count("pk"))
            ):
                counts[result["status"]] += result["total"]
        return {
            "validation_total": sum(counts.values()),
            "validation_counts": [
                {"status": status.lower(), "label": label, "total": counts[status]}
                for status, label in choices.VALIDATION_RESULT_DISPLAY
                if counts[status]
            ],
            "validation_outcome": BaseValidationReport.validation_state(
                counts,
                (
                    choices.REPORT_CREATION_WIP
                    if validation_in_progress
                    else choices.REPORT_CREATION_DONE
                ),
            ),
        }

    def get_document_context(self, active_tab, decisions):
        summary = self.object.summary
        validation_in_progress = (
            self.object.status
            in (
                choices.PS_SUBMITTED,
                choices.PS_ENQUEUED_FOR_VALIDATION,
            )
            or not summary["is_validation_finished"]
        )
        data = {
            "document_identity": self.object.document_identity,
            "validation_in_progress": validation_in_progress,
            "active_tab": active_tab,
            "document_sections": get_document_sections(self.object.pk, active_tab),
            "work_situation": self.object.work_situation(),
            "qa_publication": self.object.publication_situation("QA"),
            "public_publication": self.object.publication_situation("PUBLIC"),
            "latest_decision": decisions.filter(
                detail__decision=choices.PS_PENDING_CORRECTION
            ).first(),
            "linked": self.object.linked.all(),
            "package_id": self.object.pk,
            "category": self.object.category,
            "pkg_zip_name": self.object.pkg_zip.name if self.object.pkg_zip_id else "",
            "summary": summary,
            "blocking_errors": list(
                PkgValidationResult.objects.filter(
                    report__package=self.object,
                    status=choices.VALIDATION_RESULT_BLOCKING,
                ).values_list("message", flat=True)
            ),
            "website_urls": {
                website["label"]: website["url"]
                for website in get_package_website_links(self.object)
            },
            "document_actions": get_package_action_buttons(
                self.request.user, self.object, Button, include_finish_deposit=True
            ),
        }
        data.update(get_document_downloads(self.object))

        return data

    def get_files_context(self, document_file_available):
        data = {
            "document_files": (
                self.object.files_list()["files"] if document_file_available else []
            ),
            "document_package_filename": os.path.basename(self.object.file.name or ""),
        }
        if self.object.pkg_zip_id and self.object.pkg_zip.file:
            data["submitted_package_filename"] = os.path.basename(
                self.object.pkg_zip.file.name
            )
        if document_file_available and self.request.GET.get("show_xml") == "1":
            data.update(show_xml=True, xml=self.object.xml)
        return data

    def get_context_data(self, **kwargs):
        self.page_subtitle = str(self.object)
        active_tab = self.request.GET.get("tab", "overview")
        if active_tab not in dict(DOCUMENT_SECTIONS):
            active_tab = "overview"
        decisions = (
            self.object.upload_proc_result.filter(
                name="process_qa_decision", completed=True
            )
            .select_related("creator")
            .order_by("-created", "-pk")
        )
        data = {**kwargs, **self.get_document_context(active_tab, decisions)}
        validation_in_progress = data["validation_in_progress"]

        if active_tab in ("overview", "validations"):
            data.update(self.get_validation_context(validation_in_progress))
        if active_tab == "overview":
            data.update(self.get_overview_context(decisions))
        elif active_tab == "history":
            data.update(self.get_history_context(validation_in_progress))
        elif active_tab == "validations":
            data.update(
                reports=self.object.validation_report.order_by("created", "pk"),
                xml_error_reports=self.object.xml_error_report.order_by(
                    "created", "pk"
                ),
                xml_info_reports=self.object.xml_info_report.order_by("created", "pk"),
                can_review_reports=UploadModelPermissionPolicy(
                    XMLErrorReport
                ).user_has_permission(self.request.user, "change"),
            )
        elif active_tab == "files":
            data.update(self.get_files_context(data["document_file_available"]))

        return super().get_context_data(**data)


@require_GET
def download_document_events(request, pk):
    policy = UploadModelPermissionPolicy(Package)
    if not policy.user_has_any_permission(request.user, ("view", "change")):
        raise PermissionDenied
    package = get_object_or_404(get_scoped_package_queryset(request.user), pk=pk)
    events = package.upload_proc_result.select_related("creator").order_by(
        "created", "pk"
    )
    response = JsonResponse(
        {
            "document_id": package.pk,
            "document": str(package),
            "events": [
                {
                    "id": event.pk,
                    "created": event.created,
                    "updated": event.updated,
                    "author": event.creator.get_username() if event.creator else None,
                    "name": event.name,
                    "completed": event.completed,
                    "detail": event.detail,
                }
                for event in events
            ],
        },
        json_dumps_params={"ensure_ascii": False, "indent": 2},
    )
    response["Content-Disposition"] = content_disposition_header(
        True, f"document-{package.pk}-events.json"
    )

    return response


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
