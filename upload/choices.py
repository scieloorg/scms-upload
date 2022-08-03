from django.db import models
from django.utils.translation import gettext as _


class PackageStatus(models.TextChoices):
    # FIXME: refatorar esse jeito de usar choices que não funciona bem nos templates Wagtail
    SUBMITTED = 1, _('Submitted')
    ENQUEUED_FOR_VALIDATION = 2, _('Enqueued for validation')
    VALIDATED_WITH_ERRORS = 3, _('Validated with errors')
    VALIDATED_WITHOUT_ERRORS = 4, _('Validated without errors')
    REJECTED = 5, _('Rejected')
    ACCEPTED = 6, _('Accepted')
    SCHEDULED_FOR_PUBLICATION = 7, _('Scheduled for publication')
    PUBLISHED = 8, _('Published')


VALIDATION_ERROR_SEVERITY = [
    ('criteria-issues', _('CRITERIA_ISSUES')),
    ('warning', _('WARNING')),
    ('error', _('ERROR')),
    ('bibliometrics-data-error', _('BIBLIOMETRICS_DATA_ERROR')),
    ('services-data-error', _('SERVICES_DATA_ERROR')),
    ('data-consistency-error', _('DATA_CONSISTENCY_ERROR')),
    ('xml-format-error', _('XML_FORMAT_ERROR')),
]


VALIDATION_ERROR_CATEGORY = [
    ('assets', _('Assets')),
    ('stylesheet', _('Stylesheet')),
    ('structure', _('Structure')),
    ('individual-content', _('Individual content')),
    ('group-content', _('Group content')),
]
