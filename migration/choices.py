from django.utils.translation import gettext as _


MS_TO_IGNORE = 'TO_IGNORE'
MS_TO_MIGRATE = 'TO_MIGRATE'
MS_MIGRATED = 'MIGRATED'
MS_PUBLISHED = 'PUBLISHED'

MIGRATION_STATUS = (
    (MS_TO_MIGRATE, _('To migrate')),
    (MS_TO_IGNORE, _('To ignore')),
    (MS_MIGRATED, _('Migrated')),
    (MS_PUBLISHED, _('Published')),
)
