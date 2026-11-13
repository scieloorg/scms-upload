"""Editorial links, grouped approvals, and coordinated reception retries."""

from unittest.mock import Mock, patch

import pytest
from django.core.exceptions import ValidationError
from django.http import Http404
from django.test import RequestFactory
from django.utils.translation import gettext
from lxml import etree

from article import choices as article_choices
from article.models import Article, RequestArticleChange
from upload import choices
from upload.models import Package, PackageZip
from upload.tasks import task_receive_packages
from upload.validation.article_changes import validate_change_pair
from upload.views.submissions import retry_processing


@pytest.mark.parametrize("public_fails_once", [False, True])
def test_approved_editorial_group_survives_qa_and_publication_retry(
    editorial_pair, public_fails_once
):
    case = editorial_pair
    case.notice.article = Article.objects.create(
        creator=case.user, journal=case.original.journal
    )
    case.notice.save(update_fields=["article"])
    members = (case.original, case.notice)
    Package.objects.filter(pk__in=[member.pk for member in members]).update(
        status=choices.PS_READY_TO_PUBLISH,
        qa_decision=choices.PS_READY_TO_PUBLISH,
    )
    for member in members:
        member.refresh_from_db()
        transport = Mock(return_value={"result": "OK"})
        assert member.publish(
            case.user, transport, website_kind="QA", api_data={}
        )["completed"]
        member.refresh_from_db()
        assert member.status == choices.PS_READY_TO_PUBLISH
        assert member.qa_ws_status == choices.PUBLISHED
        member.validate_change_publication()
        if public_fails_once:
            transport.return_value = {"result": "ERROR"}
            assert not member.publish(
                case.user, transport, website_kind="PUBLIC", api_data={}
            )["completed"]
            member.refresh_from_db()
            assert member.status == choices.PS_READY_TO_PUBLISH
            transport.return_value = {"result": "OK"}
        assert member.publish(
            case.user, transport, website_kind="PUBLIC", api_data={}
        )["completed"]
    change = case.original.change_requests.get()
    assert change.status == article_choices.RCS_COMPLETED
    # Republishing QA must not revoke a completed group's approval either.
    case.original.update_publication_stage("QA", True)
    case.original.refresh_from_db()
    assert case.original.status == choices.PS_PUBLISHED
    case.original.validate_change_publication()


@pytest.mark.parametrize("missing_approval", ["decision", "status"])
def test_qa_success_does_not_approve_an_editorial_member(
    editorial_pair, missing_approval
):
    case = editorial_pair
    Package.objects.filter(pk__in=[case.original.pk, case.notice.pk]).update(
        status=choices.PS_READY_TO_PUBLISH,
        qa_decision=choices.PS_READY_TO_PUBLISH,
    )
    field = "qa_decision" if missing_approval == "decision" else "status"
    Package.objects.filter(pk=case.original.pk).update(**{field: choices.PS_PREVIEW})
    case.original.refresh_from_db()
    case.original.update_publication_stage("QA", True)
    case.original.refresh_from_db()
    assert case.original.status == choices.PS_PREVIEW
    with pytest.raises(ValidationError):
        case.original.validate_change_publication()


def test_ordinary_qa_publication_keeps_existing_transition(report_scope):
    package = report_scope.package_1
    package.article = Article.objects.create(
        creator=package.creator, journal=package.journal
    )
    package.status = choices.PS_READY_TO_PUBLISH
    package.qa_decision = choices.PS_READY_TO_PUBLISH
    package.save()
    package.update_publication_stage("QA", True)
    package.refresh_from_db()
    assert package.status == choices.PS_PREVIEW
    assert package.qa_ws_status == choices.PUBLISHED


def retry_request(user, package):
    request = RequestFactory().post("/retry/", {"package_id": package.pk})
    request.user, request._messages = user, Mock()
    return request


def test_retry_requires_scope_and_enqueues_pair_only_after_commit(
    editorial_pair, django_capture_on_commit_callbacks
):
    case = editorial_pair
    with pytest.raises(Http404):
        retry_processing(retry_request(case.outsider, case.original))
    with patch("upload.views.submissions.task_receive_packages.apply_async") as prepare:
        with django_capture_on_commit_callbacks(execute=True):
            assert (
                retry_processing(retry_request(case.user, case.original)).status_code
                == 302
            )
            prepare.assert_not_called()
        prepare.assert_called_once()
        retry_processing(retry_request(case.user, case.original))
        assert prepare.call_count == 1
        with patch("upload.controller.prepare_change_requests"), patch(
            "upload.tasks.task_receive_package.apply_async"
        ) as enqueue, django_capture_on_commit_callbacks(execute=True):
            task_receive_packages.run(**prepare.call_args.kwargs["kwargs"])
        assert {call.kwargs["kwargs"]["pkg_id"] for call in enqueue.call_args_list} == {
            case.original.pk,
            case.notice.pk,
        }
        assert case.original.upload_proc_result.filter(pk=case.history.pk).exists()


def test_invalid_sibling_prevents_partial_retry(
    editorial_pair, django_capture_on_commit_callbacks
):
    case = editorial_pair
    case.notice.file = ""
    case.notice.save(update_fields=["file"])

    with patch("upload.views.submissions.task_receive_packages.apply_async") as prepare:
        with django_capture_on_commit_callbacks(execute=True):
            assert (
                retry_processing(retry_request(case.user, case.original)).status_code
                == 302
            )
        with patch("upload.controller.prepare_change_requests"), patch(
            "upload.tasks.task_receive_package.apply_async"
        ) as enqueue, django_capture_on_commit_callbacks(execute=True):
            task_receive_packages.run(**prepare.call_args.kwargs["kwargs"])

    enqueue.assert_not_called()
    for member in (case.original, case.notice):
        member.refresh_from_db()
        assert member.status == choices.PS_UNEXPECTED

    assert case.original.upload_proc_result.filter(pk=case.history.pk).exists()
    assert (
        case.original.upload_proc_result.get(name="Try processing").detail["state"]
        == "failed"
    )


@pytest.mark.parametrize(
    "change_type,notice_type,forward,reverse",
    [
        ("erratum", "correction", "correction-forward", "corrected-article"),
        ("addendum", "addendum", "addendum", "addended-article"),
        ("retraction", "retraction", "retraction-forward", "retracted-article"),
        (
            "partial-retraction",
            "partial-retraction",
            "partial-retraction",
            "retracted-article",
        ),
    ],
)
def test_editorial_pair_checks_links_without_rejecting_changed_content(
    change_type, notice_type, forward, reverse
):
    original = etree.fromstring(
        (
            '<article xmlns:xlink="http://www.w3.org/1999/xlink" xml:lang="pt" article-type="research-article">'
            '<front><article-meta><article-id pub-id-type="doi">10.1234/original</article-id>'
            f'<related-article related-article-type="{forward}" ext-link-type="doi" xlink:href="10.1234/notice"/>'
            "</article-meta></front><body><p>Revised content and authorship.</p></body></article>"
        ).encode()
    )
    notice = etree.fromstring(
        (
            f'<article xmlns:xlink="http://www.w3.org/1999/xlink" xml:lang="pt" article-type="{notice_type}">'
            '<front><article-meta><article-id pub-id-type="doi">10.1234/notice</article-id>'
            f'<related-article related-article-type="{reverse}" ext-link-type="doi" xlink:href="10.1234/original"/>'
            "</article-meta></front><body><p>Notice text.</p></body></article>"
        ).encode()
    )
    validate_change_pair(change_type, original, notice)
    notice.find("front/article-meta/related-article").set(
        "{http://www.w3.org/1999/xlink}href", "10.1234/unrelated"
    )

    with pytest.raises(ValidationError) as error:
        validate_change_pair(change_type, original, notice)

    assert error.value.code == "missing_relationship"


@pytest.mark.parametrize("missing_approval", ["decision", "status"])
def test_group_approval_includes_originals_connected_through_shared_notices(
    editorial_pair, missing_approval
):
    case = editorial_pair
    submission = case.original.pkg_zip
    originals = [case.original]
    notice = case.notice
    for index in range(2):
        article = Article.objects.create(
            creator=case.user, journal=case.original.journal
        )
        original = Package.objects.create(
            creator=case.user,
            pkg_zip=submission,
            article=article,
            change_role=choices.CPR_ORIGINAL,
        )
        change = RequestArticleChange.objects.create(
            creator=case.user,
            article=article,
            submission=submission,
            change_type=article_choices.RCT_ERRATUM,
            status=article_choices.RCS_RECEIVED,
            was_public=True,
        )
        original.change_requests.add(change)
        notice.change_requests.add(change)
        originals.append(original)
        if index == 0:
            notice = Package.objects.create(
                creator=case.user,
                pkg_zip=submission,
                change_role=choices.CPR_NOTICE,
            )
            notice.change_requests.add(change)

    members = {case.original.pk, case.notice.pk, notice.pk, *(p.pk for p in originals)}
    Package.objects.filter(pk__in=members).update(
        status=choices.PS_READY_TO_PUBLISH,
        qa_decision=choices.PS_READY_TO_PUBLISH,
    )
    field = "qa_decision" if missing_approval == "decision" else "status"
    Package.objects.filter(pk=originals[-1].pk).update(**{field: choices.PS_PREVIEW})

    for original in originals:
        assert (
            set(original.change_publication_packages.values_list("pk", flat=True))
            == members
        )
        assert not original.is_ready_to_publish
        with pytest.raises(ValidationError) as error:
            original.validate_change_publication()

        assert error.value.messages == [
            gettext(
                "Approve the notice and all updated originals before publication in Production."
            )
        ]

    Package.objects.filter(pk=originals[-1].pk).update(
        **{field: choices.PS_READY_TO_PUBLISH}
    )
    for original in originals:
        assert original.is_ready_to_publish
        original.validate_change_publication()


@pytest.mark.parametrize(
    "previous_status", [choices.PS_SUBMITTED, choices.PS_PREVIEW, choices.PS_PUBLISHED]
)
def test_active_request_cannot_move_from_a_submission_in_progress(
    report_scope, previous_status
):
    scope = report_scope
    article = Article.objects.create(creator=scope.superuser, journal=scope.journal_1)
    change = RequestArticleChange.objects.create(
        creator=scope.superuser,
        article=article,
        submission=scope.pkg_zip_1,
        change_type=article_choices.RCT_ERRATUM,
        status=article_choices.RCS_RECEIVED,
    )
    scope.package_1.change_requests.add(change)
    Package.objects.filter(pk=scope.package_1.pk).update(status=previous_status)
    replacement = PackageZip.objects.create(creator=scope.company_user)

    with pytest.raises(ValidationError) as error:
        RequestArticleChange.active_for_submission(article, replacement)

    assert error.value.messages == [
        gettext("This change request already has a submission in progress.")
    ]

    change.refresh_from_db()

    assert change.submission_id == scope.pkg_zip_1.pk


def test_failed_submission_can_be_replaced_and_received_idempotently(report_scope):
    scope = report_scope
    article = Article.objects.create(creator=scope.superuser, journal=scope.journal_1)
    change = RequestArticleChange.objects.create(
        creator=scope.superuser,
        article=article,
        submission=scope.pkg_zip_1,
        change_type=article_choices.RCT_UPDATE,
        status=article_choices.RCS_RECEIVED,
    )
    scope.package_1.change_requests.add(change)
    Package.objects.filter(pk=scope.package_1.pk).update(status=choices.PS_UNEXPECTED)
    replacement = PackageZip.objects.create(creator=scope.company_user)
    package = Package.objects.create(creator=scope.company_user, pkg_zip=replacement)

    received = RequestArticleChange.active_for_submission(article, replacement)
    received.receive_submission(scope.company_user, replacement)
    package.bind_change_request(received, choices.CPR_ORIGINAL)
    received.refresh_from_db()
    updated = received.updated
    received.receive_submission(scope.company_user, replacement)
    received.refresh_from_db()
    package.refresh_from_db()

    assert received.submission_id == replacement.pk
    assert received.status == article_choices.RCS_RECEIVED
    assert received.was_public
    assert received.updated == updated
    assert package.article_id == article.pk
    assert package.category == article_choices.RCT_UPDATE
    assert package.change_requests.get() == received
