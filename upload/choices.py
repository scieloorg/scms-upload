from django.utils.translation import gettext as _

# Model Package, Field status

"""
# SYSTEM
1. PS_SUBMITTED --> primeira avaliação --> 2

# SYSTEM
2.1. PS_ENQUEUED_FOR_VALIDATION --> 3
2.2. PS_UNEXPECTED --> 10

# SYSTEM
3.1. PS_READY_TO_PREVIEW --> 13
3.2. PS_PENDING_CORRECTION --> 10
3.3. PS_VALIDATED_WITH_ERRORS --> 7

# QA USER
4.1. PS_PUBLISHED --> 8

# QA USER
6.1. PS_PENDING_CORRECTION --> 10
6.2. PS_READY_TO_PREVIEW --> 13

# XML PRODUCTOR USER
# SYSTEM / CONFIGURAÇÃO DO FLUXO
7.1. PS_PENDING_CORRECTION --> 10
7.2. PS_PENDING_QA_DECISION --> 6 (MAIS TOLERANTE - GARGALO NA UNIDADE SCIELO)

# QA USER ON BEHALF ANY USER
8.1. PS_REQUIRED_ERRATUM --> 11
8.2. PS_REQUIRED_UPDATE --> 11

10. produtor de XML terá que corrigir e re-submeter

# EDITOR | ?
11.1. ASSIGN XML PRODUCTOR --> 10

# SYSTEM / QA USER
13.1. PS_PREVIEW --> 14

# QA USER
14.1. PS_PENDING_CORRECTION --> 10
14.2. PS_READY_TO_PUBLISH --> 4
"""
PS_SUBMITTED = "submitted"
PS_ENQUEUED_FOR_VALIDATION = "enqueued-for-validation"
PS_VALIDATED_WITH_ERRORS = "validated-with-errors"
PS_PENDING_CORRECTION = "pending-correction"
PS_PENDING_QA_DECISION = "pending-qa-decision"
PS_UNEXPECTED = "unexpected"
PS_READY_TO_PREVIEW = "ready-to-preview"
PS_PREVIEW = "preview"
PS_READY_TO_PUBLISH = "ready-to-publish"
PS_PUBLISHED = "published"
PS_REQUIRED_ERRATUM = "required-erratum"
PS_REQUIRED_UPDATE = "required-update"
PS_DEPUBLISHED = "depublished"
PS_ARCHIVED = "archived"

PS_WIP = (
    PS_SUBMITTED,
    PS_ENQUEUED_FOR_VALIDATION,
    PS_VALIDATED_WITH_ERRORS,
    PS_PENDING_QA_DECISION,
    # PS_UNEXPECTED,
    PS_READY_TO_PREVIEW,
    PS_PREVIEW,
    PS_READY_TO_PUBLISH,
    # PS_PUBLISHED,
    # PS_DEPUBLISHED,
    # PS_ARCHIVED,
)

PACKAGE_STATUS = (
    (PS_REQUIRED_ERRATUM, _("Required erratum")),
    (PS_REQUIRED_UPDATE, _("Required update")),
    (PS_SUBMITTED, _("Submitted")),
    (PS_ENQUEUED_FOR_VALIDATION, _("Enqueued for validation")),
    (PS_VALIDATED_WITH_ERRORS, _("Validated with errors")),
    (PS_PENDING_QA_DECISION, _("Pending quality analysis decision")),
    (PS_PENDING_CORRECTION, _("Pending for correction")),
    (PS_UNEXPECTED, _("Unexpected")),
    (PS_READY_TO_PREVIEW, _("Ready to preview on QA website")),
    (PS_PREVIEW, _("Preview")),
    (PS_READY_TO_PUBLISH, _("Ready to publish on public website")),
    (PS_PUBLISHED, _("Published")),
    (PS_ARCHIVED, _("Archived")),
)

CRITICAL_ERROR_DECISION = (
    (PS_PENDING_CORRECTION, _("Pending for correction")),
    (PS_VALIDATED_WITH_ERRORS, _("Validated with errors")),
)

QA_DECISION = (
    (PS_DEPUBLISHED, _("Depublish")),
    (PS_PENDING_CORRECTION, _("Pending for correction")),
    (PS_PENDING_QA_DECISION, _("Pending quality analysis decision")),
    (PS_READY_TO_PREVIEW, _("Ready to preview on QA website")),
    (PS_READY_TO_PUBLISH, _("Ready to publish on public website")),
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

# Model ValidationResult, campo que agrupo tipos de erro de validação, VR = Validation Report
VR_XML_OR_DTD = "xml_or_dtd"
VR_ASSET_AND_RENDITION = "asset_and_rendition"
VR_INDIVIDUAL_CONTENT = "individual_content"
VR_GROUP_CONTENT = "group_content"
VR_STYLESHEET = "stylesheet"
VR_PACKAGE_FILE = "package_file"

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
VAL_CAT_RENDITION_CONTENT = "rendition-content"
VAL_CAT_WEB_PAGE_CONTENT = "web-page-content"
VAL_CAT_GROUP_DATA = "group"
VAL_CAT_QA_CONCLUSION = "qa-conclusion"


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
    (VAL_CAT_PACKAGE_FILE, "PACKAGE_FILE"),
    (VAL_CAT_QA_CONCLUSION, "QA conclusion"),
)

# Model ValidationResult, Field status
REPORT_CREATION_NONE = ""
REPORT_CREATION_WIP = "doing"
REPORT_CREATION_DONE = "done"

REPORT_CREATION = (
    (REPORT_CREATION_DONE, "done"),
    (REPORT_CREATION_WIP, "doing"),
    (REPORT_CREATION_NONE, ""),
)

# Model ValidationResult, Field status
VALIDATION_RESULT_SUCCESS = "OK"
VALIDATION_RESULT_FAILURE = "ERROR"
VALIDATION_RESULT_CRITICAL = "CRITICAL"
VALIDATION_RESULT_BLOCKING = "BLOCKING"
VALIDATION_RESULT_UNKNOWN = "UKN"
VALIDATION_RESULT_WARNING = "WARNING"

VALIDATION_RESULT = (
    (VALIDATION_RESULT_BLOCKING, _("blocking")),
    (VALIDATION_RESULT_CRITICAL, _("critical")),
    (VALIDATION_RESULT_FAILURE, _("error")),
    (VALIDATION_RESULT_UNKNOWN, _("unknown")),
    (VALIDATION_RESULT_WARNING, _("warning")),
    (VALIDATION_RESULT_SUCCESS, _("ok")),
)

# Model ErrorResolution, Field action
ER_REACTION_FIX = "to-fix"
ER_REACTION_NOT_TO_FIX = "not-to-fix"
ER_REACTION_IMPOSSIBLE_TO_FIX = "unable-to-fix"

ERROR_REACTION = (
    (ER_REACTION_FIX, _("XML producer will fix this error")),
    (
        ER_REACTION_IMPOSSIBLE_TO_FIX,
        _("XML producer declares that correction is impossible"),
    ),
    (ER_REACTION_NOT_TO_FIX, _("XML producer disagrees that there is an error")),
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


STRICT_AUTO_PUBLICATION = "strict"
FLEXIBLE_AUTO_PUBLICATION = "flexible"
MANUAL_PUBLICATION = "manual"

PUBLICATION_RULE = (
    (FLEXIBLE_AUTO_PUBLICATION, _("Flexible auto publication")),
    (STRICT_AUTO_PUBLICATION, _("Strict auto publication")),
    (MANUAL_PUBLICATION, _("Manual publication")),
)

# nunca publicado antes
UNRELEASED = "unreleased"
# publicado
PUBLISHED = "published"
# despubicado
DEPUBLISHED = "depublished"

WEBSITE_STATUS = (
    (UNRELEASED, _("unreleased")),
    (PUBLISHED, _("published")),
    (DEPUBLISHED, _("depublished")),
)
