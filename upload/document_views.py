import os
from collections import Counter

from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.http import content_disposition_header
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_GET
from wagtail.admin.widgets import Button

from core.users.permission_policies import TeamScopedInspectView
from upload.admin_buttons import (
    DOCUMENT_SECTIONS,
    get_document_downloads,
    get_document_sections,
    get_package_action_buttons,
    get_package_website_links,
)
from upload.delegation import DELEGATION_EVENT
from upload.document_workflow import work_situation
from upload.models import (
    BaseValidationReport,
    Package,
    PkgValidationResult,
    XMLError,
    XMLErrorReport,
    XMLInfo,
    choices,
)
from upload.permission_policies import UploadModelPermissionPolicy
from upload.publication_status import PUBLICATION_ATTEMPT_PREFIX, publication_situation
from upload.querysets import get_scoped_package_queryset

HISTORY_PER_PAGE = 20
HISTORY_FILTERS = {"all", "decisions", "delegations", "processing"}
EVENT_LABELS = {
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
        elif processing_in_progress and event.detail is None and not event.updated_by_id:
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
                for status, label in choices.VALIDATION_RESULT
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
            "work_situation": work_situation(self.object),
            "qa_publication": publication_situation(self.object, "QA"),
            "public_publication": publication_situation(self.object, "PUBLIC"),
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
                xml_error_reports=self.object.xml_error_report.order_by("created", "pk"),
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
    events = package.upload_proc_result.select_related("creator").order_by("created", "pk")
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
