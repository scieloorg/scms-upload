from django.utils.translation import gettext as _


PS_SUBMITTED = 'submitted'
PS_ENQUEUED_FOR_VALIDATION = 'enqueued-for-validation'
PS_VALIDATED_WITH_ERRORS = 'validated-with-errors'
PS_VALIDATED_WITHOUT_ERRORS = 'validated-without-errors'
PS_PENDING_CORRECTION = 'pending-correction'
PS_READY_TO_BE_FINISHED = 'ready-to-be-finished'
PS_QA = 'quality-analysis'
PS_REJECTED = 'rejected'
PS_ACCEPTED = 'accepted'
PS_SCHEDULED_FOR_PUBLICATION = 'scheduled-for-publication'
PS_PUBLISHED = 'published'

PACKAGE_STATUS = (
    (PS_SUBMITTED, _('Submitted')),
    (PS_ENQUEUED_FOR_VALIDATION, _('Enqueued for validation')),
    (PS_VALIDATED_WITH_ERRORS, _('Validated with errors')),
    (PS_VALIDATED_WITHOUT_ERRORS, _('Validated without errors')),
    (PS_PENDING_CORRECTION, _('Pending for correction')),
    (PS_READY_TO_BE_FINISHED, _('Ready to be finished')),
    (PS_QA, _('Waiting for quality analysis')),
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
VE_ASSET_ERROR = 'asset-error'
VE_RENDITION_ERROR = 'rendition-error'

VALIDATION_ERROR_CATEGORY = (
    (VE_PACKAGE_FILE_ERROR, 'PACKAGE_FILE_ERROR'),
    (VE_XML_FORMAT_ERROR, 'XML_FORMAT_ERROR'),
    (VE_BIBLIOMETRICS_DATA_ERROR, 'BIBLIOMETRICS_DATA_ERROR'),
    (VE_SERVICES_DATA_ERROR, 'SERVICES_DATA_ERROR'),
    (VE_DATA_CONSISTENCY_ERROR, 'DATA_CONSISTENCY_ERROR'),
    (VE_CRITERIA_ISSUES, 'CRITERIA_ISSUES'),
    (VE_ASSET_ERROR, 'ASSET_ERROR'),
    (VE_RENDITION_ERROR, 'RENDITION_ERROR'),
)

ER_ACTION_TO_FIX = 'to-fix'
ER_ACTION_DISAGREE = 'disagree'
ER_ACTION_UNKNOW = 'unknow'

ERROR_RESOLUTION_ACTION = (
    (ER_ACTION_TO_FIX, _('I will fix this error')),
    (ER_ACTION_DISAGREE, _('This is not an error')),
    (ER_ACTION_UNKNOW, _('I do not know how to fix this error'))
)
