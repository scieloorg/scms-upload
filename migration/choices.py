from django.utils.translation import gettext_lazy as _

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


PID_STATUS_MISSING = "missing"
PID_STATUS_MATCHED = "matched"
PID_STATUS_EXCEEDING = "exceeding"
PID_STATUS_UNKNOWN = "unknown"
PID_STATUS_PUBLIC_NOT_FOUND = "public_nfound"
PID_STATUS_PUBLISHED = "published"
PID_STATUS_PUBLIC_VALID = "public_ok"
PID_STATUS_PUBLIC_MISMATCHED = "public_nok"
PID_STATUS_CLASSIC_MATCHED = "classic_ok"
PID_STATUS_CLASSIC_MISMATCHED = "classic_nok"
PID_STATUS_CLASSIC_NOT_FOUND = "classic_nfound"
PID_STATUS_CLASSIC_FOUND = "classic_found"

PID_STATUS = (
    (PID_STATUS_MISSING, _("Missing")),
    (PID_STATUS_MATCHED, _("Matched")),
    (PID_STATUS_EXCEEDING, _("Exceeding")),
    (PID_STATUS_UNKNOWN, _("Unknown")),
    (PID_STATUS_PUBLISHED, _("Published")),
    (PID_STATUS_PUBLIC_NOT_FOUND, _("Published but not found")),
    (PID_STATUS_PUBLIC_VALID, _("Published and content valid")),
    (PID_STATUS_PUBLIC_MISMATCHED, _("Published and mismatched content")),
    (PID_STATUS_CLASSIC_MATCHED, _("Classic and matched content")),
    (PID_STATUS_CLASSIC_MISMATCHED, _("Classic and mismatched content")),
    (PID_STATUS_CLASSIC_FOUND, _("Classic found")),
    (PID_STATUS_CLASSIC_NOT_FOUND, _("Classic not found")),
)