from unittest.mock import Mock, patch

import pytest

from collection.choices import PUBLIC, QA
from collection.models import WebSiteConfiguration
from upload.publication import publish_article_on_collection_websites


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
            side_effect=WebSiteConfiguration.DoesNotExist
            if qa_available is None
            else None,
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
        assert responses == [{"collection": "scl", "website": QA, "published": False}]
    else:
        assert publish.call_args.args[3] == PUBLIC
        assert responses == [
            {"collection": "scl", "website": PUBLIC, "published": True}
        ]
