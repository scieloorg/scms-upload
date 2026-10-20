from unittest.mock import Mock, patch

import pytest

from upload import choices
from upload.models import Package, UploadProcResult
from upload.publication_status import PUBLICATION_ATTEMPT_PREFIX, publication_situation
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
            return_value=[{"website": "PUBLIC", "published": published}],
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
def test_legacy_publication_result_is_not_overridden_by_unchecked_pages(
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
            "publication": [{"website": "QA", "published": True}],
            "availability": {"valid": False, "status": "not-checked"},
        },
    )
    assert publication_situation(package, "QA")["state"] == "published"
