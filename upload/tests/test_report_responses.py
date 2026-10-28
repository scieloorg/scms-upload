import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from upload import choices
from upload.models import XMLError, XMLErrorReport


def test_responses_only_save_the_filtered_page(
    report_scope, client, report_factory, result_factory
):
    report = report_factory(XMLErrorReport)
    results = [
        result_factory(
            report, XMLError, reaction=choices.ER_REACTION_FIX,
            status=choices.VALIDATION_RESULT_WARNING, message="Keep diagnostic",
        )
        for _ in range(21)
    ]
    excluded = result_factory(report, XMLError, reaction=choices.ER_REACTION_NOT_TO_FIX)
    client.force_login(report_scope.superuser)
    url = reverse("upload:xml_error_report", args=[report.pk])
    url += f"?reaction={choices.ER_REACTION_FIX}&status=WARNING&p=1"
    response = client.get(url)
    assert len(response.context["form"].fields) == 20
    assert 'id="report-responses"' in response.content.decode()
    data = {
        f"reaction_{result.pk}": choices.ER_REACTION_IMPOSSIBLE_TO_FIX
        for result in results[:20]
    }
    tampered = {**data, f"reaction_{results[-1].pk}": choices.ER_REACTION_NOT_TO_FIX}
    assert client.post(url, tampered).status_code == 400
    response = client.post(url, data)
    assert response.status_code == 302
    assert response.url == url
    for result in results[:20]:
        result.refresh_from_db()
        assert result.reaction == choices.ER_REACTION_IMPOSSIBLE_TO_FIX
        assert result.updated_by == report_scope.superuser
        assert result.status == choices.VALIDATION_RESULT_WARNING
        assert result.message == "Keep diagnostic"
    results[-1].refresh_from_db()
    excluded.refresh_from_db()
    report.refresh_from_db()
    assert results[-1].reaction == choices.ER_REACTION_FIX
    assert excluded.reaction == choices.ER_REACTION_NOT_TO_FIX
    assert report.updated_by == report_scope.superuser
    assert not report.xml_producer_ack


def test_responses_reject_tampered_ids_and_invalid_choices_atomically(
    report_scope, client, report_factory, result_factory
):
    report = report_factory(XMLErrorReport)
    result = result_factory(report, XMLError, reaction=choices.ER_REACTION_FIX)
    other = result_factory(report_factory(XMLErrorReport), XMLError)
    outside = result_factory(
        report_factory(XMLErrorReport, package=report_scope.package_2), XMLError
    )
    client.force_login(report_scope.superuser)
    url = reverse("upload:xml_error_report", args=[report.pk])
    valid = {f"reaction_{result.pk}": choices.ER_REACTION_NOT_TO_FIX}
    for extra in (other.pk, outside.pk, 999999):
        assert client.post(url, {**valid, f"reaction_{extra}": choices.ER_REACTION_FIX}).status_code == 400
    assert client.post(url, {f"reaction_{result.pk}": "forged"}).status_code == 400
    with pytest.raises(ValidationError):
        report.save_responses(
            {result.pk: choices.ER_REACTION_NOT_TO_FIX, other.pk: choices.ER_REACTION_FIX},
            report_scope.superuser,
        )
    second = result_factory(report, XMLError, reaction=choices.ER_REACTION_FIX)
    with pytest.raises(ValidationError):
        report.save_responses(
            {result.pk: choices.ER_REACTION_NOT_TO_FIX, second.pk: "forged"},
            report_scope.superuser,
        )
    second.refresh_from_db()
    assert second.reaction == choices.ER_REACTION_FIX
    result.refresh_from_db()
    assert result.reaction == choices.ER_REACTION_FIX


def test_responses_reject_wip_and_report_changed(
    report_scope, client, report_factory, result_factory, monkeypatch
):
    report = report_factory(XMLErrorReport, creation=choices.REPORT_CREATION_WIP)
    result = result_factory(report, XMLError, reaction=choices.ER_REACTION_FIX)
    client.force_login(report_scope.superuser)
    url = reverse("upload:xml_error_report", args=[report.pk])
    data = {f"reaction_{result.pk}": choices.ER_REACTION_NOT_TO_FIX}
    denied = client.post(url, data)
    assert denied.status_code == 302
    assert denied.url == reverse("wagtailadmin_home")
    result.refresh_from_db()
    assert result.reaction == choices.ER_REACTION_FIX
    report.creation = choices.REPORT_CREATION_DONE
    report.save()
    save_responses = XMLErrorReport.save_responses

    def changed(self, responses, user):
        XMLErrorReport.objects.filter(pk=self.pk).update(creation=choices.REPORT_CREATION_WIP)
        return save_responses(self, responses, user)

    monkeypatch.setattr(XMLErrorReport, "save_responses", changed)
    response = client.post(url, data)
    assert response.status_code == 409
    assert response.context["form"].non_field_errors().as_data()[0].code == "report_changed"
    result.refresh_from_db()
    assert result.reaction == choices.ER_REACTION_FIX
