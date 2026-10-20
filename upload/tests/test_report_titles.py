from types import SimpleNamespace

import pytest
from django.utils.translation import gettext, override

from upload import choices
from upload.models import Package, UploadProcResult, ValidationReport, XMLErrorReport
from upload.tasks import task_validate_assets
from upload.validation.xml_data_checker import XMLDataChecker


@pytest.mark.django_db
def test_report_is_reused_across_worker_languages_and_translated_for_display(
    django_user_model,
    monkeypatch,
):
    user = django_user_model.objects.create_user(username="depositor")
    package = Package.objects.create(creator=user)
    monkeypatch.setattr(Package, "xml_with_pre", SimpleNamespace(xmltree=None))
    checker = XMLDataChecker(package, journal=None, issue=None)
    report_ids = []
    for language in ("en", "pt-br", "es"):
        with override(language):
            expected = gettext("Assets Report")
            task_validate_assets(package.pk, "article.xml", [], [])
            report = ValidationReport.objects.get(package=package)
            checker.create_info_report()
            errors = checker.create_error_report("journal-meta")
            assert checker.info_report.title == "XML Info Report"
            assert errors.title == "XML Error Report: journal-meta"
            report_ids.append((report.pk, checker.info_report.pk, errors.pk))
            assert report.title == "Assets Report"
            assert report.data["title"] == expected
            assert expected in str(report)
    assert len(set(report_ids)) == 1


def test_xml_report_group_and_decision_snapshot_remain_unchanged():
    report = XMLErrorReport(title="XML Error Report: journal-meta")
    event = UploadProcResult(
        detail={
            "decision": choices.PS_PENDING_CORRECTION,
            "decision_label": "Solicitar correção",
            "comment": "Texto original do editor",
        }
    )
    for language in ("en", "pt-br", "es"):
        with override(language):
            assert (
                report.display_title() == f'{gettext("XML Error Report")}: journal-meta'
            )
            assert str(event.decision_display) == gettext("Request correction")
            assert event.detail["decision_label"] == "Solicitar correção"
            assert event.detail["comment"] == "Texto original do editor"
    assert report.title == "XML Error Report: journal-meta"
    assert (
        ValidationReport(title="Título personalizado").display_title()
        == "Título personalizado"
    )
