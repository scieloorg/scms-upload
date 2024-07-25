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

INDEXING_INTERRUPTION_REASON = [
    ("ceased", _("Ceased journal")),
    ("not-open-access", _("Not open access")),
    ("suspended-by-committee", _("by the committee")),
    ("suspended-by-editor", _("by the editor")),
]


JOURNAL_EVENT_TYPE = [
    ("ADMITTED", _("Admitted to the collection")),
    ("INTERRUPTED", _("Indexing interrupted")),
]


STUDY_AREA = [
    ("Agricultural Sciences", _("Agricultural Sciences")),
    ("Applied Social Sciences", _("Applied Social Sciences")),
    ("Biological Sciences", _("Biological Sciences")),
    ("Engineering", _("Engineering")),
    ("Exact and Earth Sciences", _("Exact and Earth Sciences")),
    ("Health Sciences", _("Health Sciences")),
    ("Human Sciences", _("Human Sciences")),
    ("Linguistics, Letters and Arts", _("Linguistic, Literature and Arts")),
    ("Psicanalise", _("Psicanalise")),
]
