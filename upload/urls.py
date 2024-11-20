from django.urls import path

from .views import assign, download_errors, display_xml, finish_deposit, preview_document, archive_package

app_name = "upload"

urlpatterns = [
    path("assign", view=assign, name="assign"),
    path("preview-document", view=preview_document, name="preview_document"),
    path("finish", view=finish_deposit, name="finish_deposit"),
    path("download-errors", view=download_errors, name="download_errors"),
    path("xml", view=display_xml, name="display_xml"),
    path("archive", view=archive_package, name="archive_package")
]
