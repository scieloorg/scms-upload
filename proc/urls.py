from django.urls import path

from proc.views import GenerateProblemReportView

app_name = "proc"

urlpatterns = [
    path(
        "problem-report/generate/",
        GenerateProblemReportView.as_view(),
        name="generate_problem_report",
    ),
]
