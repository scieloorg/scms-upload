from django.db import models
from django.utils.translation import gettext as _


class PackageStatus(models.TextChoices):
    SUBMITTED = 1, _('Submitted')
    ACCEPTED = 2, _('Accepted')
    ENQUEUED_FOR_VALIDATION = 3, _('Enqueued for validation')
    VALIDATED_WITHOUT_ERRORS = 4, _('Validated without errors')
    VALIDATED_WITH_ERRORS = 5, _('Validated with errors')
    REJECTED = 6, _('Rejected')
    SCHEDULED_FOR_PUBLICATION = 7, _('Scheduled for publication')
    PUBLISHED = 8, _('Published')
