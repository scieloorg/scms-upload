from django.utils.translation import gettext_lazy as _

PKG_ORIGIN_MIGRATION = "MIGRATION"
PKG_ORIGIN_UPLOAD = "UPLOAD"


PKG_ORIGIN = [
    (PKG_ORIGIN_MIGRATION, _("MIGRATION")),
    (PKG_ORIGIN_UPLOAD, _("UPLOAD")),
]
