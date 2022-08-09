from django.utils.translation import gettext as _


PS_SUBMITTED = 'submitted'
PS_ENQUEUED_FOR_VALIDATION = 'enqueued-for-validation'
PS_VALIDATED_WITH_ERRORS = 'validated-with-errors'
PS_VALIDATED_WITHOUT_ERRORS = 'validated-without-errors'
PS_REJECTED = 'rejected'
PS_ACCEPTED = 'accepted'
PS_SCHEDULED_FOR_PUBLICATION = 'scheduled-for-publication'
PS_PUBLISHED = 'published'

PACKAGE_STATUS = (
    (PS_SUBMITTED, _('Submitted')),
    (PS_ENQUEUED_FOR_VALIDATION, _('Enqueued for validation')),
    (PS_VALIDATED_WITH_ERRORS, _('Validated with errors')),
    (PS_VALIDATED_WITHOUT_ERRORS, _('Validated without errors')),
    (PS_REJECTED, _('Rejected')),
    (PS_ACCEPTED, _('Accepted')),
    (PS_SCHEDULED_FOR_PUBLICATION, _('Scheduled for publication')),
    (PS_PUBLISHED, _('Published')),
)

VE_PACKAGE_FILE_ERROR = 'package-file-error'
VE_XML_FORMAT_ERROR = 'xml-format-error'
VE_BIBLIOMETRICS_DATA_ERROR = 'bibliometrics-data-error'
VE_SERVICES_DATA_ERROR = 'services-data-error'
VE_DATA_CONSISTENCY_ERROR = 'data-consistency_error'
VE_CRITERIA_ISSUES = 'criteria-issues'

VALIDATION_ERROR_CATEGORY = (
    (VE_PACKAGE_FILE_ERROR, 'PACKAGE_FILE_ERROR'),
    (VE_XML_FORMAT_ERROR, 'XML_FORMAT_ERROR'),
    (VE_BIBLIOMETRICS_DATA_ERROR, 'BIBLIOMETRICS_DATA_ERROR'),
    (VE_SERVICES_DATA_ERROR, 'SERVICES_DATA_ERROR'),
    (VE_DATA_CONSISTENCY_ERROR, 'DATA_CONSISTENCY_ERROR'),
    (VE_CRITERIA_ISSUES, 'CRITERIA_ISSUES'),
)
