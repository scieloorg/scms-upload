from html import unescape
from re import findall
from urllib.parse import parse_qs, urlsplit

from django.urls import reverse

from upload import choices
from upload.filters import PackageValidationResultFilterSet
from upload.models import (
    PkgValidationResult,
    ValidationReport,
    XMLError,
    XMLErrorReport,
)


def test_severity_filter_survives_pagination(client, report_factory, result_factory):
    report = report_factory(XMLErrorReport)
    for _ in range(21):
        result_factory(
            report, XMLError, status=choices.VALIDATION_RESULT_WARNING,
            reaction=choices.ER_REACTION_FIX,
        )

    result_factory(report, XMLError, status=choices.VALIDATION_RESULT_FAILURE)
    url = reverse("upload:xml_error_report", args=[report.pk])
    result_factory(
        report, XMLError, status=choices.VALIDATION_RESULT_WARNING,
        reaction=choices.ER_REACTION_NOT_TO_FIX,
    )
    params = {
        "status": choices.VALIDATION_RESULT_WARNING,
        "reaction": choices.ER_REACTION_FIX,
    }
    response = client.get(url, params)

    assert response.context["page_obj"].paginator.count == 21
    assert len(response.context["results"]) == 20
    links = findall(r'href="([^"]+)"', unescape(response.content.decode()))
    next_link = next(
        link for link in links if parse_qs(urlsplit(link).query).get("p") == ["2"]
    )
    assert parse_qs(urlsplit(next_link).query)["status"] == [params["status"]]
    assert parse_qs(urlsplit(next_link).query)["reaction"] == [params["reaction"]]

    response = client.get(url, {**params, "p": 2})

    assert len(response.context["results"]) == 1
    assert response.context["results"][0]["result"].status == choices.VALIDATION_RESULT_WARNING


def test_package_result_filters_are_scoped(report_scope, rf, report_factory, result_factory):
    report = report_factory(ValidationReport)
    outside = report_factory(ValidationReport, package=report_scope.package_2)
    expected = result_factory(report, PkgValidationResult, status=choices.VALIDATION_RESULT_WARNING)
    result_factory(report, PkgValidationResult, status=choices.VALIDATION_RESULT_SUCCESS)
    request = rf.get("/")
    request.user = report_scope.analyst_user
    filters = PackageValidationResultFilterSet(
        {"status": choices.VALIDATION_RESULT_WARNING, "report": report.pk},
        request=request,
        queryset=PkgValidationResult.objects.filter(report=report),
    )

    assert list(filters.qs) == [expected]
    assert outside not in filters.filters["report"].field.queryset
