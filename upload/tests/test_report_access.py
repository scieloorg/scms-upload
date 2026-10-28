import pytest
from django.urls import reverse

from upload import choices
from upload.models import (
    PkgValidationResult,
    ValidationReport,
    XMLError,
    XMLErrorReport,
)


def test_report_access_respects_scope_and_review_permission(
    report_scope, client, report_case, report_factory, result_factory
):
    report_model, result_model, route = report_case
    report = report_factory(report_model)
    result = result_factory(report, result_model, status=choices.VALIDATION_RESULT_SUCCESS)
    url = reverse(f"upload:{route}", args=[report.pk])

    assert not report_scope.analyst_user.has_perm(
        f"upload.change_{report_model._meta.model_name}"
    )
    response = client.get(url)

    assert response.status_code == 200
    assert response.context["page_subtitle"] == str(report.package)
    assert response.context["breadcrumbs_items"][-1]["sublabel"] == str(report.package)
    assert response.context["results"][0]["result"].pk == result.pk
    assert response.context["package_url"] in response.content.decode()
    assert 'id="report-responses"' not in response.content.decode()
    expected_status = 302 if report_model is XMLErrorReport else 405
    assert client.post(url, {"action": "save_responses"}).status_code == expected_status
    result.refresh_from_db()

    assert result.status == choices.VALIDATION_RESULT_SUCCESS

    outside = report_factory(report_model, package=report_scope.package_2)
    assert client.get(reverse(f"upload:{route}", args=[outside.pk]), follow=True).status_code == 404

    index = client.get(
        reverse(f"wagtailsnippets_upload_{report_model._meta.model_name}:list")
    )
    assert index.status_code == 200
    assert url in index.content.decode()
    assert outside not in index.context["object_list"]

    client.force_login(report_scope.superuser)
    response = client.post(url, {f"reaction_{result.pk}": choices.ER_REACTION_FIX})
    assert response.status_code == (302 if report_model is XMLErrorReport else 405)

    client.force_login(report_scope.unrelated_user)
    denied = client.get(url)

    assert denied.status_code == 302
    assert denied.url.startswith(reverse("wagtailadmin_login"))


@pytest.mark.parametrize(
    "report_model,result_model",
    [(ValidationReport, PkgValidationResult), (XMLErrorReport, XMLError)],
)
def test_result_lookup_view_only_scope_and_package_search(
    report_scope, client, report_factory, result_factory, report_model, result_model
):
    report_scope.package_1.name = "searchable-document"
    report_scope.package_1.save()
    report = report_factory(report_model)
    result = result_factory(report, result_model, status=choices.VALIDATION_RESULT_SUCCESS)
    outside = result_factory(
        report_factory(report_model, package=report_scope.package_2),
        result_model,
        status=choices.VALIDATION_RESULT_SUCCESS,
    )
    namespace = f"wagtailsnippets_upload_{result_model._meta.model_name}"
    response = client.get(reverse(f"{namespace}:list"), {"q": "searchable-document"})

    assert response.status_code == 200
    assert list(response.context["object_list"]) == [result]
    assert client.get(reverse(f"{namespace}:inspect", args=[result.pk])).status_code == 200
    assert client.get(reverse(f"{namespace}:inspect", args=[outside.pk]), follow=True).status_code == 404


def test_existing_review_links_are_permission_gated(report_scope, client, report_factory):
    report = report_factory(XMLErrorReport)
    document_url = reverse(
        "wagtailsnippets_upload_package:inspect", args=[report_scope.package_1.pk]
    )
    review_url = reverse("upload:xml_error_report", args=[report.pk]) + "#report-responses"

    assert review_url not in client.get(document_url, {"tab": "validations"}).content.decode()

    client.force_login(report_scope.superuser)

    assert review_url in client.get(document_url, {"tab": "validations"}).content.decode()

    report.creation = choices.REPORT_CREATION_WIP
    report.save()

    assert review_url not in client.get(document_url, {"tab": "validations"}).content.decode()
