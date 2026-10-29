from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from article import choices as article_choices
from article.models import Article, RequestArticleChange
from upload import choices
from upload.models import Package, PackageZip


@pytest.fixture
def change_publication(django_user_model):
    user = django_user_model.objects.create_user(
        username="change-review", is_superuser=True, is_staff=True
    )
    article = Article.objects.create(
        creator=user, pid_v3="original-publication", status=article_choices.AS_PUBLISHED
    )
    previous = Package.objects.create(
        creator=user,
        article=article,
        name="previous",
        status=choices.PS_PUBLISHED,
        public_ws_status=choices.PUBLISHED,
    )
    submission = PackageZip.objects.create(creator=user, file="changes.zip")
    request = RequestArticleChange.request(
        user, article, "erratum", "Correct the title."
    )
    request.status = article_choices.RCS_RECEIVED
    request.submission = submission
    request.save()
    original = Package.objects.create(
        creator=user,
        article=article,
        name="original",
        pkg_zip=submission,
        category=choices.PC_ERRATUM,
        change_role=choices.CPR_ORIGINAL,
        status=choices.PS_PREVIEW,
        qa_ws_status=choices.PUBLISHED,
    )
    notice_article = Article.objects.create(creator=user, pid_v3="notice-publication")
    notice = Package.objects.create(
        creator=user,
        article=notice_article,
        name="notice",
        pkg_zip=submission,
        category=choices.PC_ERRATUM,
        change_role=choices.CPR_NOTICE,
        status=choices.PS_PREVIEW,
        qa_ws_status=choices.PUBLISHED,
    )
    original.change_requests.add(request)
    notice.change_requests.add(request)
    return SimpleNamespace(
        user=user,
        article=article,
        previous=previous,
        submission=submission,
        request=request,
        original=original,
        notice=notice,
    )


def approve(package):
    package.qa_decision = choices.PS_READY_TO_PUBLISH
    package.status = choices.PS_READY_TO_PUBLISH
    package.save(update_fields=["qa_decision", "status", "updated"])


@pytest.mark.django_db
def test_editorial_changes_never_auto_publish_from_tolerated_validation(
    change_publication,
):
    case = change_publication
    with patch.object(Package, "is_acceptable_package", True):
        assert not case.original.is_ready_to_publish
        assert not case.notice.is_ready_to_publish


@pytest.mark.django_db
def test_first_approval_waits_and_last_approval_schedules_the_pair(change_publication):
    case = change_publication
    task = SimpleNamespace(apply_async=Mock())
    case.original.qa_decision = choices.PS_READY_TO_PUBLISH
    case.original.save(update_fields=["qa_decision", "updated"])
    with patch.object(Package, "prepare_to_publish") as prepare:
        assert case.original.process_qa_decision(case.user, task)
        prepare.assert_not_called()
    case.original.refresh_from_db()
    assert case.original.status == choices.PS_READY_TO_PUBLISH
    task.apply_async.assert_not_called()

    case.notice.qa_decision = choices.PS_READY_TO_PUBLISH
    case.notice.save(update_fields=["qa_decision", "updated"])
    with patch.object(
        Package,
        "prepare_to_publish",
        return_value={
            "websites": ["PUBLIC"],
            "result": {},
            "new_status": choices.PS_READY_TO_PUBLISH,
        },
    ):
        assert case.notice.process_qa_decision(case.user, task)
    scheduled = {
        call.kwargs["kwargs"]["upload_package_id"]
        for call in task.apply_async.call_args_list
    }
    assert scheduled == {case.original.pk, case.notice.pk}
    case.previous.refresh_from_db()
    case.article.refresh_from_db()
    assert case.previous.status == choices.PS_PUBLISHED
    assert case.article.status == article_choices.AS_PUBLISHED


@pytest.mark.django_db
@pytest.mark.parametrize("invalid", ["unapproved_peer", "cancelled", "old_submission"])
def test_publication_rechecks_approval_and_request_before_external_call(
    change_publication, invalid
):
    case = change_publication
    approve(case.original)
    approve(case.notice)
    if invalid == "unapproved_peer":
        case.notice.qa_decision = choices.PS_PENDING_CORRECTION
        case.notice.save(update_fields=["qa_decision", "updated"])
    elif invalid == "cancelled":
        case.request.status = article_choices.RCS_CANCELLED
        case.request.save(update_fields=["status", "updated"])
    else:
        case.request.submission = PackageZip.objects.create(
            creator=case.user, file="replacement.zip"
        )
        case.request.save(update_fields=["submission", "updated"])
    publish = Mock(return_value={"result": "OK"})
    response = case.original.publish(
        case.user, publish, website_kind="PUBLIC", api_data={}
    )
    publish.assert_not_called()
    assert "error_type" in response
    case.original.refresh_from_db()
    assert case.original.public_ws_status != choices.PUBLISHED


@pytest.mark.django_db
def test_qa_keeps_original_state_and_request_completes_only_when_both_are_public(
    change_publication,
):
    case = change_publication
    case.original.update_publication_stage("QA", True)
    case.article.refresh_from_db()
    assert case.article.status == article_choices.AS_PUBLISHED
    case.request.refresh_from_db()
    assert case.request.status == article_choices.RCS_RECEIVED

    approve(case.original)
    approve(case.notice)
    case.original.update_publication_stage("PUBLIC", True)
    case.request.refresh_from_db()
    assert case.request.status == article_choices.RCS_RECEIVED
    case.notice.update_publication_stage("PUBLIC", True)
    case.request.refresh_from_db()
    assert case.request.status == article_choices.RCS_COMPLETED
    case.previous.refresh_from_db()
    assert case.previous.status == choices.PS_PUBLISHED


@pytest.mark.django_db
def test_multi_original_notice_requires_all_connected_documents(change_publication):
    case = change_publication
    other_article = Article.objects.create(
        creator=case.user, pid_v3="other-publication"
    )
    other_request = RequestArticleChange.objects.create(
        creator=case.user,
        article=other_article,
        change_type="erratum",
        comment="Related correction.",
        status=article_choices.RCS_RECEIVED,
        submission=case.submission,
    )
    other_original = Package.objects.create(
        creator=case.user,
        article=other_article,
        name="other-original",
        pkg_zip=case.submission,
        change_role=choices.CPR_ORIGINAL,
        status=choices.PS_PREVIEW,
    )
    other_original.change_requests.add(other_request)
    case.notice.change_requests.add(other_request)
    approve(case.original)
    approve(case.notice)
    assert not case.original.is_ready_to_publish
    approve(other_original)
    assert case.original.is_ready_to_publish
    assert set(
        case.original.change_publication_packages.values_list("pk", flat=True)
    ) == {
        case.original.pk,
        case.notice.pk,
        other_original.pk,
    }
