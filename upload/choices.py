from django.utils.translation import gettext as _

# Model Package, Field status
PS_SUBMITTED = "submitted"
PS_ENQUEUED_FOR_VALIDATION = "enqueued-for-validation"
PS_VALIDATED_WITH_ERRORS = "validated-with-errors"
PS_VALIDATED_WITHOUT_ERRORS = "validated-without-errors"
PS_PENDING_CORRECTION = "pending-correction"
PS_READY_TO_BE_FINISHED = "ready-to-be-finished"
PS_QA = "quality-analysis"
PS_REJECTED = "rejected"
PS_ACCEPTED = "accepted"
PS_SCHEDULED_FOR_PUBLICATION = "scheduled-for-publication"
PS_PUBLISHED = "published"

PS_REQUIRED_ERRATUM = "required-erratum"
PS_REQUIRED_UPDATE = "required-update"

PACKAGE_STATUS = (
    (PS_SUBMITTED, _("Submitted")),
    (PS_ENQUEUED_FOR_VALIDATION, _("Enqueued for validation")),
    (PS_VALIDATED_WITH_ERRORS, _("Validated with errors")),
    (PS_VALIDATED_WITHOUT_ERRORS, _("Validated without errors")),
    (PS_PENDING_CORRECTION, _("Pending for correction")),
    (PS_READY_TO_BE_FINISHED, _("Ready to be finished")),
    (PS_QA, _("Waiting for quality analysis")),
    (PS_REJECTED, _("Rejected")),
    (PS_ACCEPTED, _("Accepted")),
    (PS_SCHEDULED_FOR_PUBLICATION, _("Scheduled for publication")),
    (PS_PUBLISHED, _("Published")),
)

# Model Package, Field category
PC_ERRATUM = "erratum"
PC_UPDATE = "update"
PC_NEW_DOCUMENT = "new-document"
PC_SYSTEM_GENERATED = "generated-by-the-system"

PACKAGE_CATEGORY = (
    (PC_UPDATE, _("Update")),
    (PC_ERRATUM, _("Erratum")),
    (PC_NEW_DOCUMENT, _("New document")),
)


# Model ValidationResult, Field category, VE = Validation Error
VE_PACKAGE_FILE_ERROR = "package-file-error"
VE_UNEXPECTED_ERROR = "unexpected-error"
VE_FORBIDDEN_UPDATE_ERROR = "forbidden-update-error"
VE_ARTICLE_JOURNAL_INCOMPATIBILITY_ERROR = "journal-incompatibility-error"
VE_ARTICLE_IS_NOT_NEW_ERROR = "article-is-not-new-error"
VE_XML_FORMAT_ERROR = "xml-format-error"
VE_XML_CONTENT_ERROR = "xml-content-error"
VE_BIBLIOMETRICS_DATA_ERROR = "bibliometrics-data-error"
VE_SERVICES_DATA_ERROR = "services-data-error"
VE_DATA_CONSISTENCY_ERROR = "data-consistency-error"
VE_CRITERIA_ISSUES_ERROR = "criteria-issues-error"
VE_ASSET_ERROR = "asset-error"
VE_RENDITION_ERROR = "rendition-error"
VE_GROUP_DATA_ERROR = "group-error"

VALIDATION_ERROR_CATEGORY = (
    (VE_UNEXPECTED_ERROR, "UNEXPECTED_ERROR"),
    (VE_FORBIDDEN_UPDATE_ERROR, "FORBIDDEN_UPDATE_ERROR"),
    (VE_ARTICLE_JOURNAL_INCOMPATIBILITY_ERROR, "ARTICLE_JOURNAL_INCOMPATIBILITY_ERROR"),
    (VE_ARTICLE_IS_NOT_NEW_ERROR, "ARTICLE_IS_NOT_NEW_ERROR"),
    (VE_XML_FORMAT_ERROR, "XML_FORMAT_ERROR"),
    (VE_XML_CONTENT_ERROR, "VE_XML_CONTENT_ERROR"),
    (VE_GROUP_DATA_ERROR, "VE_GROUP_DATA_ERROR"),
    (VE_BIBLIOMETRICS_DATA_ERROR, "BIBLIOMETRICS_DATA_ERROR"),
    (VE_SERVICES_DATA_ERROR, "SERVICES_DATA_ERROR"),
    (VE_DATA_CONSISTENCY_ERROR, "DATA_CONSISTENCY_ERROR"),
    (VE_CRITERIA_ISSUES_ERROR, "CRITERIA_ISSUES"),
    (VE_ASSET_ERROR, "ASSET_ERROR"),
    (VE_RENDITION_ERROR, "RENDITION_ERROR"),
)

# Model ValidationResult, campo que agrupo tipos de erro de validação, VR = Validation Report
VR_XML_OR_DTD = "xml_or_dtd"
VR_ASSET_AND_RENDITION = "asset_and_rendition"
VR_INDIVIDUAL_CONTENT = "individual_content"
VR_GROUP_CONTENT = "group_content"
VR_STYLESHEET = "stylesheet"
VR_PACKAGE_FILE = "package_file"

VALIDATION_DICT_ERROR_CATEGORY_TO_REPORT = {
    VE_XML_FORMAT_ERROR: VR_XML_OR_DTD,
    VE_ASSET_ERROR: VR_ASSET_AND_RENDITION,
    VE_RENDITION_ERROR: VR_ASSET_AND_RENDITION,
    VE_ARTICLE_IS_NOT_NEW_ERROR: VR_INDIVIDUAL_CONTENT,
    VE_ARTICLE_JOURNAL_INCOMPATIBILITY_ERROR: VR_INDIVIDUAL_CONTENT,
    VE_XML_CONTENT_ERROR: VR_INDIVIDUAL_CONTENT,
    VE_BIBLIOMETRICS_DATA_ERROR: VR_INDIVIDUAL_CONTENT,
    VE_DATA_CONSISTENCY_ERROR: VR_INDIVIDUAL_CONTENT,
    VE_CRITERIA_ISSUES_ERROR: VR_INDIVIDUAL_CONTENT,
    VE_SERVICES_DATA_ERROR: VR_INDIVIDUAL_CONTENT,
    VE_GROUP_DATA_ERROR: VR_GROUP_CONTENT,
    VE_PACKAGE_FILE_ERROR: VR_PACKAGE_FILE,
    VE_UNEXPECTED_ERROR: VR_PACKAGE_FILE,
    VE_FORBIDDEN_UPDATE_ERROR: VR_PACKAGE_FILE,
}


def _get_categories():
    d = {}
    for k, v in VALIDATION_DICT_ERROR_CATEGORY_TO_REPORT.items():
        d.setdefault(v, [])
        d[v].append(k)
    return d


VALIDATION_REPORT_ITEMS = _get_categories()

# Model ValidationResult, Field status
VS_CREATED = "created"
VS_DISAPPROVED = "disapproved"
VS_APPROVED = "approved"

VALIDATION_STATUS = (
    (VS_CREATED, "created"),
    (VS_DISAPPROVED, "disapproved"),
    (VS_APPROVED, "approved"),
)

# Model ErrorResolution, Field action
ER_ACTION_TO_FIX = "to-fix"
ER_ACTION_DISAGREE = "disagree"

ERROR_RESOLUTION_ACTION = (
    (ER_ACTION_TO_FIX, _("I will fix this error")),
    (ER_ACTION_DISAGREE, _("This is not an error")),
)


# Model ErrorResolution, Field opinion
ER_OPINION_FIXED = "fixed"
ER_OPINION_FIX_DEMANDED = "fix-demanded"

ERROR_RESOLUTION_OPINION = (
    (ER_OPINION_FIXED, _("Fixed")),
    (ER_OPINION_FIX_DEMANDED, _("Error has to be fixed")),
)


VAL_CAT_PACKAGE_FILE = "package-file"
VAL_CAT_UNEXPECTED = "unexpected"
VAL_CAT_FORBIDDEN_UPDATE = "forbidden-update"
VAL_CAT_ARTICLE_JOURNAL_COMPATIBILITY = "journal-incompatibility"
VAL_CAT_ARTICLE_IS_NOT_NEW = "article-is-not-new"
VAL_CAT_XML_FORMAT = "xml-format"
VAL_CAT_STYLE = "xml-style"
VAL_CAT_XML_CONTENT = "xml-content"
VAL_CAT_BIBLIOMETRICS_DATA = "bibliometrics-data"
VAL_CAT_SERVICES_DATA = "services-data"
VAL_CAT_DATA_CONSISTENCY = "data-consistency"
VAL_CAT_CRITERIA_ISSUES = "criteria-issues"
VAL_CAT_ASSET = "asset"
VAL_CAT_RENDITION = "rendition"
VAL_CAT_GROUP_DATA = "group"

VALIDATION_CATEGORY = (
    (VAL_CAT_ARTICLE_JOURNAL_COMPATIBILITY, "ARTICLE_JOURNAL_COMPATIBILITY"),
    (VAL_CAT_ARTICLE_IS_NOT_NEW, "ARTICLE_IS_NOT_NEW"),
    (VAL_CAT_XML_FORMAT, "XML_FORMAT"),
    (VAL_CAT_STYLE, "XML_STYLE"),
    (VAL_CAT_XML_CONTENT, "VAL_CAT_XML_CONTENT"),
    (VAL_CAT_GROUP_DATA, "VAL_CAT_GROUP_DATA"),
    (VAL_CAT_BIBLIOMETRICS_DATA, "BIBLIOMETRICS_DATA"),
    (VAL_CAT_SERVICES_DATA, "SERVICES_DATA"),
    (VAL_CAT_DATA_CONSISTENCY, "DATA_CONSISTENCY"),
    (VAL_CAT_CRITERIA_ISSUES, "CRITERIA_ISSUES"),
    (VAL_CAT_ASSET, "ASSET"),
    (VAL_CAT_RENDITION, "RENDITION"),
)


# Model ValidationResult, Field status
REPORT_CONCLUSION_REJECTED = "rejected"
REPORT_CONCLUSION_ACCEPTED_WITH_ERRORS = "has-errors"
REPORT_CONCLUSION_APPROVED = "approved"
REPORT_CONCLUSION_NONE = ""
REPORT_CONCLUSION_WIP = "doing"
REPORT_CONCLUSION_DONE = "done"

REPORT_CONCLUSION = (
    (REPORT_CONCLUSION_DONE, "done"),
    (REPORT_CONCLUSION_WIP, "doing"),
    (REPORT_CONCLUSION_NONE, ""),
    (REPORT_CONCLUSION_REJECTED, "rejected"),
    (REPORT_CONCLUSION_ACCEPTED_WITH_ERRORS, "has-errors"),
    (REPORT_CONCLUSION_APPROVED, "approved"),
)

# Model ValidationResult, Field status
VALIDATION_RESULT_SUCCESS = "success"
VALIDATION_RESULT_FAILURE = "failure"
VALIDATION_RESULT_UNKNOWN = "unknown"

VALIDATION_RESULT = (
    (VALIDATION_RESULT_SUCCESS, "success"),
    (VALIDATION_RESULT_FAILURE, "failure"),
    (VALIDATION_RESULT_UNKNOWN, "unknown"),
)

# Model ErrorResolution, Field action
ER_REACTION_FIX = "fix"
ER_REACTION_JUSTIFY = "justify"
ER_REACTION_ABSENT_DATA = "absence"

ERROR_REACTION = (
    (ER_REACTION_FIX, _("I will fix this error")),
    (ER_REACTION_ABSENT_DATA, _("Data is absent")),
    (ER_REACTION_JUSTIFY, _("I am adding a justification not to correct")),
)


# Model ErrorResolution, Field opinion
ER_DECISION_NO_CORRECTION_NEEDED = "accepted"
ER_DECISION_ACCEPTED_WITH_ERRORS = "accepted-with-error"
ER_DECISION_CORRECTION_REQUIRED = "to-fix"

ERROR_DECISION = (
    (ER_DECISION_ACCEPTED_WITH_ERRORS, _("Accepted with errors")),
    (ER_DECISION_NO_CORRECTION_NEEDED, _("Accepted")),
    (ER_DECISION_CORRECTION_REQUIRED, _("Correction required")),
)
