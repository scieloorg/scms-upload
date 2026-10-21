"""
Relatórios públicos, acessíveis em /report/.

Para adicionar um relatório:
1. inclua o path em urlpatterns
2. inclua uma entrada em REPORTS (aparece na página /report/)
"""
from django.shortcuts import render
from django.urls import path
from django.utils.translation import gettext_lazy as _

from article.views import data_availability_report, data_availability_report_options

REPORTS = [
    {
        "url_name": "report_data_availability",
        "title": _("Data availability"),
        "description": _(
            "Articles by data availability status per year, with totals and "
            "percentages. Filters: collection, journal and online publication date."
        ),
    },
]


def report_index(request):
    return render(request, "report/index.html", {"reports": REPORTS})


urlpatterns = [
    path("", report_index, name="report_index"),
    path(
        "data_availability",
        data_availability_report,
        name="report_data_availability",
    ),
    path(
        "data_availability/options",
        data_availability_report_options,
        name="report_data_availability_options",
    ),
]
