from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from article.authorization import can_request_article_change
from article.choices import RCS_PENDING, RCS_RECEIVED
from article.models import RequestArticleChange
from upload import choices
from upload.authorization import user_can_act_on_package
from upload.models import Package
from upload.permission_policies import UploadModelPermissionPolicy
from upload.permissions import FINISH_DEPOSIT, PUBLISH_PACKAGE, REQUEST_CORRECTION
from upload.publication_results import (
    PUBLICATION_BLOCKED,
    PUBLICATION_FAILED,
    PUBLICATION_UNCONFIRMED,
)
from upload.querysets import get_scoped_package_queryset

DOCUMENT_SECTIONS = (
    ("overview", _("Overview")),
    ("validations", _("Validations")),
    ("files", _("Files and data")),
    ("history", _("History")),
)


def get_document_sections(package_id, active_tab):
    document_url = reverse("wagtailsnippets_upload_package:inspect", args=[package_id])
    return [
        {
            "key": key,
            "label": label,
            "url": f"{document_url}?tab={key}",
            "selected": key == active_tab,
        }
        for key, label in DOCUMENT_SECTIONS
    ]


def get_document_downloads(package):
    downloads = []
    if any(
        package.metrics.get(key)
        for key in ("total_xml_errors", "total_xml_warnings", "critical_errors")
    ):
        downloads.append(
            {
                "label": _("XML errors (CSV)"),
                "url": reverse("upload:download_errors") + f"?package_id={package.pk}",
            }
        )
    for report in package.xml_info_report.exclude(file="").order_by("pk"):
        if report.file:
            downloads.append(
                {"label": _("XML information (CSV)"), "url": report.file.url}
            )
    if package.pkg_zip_id and package.pkg_zip.file:
        downloads.append(
            {"label": _("Submitted package (ZIP)"), "url": package.pkg_zip.file.url}
        )
    try:
        document_file_available = bool(
            package.file and package.file.storage.exists(package.file.name)
        )
    except OSError:
        document_file_available = False
    if document_file_available:
        downloads.extend(
            [
                {"label": _("Document package (ZIP)"), "url": package.file.url},
                {
                    "label": _("Document XML"),
                    "url": reverse("upload:display_xml")
                    + f"?package_id={package.pk}&download=1",
                },
            ]
        )
    downloads.append(
        {
            "label": _("History (JSON)"),
            "url": reverse("upload:download_document_events", args=[package.pk]),
        }
    )

    return {
        "document_downloads": downloads,
        "document_file_available": document_file_available,
    }


def get_package_action_buttons(
    user,
    package,
    button_class,
    include_finish_deposit=False,
):
    buttons = []
    if (
        UploadModelPermissionPolicy(Package).user_has_any_permission(
            user, ("view", "change")
        )
        and can_request_article_change(user, package.article)
        and get_scoped_package_queryset(user).filter(pk=package.pk).exists()
        and not RequestArticleChange.objects.filter(
            article_id=package.article_id,
            status__in=(RCS_PENDING, RCS_RECEIVED),
        ).exists()
    ):
        buttons.append(
            button_class(
                _("Request document change"),
                icon_name="edit",
                url=reverse("upload:request_article_change", args=[package.pk]),
                priority=20,
            )
        )

    if package.can_retry_processing(user):
        originals = (
            get_scoped_package_queryset(user)
            .filter(name=package.name)
            .exclude(pk=package.pk)
            .exclude(status__in=(choices.PS_UNEXPECTED, choices.PS_ARCHIVED))
        )
        if package.article_id:
            originals = originals.filter(article_id=package.article_id)
        elif package.journal_id:
            originals = originals.filter(journal_id=package.journal_id)
        original = originals.order_by("-created", "-pk").first()
        if original and originals.values("article_id").distinct().count() == 1:
            buttons.append(
                button_class(
                    _("Open related document"),
                    icon_name="doc-full",
                    url=reverse(
                        "wagtailsnippets_upload_package:inspect", args=[original.pk]
                    ),
                    priority=34,
                )
            )
        buttons.append(
            button_class(
                _("Reprocess"),
                icon_name="rotate",
                url=reverse("upload:retry_processing") + f"?package_id={package.pk}",
                priority=35,
            )
        )

    if not package.is_validation_finished:
        return buttons

    if package.can_delegate_review(user):
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
    ) and (
        user_can_act_on_package(user, REQUEST_CORRECTION, package)
        or user_can_act_on_package(user, PUBLISH_PACKAGE, package)
    ):
        buttons.append(
            button_class(
                _("Record decision"),
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
        if user_can_act_on_package(
            user, PUBLISH_PACKAGE, package
        ) and package.publication_situation(purpose)["state"] in (
            PUBLICATION_FAILED,
            PUBLICATION_BLOCKED,
            PUBLICATION_UNCONFIRMED,
        ):
            buttons.append(
                button_class(
                    _("Retry"),
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
