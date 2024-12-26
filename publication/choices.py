from django.utils.translation import gettext as _
from core.utils.requester import NonRetryableError, RetryableError


VERIFY_HTTP_ERROR_CODE = [
    (RetryableError, _("Excessively long response time. Retry later")),
    (NonRetryableError, _("Url not found.")),
]
