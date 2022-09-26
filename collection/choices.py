from django.utils.translation import gettext_lazy as _

CURRENT = 'C'
NOT_INFORMED = ''
CEASED = 'D'
UNKNOWN = '?'
SUSPENDED = 'S'

JOURNAL_PUBLICATION_STATUS = [
    (SUSPENDED, _('Suspended')),
    (UNKNOWN, _('Unknown')),
    (CEASED, _('Ceased')),
    (NOT_INFORMED, _('Not informed')),
    (CURRENT, _('Current')),
]


QA = 'QA'
PUBLIC = 'PUBLIC'

WEBSITE_KIND = [
    (QA, _('QA')),
    (PUBLIC, _('PUBLIC')),
]
