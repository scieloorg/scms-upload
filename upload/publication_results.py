"""The recorded contract for each requested publication destination."""

from requests.exceptions import ConnectionError, Timeout

from article.choices import (
    ARTICLE_WEBPAGE_STATUS_CONTENT_MISMATCH,
    ARTICLE_WEBPAGE_STATUS_NOT_CHECKED,
    ARTICLE_WEBPAGE_STATUS_UNAVAILABLE,
)

PUBLICATION_ATTEMPT_PREFIX = "Publish article and check availability"
PUBLICATION_QUEUED = "queued"
PUBLICATION_RUNNING = "running"
PUBLICATION_FAILED = "failed"
PUBLICATION_PUBLISHED = "published"
PUBLICATION_UNRELEASED = "unreleased"
PUBLICATION_UNCONFIRMED = "unconfirmed"
PUBLICATION_UNAVAILABLE = "unavailable"
PUBLICATION_UNVERIFIED = "unverified"
PUBLICATION_BLOCKED = "blocked"


def publication_http_error_category(status):
    if not isinstance(status, int) or isinstance(status, bool):
        return "unknown"
    return {
        401: "authentication",
        403: "authentication",
        400: "data",
        422: "data",
        409: "conflict",
    }.get(status, "service" if status >= 500 else "unknown")


def publication_error_metadata(error):
    """Classify exceptions at the integration boundary, before recording results."""
    metadata = {"error_category": "unknown"}
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        response = getattr(error, "response", None)
        status = getattr(response, "status_code", None) or getattr(
            error, "status_code", None
        )
        if isinstance(status, int) and 100 <= status <= 599:
            metadata["status_code"] = status
            metadata["error_category"] = publication_http_error_category(status)
        if isinstance(error, (Timeout, TimeoutError)):
            metadata["error_category"] = "timeout"
        elif isinstance(error, ConnectionError):
            metadata["error_category"] = "connection"
        error = error.__cause__ or error.__context__

    return metadata


def destination_result(purpose, response, collection=None):
    published = bool(response.get("completed"))
    category = response.get("error_category") or publication_http_error_category(
        response.get("status_code")
    )
    state = PUBLICATION_PUBLISHED if published else PUBLICATION_FAILED
    if not published and category == "timeout":
        state = PUBLICATION_UNCONFIRMED

    return {
        "website": purpose,
        "collection": collection,
        "published": published,
        "state": state,
        "stage": response.get("stage", "article"),
        "error_category": category,
        "status_code": response.get("status_code"),
    }


def record_publication_results(websites, responses, availability=None):
    """Complete requested destinations, including Production blocked by QA."""
    by_destination = {item["website"]: item for item in responses}
    pages = (availability or {}).get("pages", [])
    results = []
    for purpose in websites:
        result = by_destination.get(purpose)
        if result is None:
            result = {
                "website": purpose,
                "published": False,
                "state": PUBLICATION_BLOCKED,
                "stage": "article",
                "error_category": "qa_required",
            }
        else:
            result = dict(result)
        if result["published"]:
            destination_pages = [page for page in pages if page["purpose"] == purpose]
            checked = [
                page
                for page in destination_pages
                if page["status"] != ARTICLE_WEBPAGE_STATUS_NOT_CHECKED
            ]
            if any(
                page["status"]
                in (
                    ARTICLE_WEBPAGE_STATUS_UNAVAILABLE,
                    ARTICLE_WEBPAGE_STATUS_CONTENT_MISMATCH,
                )
                for page in checked
            ):
                result["state"] = PUBLICATION_UNAVAILABLE
            elif not checked or len(checked) != len(destination_pages):
                result["state"] = PUBLICATION_UNVERIFIED
        results.append(result)

    return results
