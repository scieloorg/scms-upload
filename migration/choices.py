from django.utils.translation import gettext as _

"""
Migration is the process of import and publication
Importation is getting data from classic website and saving them in new system
Publication is make data available at the new website
"""
MS_TO_IGNORE = "TO_IGNORE"
MS_TO_MIGRATE = "TO_MIGRATE"
MS_MISSING_ASSETS = "MISSING_ASSETS"
MS_XML_WIP = "XML_WIP"
MS_XML_WIP_AND_MISSING_ASSETS = "XML_WIP_AND_MISSING_ASSETS"
MS_IMPORTED = "IMPORTED"
MS_PUBLISHED = "PUBLISHED"

MIGRATION_STATUS = (
    (MS_TO_MIGRATE, _("To migrate")),
    (MS_TO_IGNORE, _("To ignore")),
    (MS_MISSING_ASSETS, _("Missing assets")),
    (MS_XML_WIP, _("XML work in progress")),
    (MS_XML_WIP_AND_MISSING_ASSETS, _("XML work in progress and missing assets")),
    (MS_IMPORTED, _("Imported")),
    (MS_PUBLISHED, _("Published")),
)


HTML2XML_DONE = "DONE"
HTML2XML_PENDING_HIGH = "PENDING_HIGH"
HTML2XML_PENDING_MEDIUM = "PENDING_MEDIUM"
HTML2XML_PENDING_LOW = "PENDING_LOW"
HTML2XML_NOT_EVALUATED = "NOT_EVALUATED"

HTML2XML_STATUS = (
    (HTML2XML_DONE, _("DONE")),
    (HTML2XML_PENDING_HIGH, _("PENDING_HIGH")),
    (HTML2XML_PENDING_MEDIUM, _("PENDING_MEDIUM")),
    (HTML2XML_PENDING_LOW, _("PENDING_LOW")),
    (HTML2XML_NOT_EVALUATED, _("NOT_EVALUATED")),
)
