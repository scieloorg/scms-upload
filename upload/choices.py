from django.utils.translation import gettext_lazy as _

WEBSITE_ENVIRONMENTS = (("QA", _("QA")), ("PUBLIC", _("Production")))
WEBSITE_ENVIRONMENT_LABELS = dict(WEBSITE_ENVIRONMENTS)

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
    (PS_REQUIRED_ERRATUM, _("Erratum required")),
    (PS_REQUIRED_UPDATE, _("Update required")),
    (PS_SUBMITTED, _("Submitted")),
    (PS_ENQUEUED_FOR_VALIDATION, _("Processing")),
    (PS_VALIDATED_WITH_ERRORS, _("Validation issues found")),
    (PS_PENDING_QA_DECISION, _("Awaiting quality review")),
    (PS_PENDING_CORRECTION, _("Awaiting corrections")),
    (PS_UNEXPECTED, _("Unexpected submission")),
    (PS_READY_TO_PREVIEW, _("Publication on QA website authorized")),
    (PS_PREVIEW, _("Published in QA")),
    (PS_READY_TO_PUBLISH, _("Publication in Production authorized")),
    (PS_PUBLISHED, _("Published in Production")),
    (PS_ARCHIVED, _("Archived")),
)

CRITICAL_ERROR_DECISION = (
    (PS_PENDING_CORRECTION, _("Awaiting corrections")),
    (PS_VALIDATED_WITH_ERRORS, _("Validation issues found")),
)

QA_DECISION = (
    (PS_DEPUBLISHED, _("Depublish")),
    (PS_PENDING_CORRECTION, _("Request correction")),
    (PS_PENDING_QA_DECISION, _("Assign quality review")),
    (PS_READY_TO_PREVIEW, _("Publish on QA website")),
    (PS_READY_TO_PUBLISH, _("Publish in Production")),
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
    (VAL_CAT_ARTICLE_JOURNAL_COMPATIBILITY, _("Journal compatibility")),
    (VAL_CAT_ARTICLE_IS_NOT_NEW, _("Existing article")),
    (VAL_CAT_XML_FORMAT, _("XML format")),
    (VAL_CAT_STYLE, _("XML style")),
    (VAL_CAT_XML_CONTENT, _("XML content")),
    (VAL_CAT_GROUP_DATA, _("Group data")),
    (VAL_CAT_BIBLIOMETRICS_DATA, _("Bibliometric data")),
    (VAL_CAT_SERVICES_DATA, _("Service data")),
    (VAL_CAT_DATA_CONSISTENCY, _("Data consistency")),
    (VAL_CAT_CRITERIA_ISSUES, _("Publication criteria")),
    (VAL_CAT_ASSET, _("Images and other files")),
    (VAL_CAT_RENDITION, _("Full-text files")),
    (VAL_CAT_PACKAGE_FILE, _("Package file")),
    (VAL_CAT_QA_CONCLUSION, _("QA conclusion")),
)

# Model ValidationResult, Field status
REPORT_CREATION_NONE = ""
REPORT_CREATION_WIP = "doing"
REPORT_CREATION_DONE = "done"

REPORT_CREATION = (
    (REPORT_CREATION_DONE, _("Completed")),
    (REPORT_CREATION_WIP, _("In progress")),
    (REPORT_CREATION_NONE, _("Not specified")),
)

# Model ValidationResult, Field status
VALIDATION_RESULT_SUCCESS = "OK"
VALIDATION_RESULT_FAILURE = "ERROR"
VALIDATION_RESULT_CRITICAL = "CRITICAL"
VALIDATION_RESULT_BLOCKING = "BLOCKING"
VALIDATION_RESULT_UNKNOWN = "UKN"
VALIDATION_RESULT_WARNING = "WARNING"

VALIDATION_RESULT = (
    (VALIDATION_RESULT_BLOCKING, _("Blocking")),
    (VALIDATION_RESULT_CRITICAL, _("Critical")),
    (VALIDATION_RESULT_FAILURE, _("Error")),
    (VALIDATION_RESULT_UNKNOWN, _("Unknown")),
    (VALIDATION_RESULT_WARNING, _("Warning")),
    (VALIDATION_RESULT_SUCCESS, _("OK")),
)

# Model ErrorResolution, Field action
ER_REACTION_FIX = "to-fix"
ER_REACTION_NOT_TO_FIX = "not-to-fix"
ER_REACTION_IMPOSSIBLE_TO_FIX = "unable-to-fix"

ERROR_REACTION = (
    (ER_REACTION_FIX, _("The error will be fixed")),
    (
        ER_REACTION_IMPOSSIBLE_TO_FIX,
        _("Impossible to fix it"),
    ),
    (ER_REACTION_NOT_TO_FIX, _("There's disagreement about the error")),
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
