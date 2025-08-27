from django.utils.translation import gettext_lazy as _

HTML2XML_QA_AUTO_APPROVED = "AUTO_APPROVED"
HTML2XML_QA_APPROVED = "APPROVED"
HTML2XML_QA_REJECTED = "REJECTED"
HTML2XML_QA_NOT_EVALUATED = "NOT_EVALUATED"

HTML2XML_QA = (
    (HTML2XML_QA_AUTO_APPROVED, _("approved automatically")),
    (HTML2XML_QA_APPROVED, _("approved")),
    (HTML2XML_QA_REJECTED, _("rejected")),
    (HTML2XML_QA_NOT_EVALUATED, _("not evaluated")),
)
