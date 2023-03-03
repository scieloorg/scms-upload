from django.utils.translation import gettext as _

"""
Migration is the process of import and publication
Importation is getting data from classic website and saving them in new system
Publication is make data available at the new website
"""
MS_TO_IGNORE = "TO_IGNORE"
MS_TO_MIGRATE = "TO_MIGRATE"
MS_IMPORTED = "IMPORTED"
MS_PUBLISHED = "PUBLISHED"

MIGRATION_STATUS = (
    (MS_TO_MIGRATE, _("To migrate")),
    (MS_TO_IGNORE, _("To ignore")),
    (MS_IMPORTED, _("Imported")),
    (MS_PUBLISHED, _("Published")),
)
