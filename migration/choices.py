from django.utils.translation import gettext as _


MS_TO_MIGRATE = 'TO_MIGRATE'
MS_MIGRATED = 'MIGRATED'
MS_PUBLISHED = 'PUBLISHED'

MIGRATION_STATUS = (
    (MS_TO_MIGRATE, _('To migrate')),
    (MS_MIGRATED, _('Migrated')),
    (MS_PUBLISHED, _('Published')),
)
