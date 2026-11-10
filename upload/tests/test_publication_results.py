from unittest.mock import Mock, patch

import pytest

from upload import choices
from upload.models import Package, UploadProcResult
from upload.publication_results import (
    PUBLICATION_ATTEMPT_PREFIX,
    destination_result,
    record_publication_results,
)
from upload.tasks import task_publish_article


@pytest.mark.parametrize("published", [False, True])
def test_task_records_destination_result_instead_of_celery_completion(published):
    manager = Mock()
    manager.article.is_available_on_website.return_value = {"valid": True}
    operation = Mock()

    with (
        patch("upload.tasks._get_user"),
        patch("upload.tasks.Package.objects.get", return_value=manager),
        patch("upload.tasks.UploadProcResult.create", return_value=operation),
        patch(
            "upload.tasks.publication.publish_article_on_collection_websites",
            return_value=[destination_result("PUBLIC", {"completed": published})],
        ),
    ):
        task_publish_article.run(
            user_id=1,
            username="coordinator",
            websites=["PUBLIC"],
            upload_package_id=1,
            collection_id=1,
        )
    result = operation.finish.call_args.kwargs

    assert result["completed"] is published
    assert result["detail"]["state"] == ("published" if published else "failed")


@pytest.mark.django_db
def test_republication_preserves_previous_attempts(django_user_model):
    user = django_user_model.objects.create_user(username="coordinator")
    package = Package.objects.create(creator=user)
    previous = UploadProcResult.create(user, package, "Package.publish on PUBLIC")
    running = UploadProcResult.create(
        user, package, f"{PUBLICATION_ATTEMPT_PREFIX} ['PUBLIC']"
    )

    with patch.object(Package, "update_publication_stage"):
        result = package.publish(
            user,
            Mock(return_value={"result": "OK"}),
            website_kind="PUBLIC",
            api_data={},
        )

    assert result["completed"]
    assert (
        UploadProcResult.objects.filter(pk__in=[previous.pk, running.pk]).count() == 2
    )


@pytest.mark.django_db
def test_publication_result_is_not_overridden_by_unchecked_pages(
    django_user_model,
):
    user = django_user_model.objects.create_user(username="coordinator")
    package = Package.objects.create(creator=user, qa_ws_status=choices.PUBLISHED)
    attempt = UploadProcResult.create(
        user, package, f"{PUBLICATION_ATTEMPT_PREFIX} scl ['QA']"
    )
    attempt.finish(
        user,
        completed=False,
        detail={
            "websites": ["QA"],
            "state": "published",
            "publication": record_publication_results(
                ["QA"],
                [destination_result("QA", {"completed": True})],
                {"pages": [{"purpose": "QA", "valid": False, "status": "not-checked"}]},
            ),
        },
    )

    assert package.publication_situation("QA")["is_published"]


@pytest.mark.parametrize(
    "purpose,state,published",
    [("QA", "published", True), ("PUBLIC", "failed", False)],
)
def test_document_listing_reads_state_from_previous_publication_records(
    client, report_scope, purpose, state, published
):
    scope = report_scope
    package = scope.package_1
    attempt = UploadProcResult.create(
        scope.superuser, package, f"{PUBLICATION_ATTEMPT_PREFIX} ['{purpose}']"
    )
    attempt.finish(
        scope.superuser,
        completed=published,
        detail={
            "websites": [purpose],
            "state": state,
            "publication": [
                {"website": purpose, "published": published, "completed": published}
            ],
        },
    )

    client.force_login(scope.superuser)
    response = client.get("/admin/upload/documents/")

    assert response.status_code == 200
    situation = package.publication_situation(purpose)
    assert situation["state"] == state
    assert situation["is_published"] is published


@pytest.mark.parametrize(
    "page_status,expected",
    [
        ("not-checked", "unverified"),
        ("available", "published"),
        ("valid_content", "published"),
        ("unavailable", "unavailable"),
    ],
)
def test_availability_does_not_turn_successful_publication_into_failure(
    page_status, expected
):
    result = record_publication_results(
        ["QA"],
        [destination_result("QA", {"completed": True})],
        {"pages": [{"purpose": "QA", "status": page_status, "valid": False}]},
    )[0]
    assert result["published"] is True
    assert result["state"] == expected


def test_production_precheck_does_not_overwrite_qa_publication():
    def event(destinations, responses, completed):
        return UploadProcResult(
            name="",
            created=None,
            completed=completed,
            detail={
                "websites": destinations,
                "publication": record_publication_results(
                    destinations,
                    [
                        destination_result(
                            item["website"], {"completed": item["published"]}
                        )
                        for item in responses
                    ],
                ),
            },
        )

    package = Package(
        qa_ws_status=choices.PUBLISHED,
        public_ws_status=choices.PUBLISHED,
    )
    package.publication_attempts = [
        event(["PUBLIC"], [{"website": "PUBLIC", "published": True}], True),
        event(["PUBLIC"], [{"website": "QA", "published": False}], False),
        event(["QA"], [{"website": "QA", "published": True}], True),
    ]
    for destination in ("QA", "PUBLIC"):
        situation = package.publication_situation(destination)
        assert situation["is_published"] and situation["diagnostic"] is None


def test_diagnostics_never_expose_untrusted_details():
    result = {
        "website": "QA",
        "published": False,
        "state": "unconfirmed",
        "error_category": "timeout",
        "error": "<script>private-payload</script>",
        "url": "https://private.invalid/",
        "traceback": "private-payload",
    }
    diagnostic = UploadProcResult(created=None).publication_diagnostic(result)
    assert diagnostic["reason"]
    assert all(
        value not in str(diagnostic)
        for value in ("<script>", "private-payload", "private.invalid")
    )
