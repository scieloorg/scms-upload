from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from upload import choices
from upload.permissions import ASSIGN_PACKAGE, FINISH_DEPOSIT


def get_package_action_buttons(
    user,
    package,
    button_class,
    include_finish_deposit=False,
):
    if not package.is_validation_finished:
        return []

    buttons = []
    query = f"?package_id={package.pk}"

    if (
        include_finish_deposit
        and package.status == choices.PS_VALIDATED_WITH_ERRORS
        and user.has_perm(f"upload.{FINISH_DEPOSIT}")
    ):
        buttons.append(
            button_class(
                _("Finish deposit"),
                url=reverse("upload:finish_deposit") + query,
                priority=40,
            )
        )

    if package.status in (
        choices.PS_PENDING_QA_DECISION,
        choices.PS_VALIDATED_WITH_ERRORS,
    ) and user.has_perm(f"upload.{ASSIGN_PACKAGE}"):
        buttons.append(
            button_class(
                _("Accept / Reject the package or delegate it"),
                url=reverse("upload:assign") + query,
                priority=50,
            )
        )

    if package.status == choices.PS_UNEXPECTED and user.has_perm(
        "upload.change_package"
    ):
        buttons.append(
            button_class(
                _("Archive"),
                url=reverse("upload:archive_package") + query,
                priority=60,
            )
        )

    return buttons
