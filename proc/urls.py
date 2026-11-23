from django.urls import path

from htmlxml.views import RequestHtml2xmlReviewView
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
]
