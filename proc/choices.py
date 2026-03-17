from django.utils.translation import gettext_lazy as _

PID_STATUS_MISSING = "missing"
PID_STATUS_MATCHED = "matched"
PID_STATUS_EXCEEDING = "exceeding"

PID_STATUS = (
    ("", ""),
    (PID_STATUS_MISSING, _("Missing")),
    (PID_STATUS_MATCHED, _("Matched")),
    (PID_STATUS_EXCEEDING, _("Exceeding")),
)
