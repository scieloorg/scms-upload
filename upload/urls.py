from django.urls import path

from .views import (finish_deposit, preview_document, validation_report)


app_name = "upload"

urlpatterns = [
    path("preview-document", view=preview_document, name="preview_document"),
    path("validation-report", view=validation_report, name="validation_report"),
    path("finish", view=finish_deposit, name="finish_deposit"),
]
