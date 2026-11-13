from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from collection.choices import PUBLIC, QA
from collection.models import WebSiteConfiguration
from publication.api.issue import publish_issue
from publication.api.journal import publish_journal
from upload.publication import (
    ensure_published_dependency,
    publish_article_on_collection_websites,
    publish_article_on_website,
)
from upload.publication_results import destination_result

@pytest.mark.parametrize(
    "website_kinds, qa_completed, public_completed, expected",
    [
        ([QA], True, True, [(QA, True)]),
        ([QA, PUBLIC], True, True, [(QA, True), (PUBLIC, True)]),
        ([QA, PUBLIC], False, True, [(QA, False)]),
        ([QA, PUBLIC], True, False, [(QA, True), (PUBLIC, False)]),
    ],
)
def test_requested_publication_stops_on_qa_failure(
    website_kinds, qa_completed, public_completed, expected
):
    manager = Mock()
    manager.journal.missing_fields = []
    collection = Mock(acron="scl")
    results = {QA: qa_completed, PUBLIC: public_completed}

    with (
        patch("upload.publication.IssueProc.objects.filter"),
        patch(
            "upload.publication.publish_article_on_website",
            side_effect=lambda *args: {"completed": results[args[3]]},
        ) as publish,
        patch("upload.publication.WebSiteConfiguration.get") as get_qa,
    ):
        responses = publish_article_on_collection_websites(
            None, manager, collection, website_kinds, False, False
        )

    assert [(item["website"], item["published"]) for item in responses] == expected
    assert [call.args[3] for call in publish.call_args_list] == [
        website for website, _ in expected
    ]
    get_qa.assert_not_called()


@pytest.mark.parametrize("qa_available", [True, False, None])
def test_public_only_checks_existing_qa_before_publishing(qa_available):
    manager = Mock()
    manager.journal.missing_fields = []
    collection = Mock(acron="scl")

    with (
        patch("upload.publication.IssueProc.objects.filter"),
        patch(
            "upload.publication.WebSiteConfiguration.get",
            side_effect=(
                WebSiteConfiguration.DoesNotExist if qa_available is None else None
            ),
        ),
        patch(
            "upload.publication.check_article_is_published", return_value=qa_available
        ),
        patch(
            "upload.publication.publish_article_on_website",
            return_value={"completed": True},
        ) as publish,
    ):
        responses = publish_article_on_collection_websites(
            None, manager, collection, [PUBLIC], False, False
        )

    if qa_available is False:
        publish.assert_not_called()
        assert responses == [destination_result(QA, {"completed": False}, "scl")]
    else:
        assert publish.call_args.args[3] == PUBLIC
        assert len(responses) == 1
        assert responses[0]["website"] == PUBLIC
        assert responses[0]["published"] is True
        assert responses[0]["state"] == "published"


@pytest.mark.parametrize(
    "content_type,script", [("journal", "sci_serial"), ("issue", "sci_issuetoc")]
)
def test_existing_dependency_is_checked_before_publishing(content_type, script):
    manager = Mock(pid="dependency-pid")
    website = Mock(url="https://site.invalid", purpose=QA)

    with patch("upload.publication.fetch_data", return_value=b"existing") as fetch:
        response = ensure_published_dependency(manager, website, None, {}, content_type)

    fetch.assert_called_once_with(
        f"https://site.invalid/scielo.php?pid=dependency-pid&script={script}"
    )
    manager.publish.assert_not_called()
    assert response["published"] is True


@pytest.mark.parametrize(
    "content_type,publisher", [("journal", publish_journal), ("issue", publish_issue)]
)
@pytest.mark.parametrize("force_update", [False, True])
@pytest.mark.parametrize("lookup", ["exception", "empty"])
def test_dependency_uses_the_correct_publisher_after_lookup_failure_or_force(
    content_type, publisher, force_update, lookup
):
    manager = Mock()
    manager.publish.return_value = {"completed": True}
    website = Mock(purpose=QA)
    user = Mock()
    api_data = {"destination": content_type}

    with patch(
        "upload.publication.fetch_data",
        side_effect=OSError("Unavailable") if lookup == "exception" else None,
        return_value=b"",
    ) as fetch:
        response = ensure_published_dependency(
            manager, website, user, api_data, content_type, force_update
        )

    assert fetch.call_count == (0 if force_update else 1)
    manager.publish.assert_called_once_with(
        user,
        publisher,
        website_kind=QA,
        api_data=api_data,
        force_update=True,
        content_type=content_type,
    )
    assert response["published"] is True


@pytest.mark.parametrize("content_type", ["journal", "issue"])
@pytest.mark.parametrize("failure", ["rejected", "empty", "exception"])
def test_dependency_failure_stays_unsuccessful(content_type, failure):
    manager = Mock()
    if failure == "exception":
        manager.publish.side_effect = RuntimeError("Publication unavailable")
    else:
        manager.publish.return_value = (
            {"completed": False, "error": "Rejected"} if failure == "rejected" else None
        )

    response = ensure_published_dependency(
        manager, Mock(purpose=QA), None, {}, content_type, force_update=True
    )

    assert not response.get("published")
    assert response["error"]
    if failure == "rejected":
        assert response["error"] == "Rejected"


@pytest.mark.parametrize("authenticated", [True, False])
def test_upload_authenticates_once_and_handles_legacy_authentication_failure(
    authenticated,
):
    website = SimpleNamespace(
        enabled=True,
        purpose=QA,
        api_url_article="article",
        api_url_journal="journal",
        api_url_issue="issue",
        api_get_token_url="auth",
        api_username="user",
        api_password="password",
    )
    manager = Mock()
    manager.publish.return_value = {"completed": True}
    issue = Mock(collection="scl")

    with (
        patch("upload.publication.WebSiteConfiguration.get", return_value=website),
        patch(
            "publication.api.publication.post_data",
            return_value={"token": "token"} if authenticated else {},
        ) as authenticate,
        patch(
            "upload.publication.ensure_published_dependency",
            return_value={"published": True},
        ),
    ):
        response = publish_article_on_website(None, manager, issue, QA)

    assert authenticate.call_count == 1
    if authenticated:
        assert response["completed"] is True
    else:
        manager.publish.assert_not_called()
        assert response["stage"] == "authentication"
        assert response["error_category"] == "authentication"


@pytest.mark.parametrize("failed_stage", ["journal", "issue"])
def test_dependency_rejection_stops_article_publication_without_replacing_its_error(
    failed_stage,
):
    manager = Mock()
    api = Mock()
    api.data = {}
    failure = {
        "published": False,
        "error": "Rejected",
        "error_category": "data",
        "status_code": 422,
    }
    responses = (
        [failure] if failed_stage == "journal" else [{"published": True}, failure]
    )

    with (
        patch("upload.publication.WebSiteConfiguration.get"),
        patch("upload.publication.PublicationAPI", return_value=api),
        patch(
            "upload.publication.ensure_published_dependency", side_effect=responses
        ) as publish,
    ):
        response = publish_article_on_website(None, manager, Mock(), QA)

    manager.publish.assert_not_called()
    assert response == {**failure, "stage": failed_stage}
    assert publish.call_count == len(responses)
    manager.start.return_value.finish.assert_called_once_with(
        None, completed=False, detail=responses
    )
