from types import SimpleNamespace
from unittest.mock import patch

import pytest
from requests.exceptions import Timeout

from publication.api.document import publish_article
from publication.api.publication import PublicationAPI
from upload.publication_results import destination_result


@pytest.mark.parametrize(
    "failure", [Timeout("Timed out"), ValueError("Invalid response")]
)
def test_shared_publication_keeps_the_legacy_failure_contract(failure):
    article_proc = SimpleNamespace(
        issue_proc=SimpleNamespace(bundle_id="migration-bundle-id"),
        article=SimpleNamespace(position=1),
        sps_pkg=SimpleNamespace(pub_date="2026-11-10"),
    )

    with (
        patch("publication.api.document.build_article"),
        patch("publication.api.publication.post_data", side_effect=failure),
    ):
        response = publish_article(
            article_proc,
            {"token": "token", "post_data_url": "https://site.invalid/article"},
        )

    assert response["error_type"] == str(type(failure))
    assert response["error"] == str(failure)
    assert set(response) == {
        "post_data_url",
        "payload",
        "traceback",
        "error",
        "error_type",
    }
    result = destination_result("PUBLIC", response)

    assert result["published"] is False
    assert result["error_category"] == "unknown"


def test_shared_authentication_keeps_its_original_exception():
    with patch("publication.api.publication.post_data", return_value={}):
        with pytest.raises(Exception) as error:
            PublicationAPI(
                get_token_url="https://site.invalid/auth",
                username="test-user",
                enabled=True,
            )

    assert type(error.value) is Exception
    assert (
        str(error.value)
        == "Failed to get token from https://site.invalid/auth with username test-user: {}"
    )
