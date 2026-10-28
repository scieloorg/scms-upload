import os
from collections import Counter

from django.db.models import Count
from django.utils.translation import gettext_lazy as _
from wagtail.admin.widgets import Button

from core.users.permission_policies import TeamScopedInspectView
from upload.admin_buttons import get_package_action_buttons, get_package_website_links
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
from upload.publication_status import publication_situation

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
        validation_in_progress = self.object.status in (
            choices.PS_SUBMITTED,
            choices.PS_ENQUEUED_FOR_VALIDATION,
        ) or any(
            reports.filter(creation=choices.REPORT_CREATION_WIP).exists()
            for reports in (
                self.object.validation_report,
                self.object.xml_error_report,
                self.object.xml_info_report,
            )
        )

        data = {
            "validation_in_progress": validation_in_progress,
            "active_tab": active_tab,
            "document_sections": [
                {"key": key, "label": label, "selected": key == active_tab}
                for key, label in DOCUMENT_SECTIONS
            ],
            "work_situation": work_situation(self.object),
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

        if active_tab in ("overview", "validations"):
            counts = Counter()
            for model in (PkgValidationResult, XMLError, XMLInfo):
                for result in (
                    model.objects.filter(report__package=self.object)
                    .order_by()
                    .values("status")
                    .annotate(total=Count("pk"))
                ):
                    counts[result["status"]] += result["total"]
            data["validation_total"] = sum(counts.values())
            data["validation_counts"] = [
                {"status": status.lower(), "label": label, "total": counts[status]}
                for status, label in choices.VALIDATION_RESULT
                if counts[status]
            ]
            data["validation_outcome"] = BaseValidationReport.validation_state(
                counts,
                (
                    choices.REPORT_CREATION_WIP
                    if validation_in_progress
                    else choices.REPORT_CREATION_DONE
                ),
            )

        if active_tab == "validations":
            data.update(
                reports=self.object.validation_report.order_by("created", "pk"),
                xml_error_reports=self.object.xml_error_report.order_by("created", "pk"),
                xml_info_reports=self.object.xml_info_report.order_by("created", "pk"),
                can_review_reports=UploadModelPermissionPolicy(
                    XMLErrorReport
                ).user_has_permission(self.request.user, "change"),
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
