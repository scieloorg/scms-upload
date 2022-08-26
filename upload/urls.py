from django.urls import path

from .views import (error_resolution, ajx_error_resolution, finish_deposit, preview_document, validation_report)


app_name = "upload"

urlpatterns = [
    path("ajx-error-resolution/", view=ajx_error_resolution, name="ajx_error_resolution"),
    path("error-resolution", view=error_resolution, name="error_resolution"),
    path("preview-document", view=preview_document, name="preview_document"),
    path("validation-report", view=validation_report, name="validation_report"),
    path("finish", view=finish_deposit, name="finish_deposit"),
]
