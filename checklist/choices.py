from django.utils.translation import gettext as _


MC_STATUS_DISABLED = 'disabled'
MC_STATUS_ENABLED = 'enabled'

MANUAL_CHECKING_STATUS = (
    (MC_STATUS_DISABLED, _('Disabled')),
    (MC_STATUS_ENABLED, _('Enabled')),
)
