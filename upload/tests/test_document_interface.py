import pytest
from django.urls import reverse

from upload import choices
from upload.delegation import DELEGATION_EVENT
from upload.models import UploadProcResult, XMLErrorReport


def document_url(package, tab="overview"):
    return (
        reverse("wagtailsnippets_upload_package:inspect", args=[package.pk])
        + f"?tab={tab}"
    )


@pytest.mark.django_db
def test_overview_review_counts_and_shared_navigation(
    client, report_scope, report_factory
):
    report_factory(XMLErrorReport)
    completed = report_factory(XMLErrorReport)
    completed.xml_producer_ack = True
    completed.save()
    report_factory(XMLErrorReport, creation=choices.REPORT_CREATION_NONE)
    decision = UploadProcResult.objects.create(
        proc=report_scope.package_1,
        creator=report_scope.superuser,
        name="process_qa_decision",
        completed=True,
        detail={
            "decision": choices.PS_PENDING_CORRECTION,
            "comment": "Correct references",
        },
    )
    response = client.get(document_url(report_scope.package_1))
    assert response.status_code == 200
    assert response.context["pending_review_count"] == 1
    assert response.context["completed_review_count"] == 1
    assert response.context["latest_activity"] == decision
    sections = response.context["document_sections"]
    assert [section["key"] for section in sections] == [
        "overview",
        "validations",
        "files",
        "history",
    ]
    assert sections[0]["selected"]
    assert all(section["url"] for section in sections)


@pytest.mark.django_db
def test_history_filters_pagination_and_old_unfinished_events(client, report_scope):
    package = report_scope.package_1
    old = UploadProcResult.objects.create(
        proc=package,
        creator=report_scope.superuser,
        name="save_pkg_zip_file",
        completed=False,
    )
    for index in range(21):
        UploadProcResult.objects.create(
            proc=package,
            creator=report_scope.superuser,
            name=f"processing-{index}",
            completed=True,
        )
    UploadProcResult.objects.create(
        proc=package,
        creator=report_scope.superuser,
        name=DELEGATION_EVENT,
        completed=True,
        detail={"assignee": "Reviewer"},
    )
    UploadProcResult.objects.create(
        proc=package,
        creator=report_scope.superuser,
        name="process_qa_decision",
        completed=True,
        detail={"decision": choices.PS_PENDING_CORRECTION},
    )
    url = document_url(package, "history")
    response = client.get(url + "&event_type=processing")
    assert response.status_code == 200
    assert response.context["page_obj"].paginator.count == 22
    assert len(response.context["timeline_events"]) == 20
    assert response.context["timeline_events"][0]["state"]["label"] != "No issues found"
    response = client.get(url + "&event_type=processing&p=2")
    assert response.context["page_obj"].number == 2
    event = next(
        item for item in response.context["timeline_events"] if item["name"] == old.name
    )
    assert event["state"]["kind"] == "neutral"
    for event_type in ("decisions", "delegations"):
        response = client.get(url + f"&event_type={event_type}")
        assert response.context["page_obj"].paginator.count == 1
    response = client.get(url + "&event_type=invalid")
    assert response.context["history_filter"] == "all"


@pytest.mark.django_db
def test_history_json_is_get_only_and_scoped(client, report_scope):
    package = report_scope.package_1
    event = UploadProcResult.objects.create(
        proc=package,
        creator=report_scope.superuser,
        name="save_pkg_zip_file",
        completed=True,
        detail={"message": "conteúdo"},
    )
    url = reverse("upload:download_document_events", args=[package.pk])
    response = client.get(url)
    assert response.status_code == 200
    assert response.json()["document_id"] == package.pk
    assert response.json()["events"][0]["id"] == event.pk
    assert (
        response["Content-Disposition"]
        == f'attachment; filename="document-{package.pk}-events.json"'
    )
    assert client.post(url).status_code == 405
    outside = reverse(
        "upload:download_document_events", args=[report_scope.package_2.pk]
    )
    assert client.get(outside, follow=True).status_code == 404
    client.force_login(report_scope.unrelated_user)
    denied = client.get(url)
    assert denied.status_code == 302
    assert denied.url.startswith(reverse("wagtailadmin_home"))


@pytest.mark.django_db
def test_missing_document_zip_does_not_open_files_or_xml(
    client, report_scope, monkeypatch
):
    package = report_scope.package_1
    package.file = "missing/document.zip"
    package.save(update_fields=["file"])

    def must_not_open(*args, **kwargs):
        pytest.fail("An unavailable document ZIP must not be opened")

    monkeypatch.setattr(type(package), "files_list", must_not_open)
    monkeypatch.setattr(type(package), "xml", property(must_not_open))
    response = client.get(document_url(package, "files") + "&show_xml=1")
    assert response.status_code == 200
    assert response.context["document_file_available"] is False
    assert response.context["document_files"] == []
    assert not response.context.get("show_xml")
    downloads = response.context["document_downloads"]
    assert any(
        item["url"] == reverse("upload:download_document_events", args=[package.pk])
        for item in downloads
    )
    assert all("download=1" not in item["url"] for item in downloads)
