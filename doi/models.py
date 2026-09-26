import sys
import logging

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.db import IntegrityError, models
from django.utils.translation import gettext_lazy as _
from wagtail.admin.panels import FieldPanel, ObjectList, TabbedInterface

from core.models import CommonControlField

from .forms import DOIWithLangForm, CrossrefConfigurationForm
from collection.models import Language


User = get_user_model()

logger = logging.getLogger(__name__)


class DOIWithLang(CommonControlField):
    doi = models.CharField(_("DOI"), max_length=256, blank=False, null=False)
    lang = models.ForeignKey(
        Language, null=True, blank=True, on_delete=models.SET_NULL
    )

    panels = [
        FieldPanel("doi"),
        FieldPanel("lang"),
    ]

    def __str__(self):
        return f"{self.lang}: {self.doi}"

    base_form_class = DOIWithLangForm


class XMLCrossRef(CommonControlField):
    file = models.FileField(null=True, blank=True)
    uri = models.URLField(null=True, blank=True)

    class Meta:
        ordering = ("file",)
        verbose_name = "XMLCrossRef"
        verbose_name_plural = "XMLCrossRef"

    def __str__(self):
        return f"{self.uri}"


class CrossrefConfiguration(CommonControlField):
    """
    Configuração do Crossref por periódico.
    Armazena os dados necessários para realizar o depósito de DOI no Crossref.
    """

    journal = models.OneToOneField(
        "journal.Journal",
        on_delete=models.CASCADE,
        related_name="crossref_configuration",
        verbose_name=_("Journal"),
    )
    crossmark_policy_url = models.URLField(
        _("Crossmark Policy URL"),
        null=True,
        blank=True,
        help_text=_("URL of the journal's crossmark policy page"),
    )
    crossmark_policy_doi = models.CharField(
        _("Crossmark Policy DOI"),
        max_length=256,
        null=True,
        blank=True,
        help_text=_("DOI of the journal's crossmark policy"),
    )
    depositor_name = models.CharField(
        _("Depositor Name"),
        max_length=256,
        null=False,
        blank=False,
        help_text=_("Name of the depositor (contact person or organization)"),
    )
    depositor_email = models.EmailField(
        _("Depositor Email"),
        null=False,
        blank=False,
        help_text=_("Email address for deposit notifications"),
    )
    registrant = models.CharField(
        _("Registrant"),
        max_length=256,
        null=False,
        blank=False,
        help_text=_("Name of the organization registering the DOIs (typically the publisher)"),
    )
    login_id = models.CharField(
        _("Crossref Login ID"),
        max_length=256,
        null=True,
        blank=True,
        help_text=_("Crossref member account username for API deposit"),
    )
    login_password = models.CharField(
        _("Crossref Login Password"),
        max_length=256,
        null=True,
        blank=True,
        help_text=_("Crossref member account password for API deposit"),
    )

    class Meta:
        verbose_name = _("Crossref Configuration")
        verbose_name_plural = _("Crossref Configurations")

    base_form_class = CrossrefConfigurationForm

    panels_configuration = [
        FieldPanel("journal"),
        FieldPanel("depositor_name"),
        FieldPanel("depositor_email"),
        FieldPanel("registrant"),
    ]

    panels_crossmark = [
        FieldPanel("crossmark_policy_url"),
        FieldPanel("crossmark_policy_doi"),
    ]

    panels_credentials = [
        FieldPanel("login_id"),
        FieldPanel("login_password"),
    ]

    edit_handler = TabbedInterface(
        [
            ObjectList(panels_configuration, heading=_("Configuration")),
            ObjectList(panels_crossmark, heading=_("Crossmark Policy")),
            ObjectList(panels_credentials, heading=_("Credentials")),
        ]
    )

    def __str__(self):
        return f"CrossrefConfiguration({self.journal})"

    @classmethod
    def get(cls, journal):
        return cls.objects.get(journal=journal)

    @classmethod
    def create_or_update(
        cls,
        user,
        journal,
        depositor_name,
        depositor_email,
        registrant,
        crossmark_policy_url=None,
        crossmark_policy_doi=None,
        login_id=None,
        login_password=None,
    ):
        try:
            obj = cls.get(journal=journal)
            obj.updated_by = user
        except cls.DoesNotExist:
            obj = cls(creator=user, journal=journal)

        obj.depositor_name = depositor_name
        obj.depositor_email = depositor_email
        obj.registrant = registrant
        obj.crossmark_policy_url = crossmark_policy_url
        obj.crossmark_policy_doi = crossmark_policy_doi
        if login_id:
            obj.login_id = login_id
        if login_password:
            obj.login_password = login_password
        obj.save()
        return obj


class CrossrefDepositStatus:
    PENDING = "pending"
    SUBMITTED = "submitted"
    SUCCESS = "success"
    ERROR = "error"


CROSSREF_DEPOSIT_STATUS = (
    (CrossrefDepositStatus.PENDING, _("Pending")),
    (CrossrefDepositStatus.SUBMITTED, _("Submitted")),
    (CrossrefDepositStatus.SUCCESS, _("Success")),
    (CrossrefDepositStatus.ERROR, _("Error")),
)


class CrossrefDeposit(CommonControlField):
    """
    Registro de depósito de DOI no Crossref para um artigo.
    """

    article = models.ForeignKey(
        "article.Article",
        on_delete=models.CASCADE,
        related_name="crossref_deposits",
        verbose_name=_("Article"),
    )
    xml_crossref = models.ForeignKey(
        XMLCrossRef,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name=_("Crossref XML"),
        related_name="deposits",
    )
    status = models.CharField(
        _("Status"),
        max_length=16,
        choices=CROSSREF_DEPOSIT_STATUS,
        default=CrossrefDepositStatus.PENDING,
    )
    response_status = models.IntegerField(
        _("HTTP Response Status"),
        null=True,
        blank=True,
    )
    response_body = models.TextField(
        _("Response Body"),
        null=True,
        blank=True,
    )
    batch_id = models.CharField(
        _("Batch ID"),
        max_length=256,
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = _("Crossref Deposit")
        verbose_name_plural = _("Crossref Deposits")
        ordering = ["-updated"]

    panels = [
        FieldPanel("article", read_only=True),
        FieldPanel("status"),
        FieldPanel("batch_id", read_only=True),
        FieldPanel("response_status", read_only=True),
        FieldPanel("response_body", read_only=True),
        FieldPanel("xml_crossref"),
    ]

    def __str__(self):
        return f"CrossrefDeposit({self.article}, {self.status})"

    @classmethod
    def create(cls, user, article, xml_content=None):
        xml_crossref = None
        if xml_content:
            xml_crossref = XMLCrossRef(creator=user)
            xml_crossref.file.save(
                f"crossref_{article.pid_v3}.xml",
                ContentFile(xml_content.encode("utf-8") if isinstance(xml_content, str) else xml_content),
            )
            xml_crossref.save()

        obj = cls(
            creator=user,
            article=article,
            xml_crossref=xml_crossref,
            status=CrossrefDepositStatus.PENDING,
        )
        obj.save()
        return obj

    def mark_submitted(self, batch_id=None):
        self.status = CrossrefDepositStatus.SUBMITTED
        if batch_id:
            self.batch_id = batch_id
        self.save()

    def mark_success(self, response_status=None, response_body=None):
        self.status = CrossrefDepositStatus.SUCCESS
        self.response_status = response_status
        self.response_body = response_body
        self.save()

    def mark_error(self, response_status=None, response_body=None):
        self.status = CrossrefDepositStatus.ERROR
        self.response_status = response_status
        self.response_body = response_body
        self.save()
