from django.db import models
from django.utils.translation import gettext as _


class PackageStatus(models.TextChoices):
    SUBMITTED = 1, _('Submitted')
    ENQUEUED_FOR_VALIDATION = 2, _('Enqueued for validation')
    VALIDATED_WITH_ERRORS = 3, _('Validated with errors')
    VALIDATED_WITHOUT_ERRORS = 4, _('Validated without errors')
    REJECTED = 5, _('Rejected')
    ACCEPTED = 6, _('Accepted')
    SCHEDULED_FOR_PUBLICATION = 7, _('Scheduled for publication')
    PUBLISHED = 8, _('Published')


VALIDATION_ERROR_SEVERITY = [
    ('criteria-issues', _('Criteria issues')),
    ('warning', _('Warning')),
    ('error', _('Error')),
    ('fatal-error', _('Fatal error')),
    ('blocking-error', _('Blocking error')),
]
