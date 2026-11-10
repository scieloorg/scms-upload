from django.urls import path

from upload.views.decisions import DelegateReviewView, assign
from upload.views.documents import archive_package, display_xml, preview_document
from upload.views.publication import republish_selected, retry_publication
from upload.views.reports import download_errors, finish_deposit

app_name = "upload"

urlpatterns = [
    path(
        "documents/<int:pk>/delegate/",
        DelegateReviewView.as_view(),
        name="delegate_review",
    ),
    path("retry-publication", view=retry_publication, name="retry_publication"),
    path("assign", view=assign, name="assign"),
    path("preview-document", view=preview_document, name="preview_document"),
    path("finish", view=finish_deposit, name="finish_deposit"),
    path("download-errors", view=download_errors, name="download_errors"),
    path("xml", view=display_xml, name="display_xml"),
    path("archive", view=archive_package, name="archive_package"),
    path("republish-selected", view=republish_selected, name="republish_selected"),
]
