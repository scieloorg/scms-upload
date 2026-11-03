from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from upload import choices
from upload.authorization import user_can_act_on_package
from upload.models import Package, UploadProcResult
from upload.permissions import ASSIGN_PACKAGE
from upload.querysets import get_scoped_package_queryset, review_assignee_queryset

DELEGATION_STATUSES = (
    choices.PS_VALIDATED_WITH_ERRORS,
    choices.PS_PENDING_QA_DECISION,
    choices.PS_PREVIEW,
)
DELEGATION_EVENT = "delegate_review"


def can_delegate_review(user, package):
    return (
        package.status in DELEGATION_STATUSES
        and user_can_act_on_package(user, ASSIGN_PACKAGE, package)
        and package.is_validation_finished
        and get_scoped_package_queryset(user, ASSIGN_PACKAGE)
        .filter(pk=package.pk)
        .exists()
    )


@transaction.atomic
def delegate_review(user, package_id, reviewer_id, instructions):
    package = (
        Package.objects.select_for_update()
        .filter(
            pk__in=get_scoped_package_queryset(user, ASSIGN_PACKAGE).values("pk"),
            pk=package_id,
        )
        .first()
    )

    if package is None:
        raise PermissionDenied
    if not can_delegate_review(user, package):
        raise PermissionDenied

    reviewer = review_assignee_queryset(package).filter(pk=reviewer_id).first()
    if reviewer is None:
        raise ValidationError(
            _("Choose an active reviewer eligible for this document.")
        )

    previous_assignee = package.assignee

    package.assignee = reviewer
    package.updated_by = user
    package.save(update_fields=["assignee", "updated_by", "updated"])

    event = UploadProcResult.create(user, package, DELEGATION_EVENT)
    event.finish(
        user,
        completed=True,
        detail={
            "previous_assignee_id": previous_assignee.pk if previous_assignee else None,
            "previous_assignee": str(previous_assignee) if previous_assignee else None,
            "assignee_id": reviewer.pk,
            "assignee": str(reviewer),
            "comment": instructions,
        },
    )

    return package
