from io import StringIO
from unittest.mock import patch

import pytest
from django.http import Http404
from django.test import RequestFactory
from django.urls import reverse

from collection.models import Collection
from journal.models import Journal, JournalCollection, OfficialJournal
from team.management.commands.create_user_groups import Command
from team.models import CollectionTeamMember, JournalTeamMember, TeamRole
from upload import choices
from upload.models import Package, UploadProcResult
from upload.publication_status import PUBLICATION_ATTEMPT_PREFIX, publication_situation
from upload.views import retry_publication


@pytest.mark.django_db
def test_publication_failure_and_retry_keep_authorization(
    client,
    django_user_model,
    django_capture_on_commit_callbacks,
):
    Command().handle(stdout=StringIO(), sync_users=False)
    user = django_user_model.objects.create_user(username="coordinator", is_staff=True)
    official = OfficialJournal.objects.create(title="Journal", creator=user)
    journal = Journal.objects.create(
        official_journal=official, journal_acron="test", creator=user
    )
    JournalTeamMember.objects.create(
        user=user,
        journal=journal,
        role=TeamRole.MANAGER,
        is_active_member=True,
        creator=user,
    )
    collection = Collection.objects.create(acron="scl", name="Collection", creator=user)
    journal_collection = JournalCollection.objects.create(
        journal=journal,
        collection=collection,
        creator=user,
    )
    membership = CollectionTeamMember.objects.create(
        user=user,
        collection=collection,
        role=TeamRole.MANAGER,
        creator=user,
    )
    package = Package.objects.create(
        creator=user,
        journal=journal,
        status=choices.PS_READY_TO_PUBLISH,
        qa_decision=choices.PS_READY_TO_PUBLISH,
    )
    attempt = UploadProcResult.create(
        user, package, f"{PUBLICATION_ATTEMPT_PREFIX} scl ['PUBLIC']"
    )
    attempt.finish(
        user,
        completed=False,
        detail={"publication": [{"website": "QA", "published": False}]},
    )
    assert publication_situation(package, "PUBLIC")["state"] == "failed"
    client.force_login(user)
    url = reverse("upload:retry_publication")
    with patch(
        "upload.views.task_upload_workflow_publish_article.apply_async"
    ) as enqueue:
        assert client.get(url, {"package_id": package.pk}).status_code == 200
        enqueue.assert_not_called()
        with django_capture_on_commit_callbacks(execute=True):
            assert client.post(url, {"package_id": package.pk}).status_code == 302
        assert enqueue.call_args.kwargs["kwargs"]["websites"] == ["PUBLIC"]
        assert enqueue.call_count == 1
        client.post(url, {"package_id": package.pk})
        assert enqueue.call_count == 1
    package.refresh_from_db()
    assert package.qa_decision == choices.PS_READY_TO_PUBLISH
    assert package.public_ws_status == choices.UNRELEASED
    assert publication_situation(package, "PUBLIC")["state"] == "queued"
    membership.is_active_member = False
    membership.save()
    with patch(
        "upload.views.task_upload_workflow_publish_article.apply_async"
    ) as enqueue:
        client.post(url, {"package_id": package.pk})
        enqueue.assert_not_called()
        membership.is_active_member = True
        membership.save()
        journal_collection.delete()
        request = RequestFactory().post(url, {"package_id": package.pk})
        request.user = django_user_model.objects.get(pk=user.pk)
        with pytest.raises(Http404):
            retry_publication(request)
        enqueue.assert_not_called()
