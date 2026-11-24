from django.urls import path

from htmlxml.views import (
    CreateHtml2xmlTicketView,
    ReprocessHtml2xmlTicketView,
    RequestHtml2xmlReviewView,
)
from proc.views import GenerateProblemReportView

app_name = "proc"

urlpatterns = [
    path(
        "problem-report/generate/",
        GenerateProblemReportView.as_view(),
        name="generate_problem_report",
    ),
    path(
        "html2xml-review/request/",
        RequestHtml2xmlReviewView.as_view(),
        name="request_html2xml_review",
    ),
    path(
        "html2xml-ticket/create/",
        CreateHtml2xmlTicketView.as_view(),
        name="create_html2xml_ticket",
    ),
    path(
        "html2xml-ticket/<int:pk>/reprocess/",
        ReprocessHtml2xmlTicketView.as_view(),
        name="reprocess_html2xml_ticket",
    ),
]
