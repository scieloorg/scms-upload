from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from upload import choices

REVIEW_STATUSES = (
    choices.PS_VALIDATED_WITH_ERRORS,
    choices.PS_PENDING_QA_DECISION,
    choices.PS_PREVIEW,
)
ARCHIVED_STATUSES = (choices.PS_ARCHIVED, choices.PS_DEPUBLISHED)
QUEUE_LABELS = (
    ("all", _("All")),
    ("mine", _("My pending tasks")),
    ("review", _("In review")),
    ("corrections", _("In correction")),
    ("archived", _("Archived")),
)

WORK_STATUS_CHOICES = tuple(
    (value, _("Awaiting analysis") if value == choices.PS_PREVIEW else label)
    for value, label in choices.PACKAGE_STATUS
)
WORK_STATUS_LABELS = dict(WORK_STATUS_CHOICES)


def document_queue_filter(queue, user, status=None):
    if queue == "archived" or (queue == "all" and status in ARCHIVED_STATUSES):
        return Q(status__in=ARCHIVED_STATUSES)

    active = ~Q(status__in=ARCHIVED_STATUSES)

    if queue == "mine":
        return active & Q(
            assignee=user, status__in=(*REVIEW_STATUSES, choices.PS_PENDING_CORRECTION)
        )

    if queue == "review":
        return active & Q(status__in=REVIEW_STATUSES)

    if queue == "corrections":
        return active & Q(status=choices.PS_PENDING_CORRECTION)

    return active


def work_situation(package):
    return WORK_STATUS_LABELS.get(package.status, package.get_status_display())
