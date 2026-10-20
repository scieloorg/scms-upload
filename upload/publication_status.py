from django.utils.translation import gettext_lazy as _

from upload import choices

PUBLICATION_ATTEMPT_PREFIX = "Publish article and check availability"
PUBLICATION_QUEUED = "queued"
PUBLICATION_RUNNING = "running"
PUBLICATION_FAILED = "failed"
PUBLICATION_PUBLISHED = "published"
PUBLICATION_UNRELEASED = "unreleased"
PUBLICATION_STATE_LABELS = {
    PUBLICATION_QUEUED: _("Awaiting publication"),
    PUBLICATION_RUNNING: _("Publication in progress"),
    PUBLICATION_FAILED: _("Last publication attempt failed"),
    PUBLICATION_PUBLISHED: _("Published"),
    PUBLICATION_UNRELEASED: _("Not published"),
}


def publication_situation(package, purpose):
    events = getattr(package, "publication_attempts", None)
    if events is None:
        events = package.upload_proc_result.filter(
            name__startswith=PUBLICATION_ATTEMPT_PREFIX,
        ).order_by("-created", "-pk")

    attempt = None
    for event in events:
        detail = event.detail if isinstance(event.detail, dict) else {}
        # Older attempts recorded the destinations only in their operation name.
        if purpose in detail.get("websites", []) or (
            "websites" not in detail and f"'{purpose}'" in event.name
        ):
            attempt = event
            break

    website_status = (
        package.public_ws_status if purpose == "PUBLIC" else package.qa_ws_status
    )
    state = (
        PUBLICATION_PUBLISHED
        if website_status == choices.PUBLISHED
        else PUBLICATION_UNRELEASED
    )

    if attempt:
        detail = attempt.detail if isinstance(attempt.detail, dict) else {}
        if detail.get("state"):
            state = detail["state"]
        elif any(
            result.get("website") == purpose and result.get("published")
            for result in detail.get("publication", [])
        ):
            state = PUBLICATION_PUBLISHED
        elif attempt.completed:
            state = PUBLICATION_PUBLISHED
        else:
            state = PUBLICATION_FAILED if detail else PUBLICATION_RUNNING
    elif package.status == (
        choices.PS_READY_TO_PUBLISH
        if purpose == "PUBLIC"
        else choices.PS_READY_TO_PREVIEW
    ):
        state = PUBLICATION_QUEUED

    return {
        "state": state,
        "label": PUBLICATION_STATE_LABELS[state],
        "attempt": attempt,
    }
