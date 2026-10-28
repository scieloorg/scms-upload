import pytest
from django.template import Context, Template
from django.urls import reverse
from django.utils.html import escape
from django.utils.translation import gettext

from article.models import Article, ArticleTitle
from upload import choices
from upload.models import (
    PkgValidationResult,
    ValidationReport,
    XMLError,
    XMLErrorReport,
    XMLInfoReport,
)


def test_titles_are_presentation_only():
    info = XMLInfoReport(title="XML Info Report")

    assert info.display_title() == gettext("Successful XML checks")
    assert info.title == "XML Info Report"

    custom = ValidationReport(title="Custom title: keep this group")

    assert custom.display_title() == custom.title

    errors = XMLErrorReport(title="XML Error Report: journal-meta")

    assert errors.display_title() == f'{gettext("XML Error Report")}: journal-meta'
    assert errors.title == "XML Error Report: journal-meta"
    assert errors.display_heading == gettext("Journal metadata")


def test_complete_long_text_is_saved_and_displayed(
    client, report_case, report_factory, result_factory
):
    report_model, result_model, route = report_case
    report = report_factory(report_model)
    message = "Full diagnostic <element> " * 45
    advice = "Correction guidance & context " * 45
    fields = {
        "message": message,
        "status": choices.VALIDATION_RESULT_SUCCESS,
        "data": {"apparent_line": 0, "data": {"ref_id": "ref-1"}},
    }
    if result_model is XMLError:
        fields.update(
            advice=advice, got_value="a  b", expected_value="a b", parent_id="aff1"
        )

    result = result_factory(report, result_model, **fields)
    result.refresh_from_db()

    assert result.message == message
    if result_model is XMLError:
        assert result.advice == advice

    response = client.get(reverse(f"upload:{route}", args=[report.pk]))
    html = response.content.decode()

    assert str(escape(message)) in html
    assert "<details" in html
    assert "ref-1" in html
    assert "Approximate line: 0" in html
    if result_model is XMLError:
        assert str(escape(advice)) in html
        assert "a  b" in html and "a b" in html and "aff1" in html
        assert 'name="reaction_' not in html


@pytest.mark.parametrize(
    "status,creation,kind",
    [
        (choices.VALIDATION_RESULT_WARNING, choices.REPORT_CREATION_DONE, "warning"),
        (choices.VALIDATION_RESULT_BLOCKING, choices.REPORT_CREATION_DONE, "error"),
        (choices.VALIDATION_RESULT_SUCCESS, choices.REPORT_CREATION_DONE, "success"),
        (choices.VALIDATION_RESULT_FAILURE, choices.REPORT_CREATION_WIP, "processing"),
    ],
)
def test_document_summary_matches_report(
    report_scope, client, report_factory, result_factory, status, creation, kind
):
    report = report_factory(ValidationReport, creation=creation)
    result_factory(report, PkgValidationResult, status=status)
    response = client.get(
        reverse("wagtailsnippets_upload_package:inspect", args=[report_scope.package_1.pk]),
        {"tab": "validations"},
    )

    assert response.status_code == 200
    assert response.context["validation_outcome"] == kind
    assert response.context["validation_total"] == 1
    assert response.context["reports"][0].validation_summary["state"] == kind
    assert report.validation_summary["state"] == kind
    if kind != "processing":
        assert not response.context["validation_in_progress"]

    labels = {
        "processing": gettext("Processing"),
        "error": gettext("Issues found"),
        "warning": gettext("Warnings found"),
        "success": gettext("No issues found"),
    }
    html = response.content.decode()
    if kind in ("processing", "success"):
        assert labels[kind] in html
    else:
        assert 'class="validation-count' in html
    assert 'name="reaction_' not in response.content.decode()


@pytest.mark.parametrize(
    "title", [None, '<b>Title</b> & <img src=x onerror="alert(1)">']
)
def test_document_identity_title_fallback_and_escape(report_scope, client, report_factory, title):
    package = report_scope.package_1
    package.name = "<img src=x onerror=alert(2)> & doc"
    package.journal = None
    package.issue = None
    package.article = None
    if title:
        package.article = Article.objects.create(creator=report_scope.superuser)
        ArticleTitle.objects.create(
            parent=package.article, text=title, creator=report_scope.superuser
        )

    package.save()
    report = report_factory(ValidationReport)
    client.force_login(report_scope.superuser)

    response = client.get(reverse("upload:package_validation_report", args=[report.pk]))
    identity = response.context["document_identity"]
    expected_title = "Title & " if title else package.name

    assert identity["title"] == expected_title
    assert identity["identifier"] == package.name
    assert identity["journal"] is None
    assert identity["issue"] is None
    assert identity["batch"] == package.pkg_zip.name
    html = response.content.decode()

    assert f"<h2>{escape(expected_title)}</h2>" in html
    assert "<img src=x" not in html
    assert "<b>Title</b>" not in html


def test_validation_value_formatting_preserves_empty_values_and_escapes_json():
    template = Template("{% load upload_tags %}{{ value|validation_value }}")

    assert template.render(Context({"value": None})) == gettext("Not provided")
    assert template.render(Context({"value": ""})) == gettext("Empty value")
    assert template.render(Context({"value": "a  b"})) == "a  b"

    html = template.render(Context({"value": {"tag": "<script>"}}))

    assert "&lt;script&gt;" in html
    assert "<script>" not in html
