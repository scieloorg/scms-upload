from django.utils.translation import gettext as _

"""
Migration is the process of import and publication
Importation is getting data from classic website and saving them in new system
Publication is make data available at the new website
"""
MS_TO_IGNORE = "TO_IGNORE"
MS_TO_MIGRATE = "TO_MIGRATE"
MS_IMPORTED = "IMPORTED"

MIGRATION_STATUS = (
    (MS_TO_MIGRATE, _("To migrate")),
    (MS_TO_IGNORE, _("To ignore")),
    (MS_IMPORTED, _("Imported")),
)

ORIGINAL_XML = "ORIGINAL_XML"
HTML2XML_TO_GENERATE = "TO_DO_HTML2XML"
HTML2XML_APPROVED_AUTOMATICALLY = "APPROVED_AUTOMATICALLY"
HTML2XML_APPROVED = "APPROVED"
HTML2XML_REJECTED = "REJECTED"
HTML2XML_NOT_EVALUATED = "NOT_EVALUATED"

HTML2XML_STATUS = (
    (HTML2XML_TO_GENERATE, _("to generate XML from HTML")),
    (HTML2XML_APPROVED_AUTOMATICALLY, _("generated XML is approved automatically")),
    (HTML2XML_APPROVED, _("generated XML is approved")),
    (HTML2XML_REJECTED, _("generated XML is rejected")),
    (HTML2XML_NOT_EVALUATED, _("generated XML is not evaluated")),
)

DOC_TO_GENERATE_SPS_PKG = "TO_GENERATE_SPS_PKG"
DOC_TO_GENERATE_XML = "TO_GENERATE_XML"
DOC_GENERATED_XML = "GENERATED_XML"
DOC_GENERATED_SPS_PKG = "GENERATED_SPS_PKG"

DOC_XML_STATUS = (
    (DOC_TO_GENERATE_XML, _("To generate XML")),
    (DOC_GENERATED_XML, _("GENERATED XML")),
    (DOC_TO_GENERATE_SPS_PKG, _("To generate SPS Package")),
    (DOC_GENERATED_SPS_PKG, _("GENERATED SPS PKG")),
)

XML_STATUS = [
    (ORIGINAL_XML, _("XML original")),
    (HTML2XML_TO_GENERATE, _("to generate XML from HTML")),
    (HTML2XML_APPROVED_AUTOMATICALLY, _("generated XML is approved automatically")),
    (HTML2XML_APPROVED, _("generated XML is approved")),
    (HTML2XML_REJECTED, _("generated XML is rejected")),
    (HTML2XML_NOT_EVALUATED, _("generated XML is not evaluated")),
]
