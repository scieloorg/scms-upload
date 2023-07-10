from django.utils.translation import gettext_lazy as _

SOCIAL_NETWORK_NAMES = [
    ("facebook", "Facebook"),
    ("twitter", "Twitter"),
    ("journal", _("Journal URL")),
]


CURRENT = "C"
NOT_INFORMED = ""
CEASED = "D"
UNKNOWN = "?"
SUSPENDED = "S"

JOURNAL_PUBLICATION_STATUS = [
    (SUSPENDED, _("Suspended")),
    (UNKNOWN, _("Unknown")),
    (CEASED, _("Ceased")),
    (NOT_INFORMED, _("Not informed")),
    (CURRENT, _("Current")),
]

# AVAILABILTY on the website
JOURNAL_AVAILABILTY_STATUS = [
    (UNKNOWN, _("Unknown")),
    (CURRENT, _("Current")),
]
