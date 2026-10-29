from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from upload import choices
from upload.authorization import user_can_act_on_package
from upload.delegation import can_delegate_review
from upload.permissions import FINISH_DEPOSIT, PUBLISH_PACKAGE, REQUEST_CORRECTION
from upload.publication_status import PUBLICATION_FAILED, publication_situation


def get_package_action_buttons(
    user,
    package,
    button_class,
    include_finish_deposit=False,
):
    if not package.is_validation_finished:
        return []

    buttons = []
    if can_delegate_review(user, package):
        buttons.append(
            button_class(
                _("Delegate review"),
                icon_name="user",
                url=reverse("upload:delegate_review", args=[package.pk]),
                priority=25,
            )
        )

    query = f"?package_id={package.pk}"
    if package.status in (
        choices.PS_PENDING_CORRECTION,
        choices.PS_PENDING_QA_DECISION,
        choices.PS_VALIDATED_WITH_ERRORS,
        choices.PS_PREVIEW,
        choices.PS_READY_TO_PREVIEW,
        choices.PS_READY_TO_PUBLISH,
        choices.PS_PUBLISHED,
    ) and user_can_act_on_package(user, REQUEST_CORRECTION, package):
        buttons.append(
            button_class(
                _("Decisions"),
                icon_name="tasks",
                url=reverse(
                    "wagtailsnippets_upload_readytopublishpackage:edit",
                    args=[package.pk],
                ),
                priority=30,
            )
        )

    if (
        include_finish_deposit
        and package.status == choices.PS_VALIDATED_WITH_ERRORS
        and user_can_act_on_package(user, FINISH_DEPOSIT, package)
    ):
        buttons.append(
            button_class(
                _("Submit validation responses"),
                icon_name="check",
                url=reverse("upload:finish_deposit") + query,
                priority=40,
            )
        )

    if package.status == choices.PS_UNEXPECTED and user.has_perm(
        "upload.change_package"
    ):
        buttons.append(
            button_class(
                _("Archive"),
                icon_name="history",
                url=reverse("upload:archive_package") + query,
                priority=60,
            )
        )

    if package.status in (choices.PS_READY_TO_PREVIEW, choices.PS_READY_TO_PUBLISH):
        purpose = "PUBLIC" if package.status == choices.PS_READY_TO_PUBLISH else "QA"
        if (
            user_can_act_on_package(user, PUBLISH_PACKAGE, package)
            and publication_situation(package, purpose)["state"] == PUBLICATION_FAILED
        ):
            buttons.append(
                button_class(
                    _("Retry publication"),
                    icon_name="rotate",
                    url=reverse("upload:retry_publication") + query,
                    priority=35,
                )
            )

    return buttons


def get_package_website_links(package):
    if not package.article_id:
        return []
    links = []
    for purpose, status in (
        ("QA", package.qa_ws_status),
        ("PUBLIC", package.public_ws_status),
    ):
        if status != choices.PUBLISHED:
            continue
        page = next(
            (
                page
                for page in package.article.pages.all()
                if page.purpose == purpose and page.fmt == "html" and page.url
            ),
            None,
        )
        if page:
            links.append({"label": purpose, "url": page.url})
    return links
