from django.urls import path

from upload.models import ValidationReport, XMLErrorReport, XMLInfoReport
from upload.views.changes import RequestArticleChangeView
from upload.views.decisions import DelegateReviewView, assign
from upload.views.documents import (
    archive_package,
    display_xml,
    download_document_events,
    preview_document,
)
from upload.views.publication import republish_selected, retry_publication
from upload.views.reports import ValidationReportView, download_errors, finish_deposit
from upload.views.submissions import retry_processing

app_name = "upload"

urlpatterns = [
    path(
        "documents/<int:pk>/request-change/",
        RequestArticleChangeView.as_view(),
        name="request_article_change",
    ),
    path(
        "documents/<int:pk>/events/",
        download_document_events,
        name="download_document_events",
    ),
    path(
        "documents/<int:pk>/delegate/",
        DelegateReviewView.as_view(),
        name="delegate_review",
    ),
    path(
        "reports/xml-errors/<int:pk>/",
        ValidationReportView.as_view(model=XMLErrorReport, report_kind="xml-errors"),
        name="xml_error_report",
    ),
    path(
        "reports/package-checks/<int:pk>/",
        ValidationReportView.as_view(
            model=ValidationReport, report_kind="package-checks"
        ),
        name="package_validation_report",
    ),
    path(
        "reports/xml-information/<int:pk>/",
        ValidationReportView.as_view(
            model=XMLInfoReport, report_kind="xml-information"
        ),
        name="xml_info_report",
    ),
    path("retry-processing", view=retry_processing, name="retry_processing"),
    path("retry-publication", view=retry_publication, name="retry_publication"),
    path("assign", view=assign, name="assign"),
    path("preview-document", view=preview_document, name="preview_document"),
    path("finish", view=finish_deposit, name="finish_deposit"),
    path("download-errors", view=download_errors, name="download_errors"),
    path("xml", view=display_xml, name="display_xml"),
    path("archive", view=archive_package, name="archive_package"),
    path("republish-selected", view=republish_selected, name="republish_selected"),
]
