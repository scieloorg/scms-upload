from django.db import models
from django.utils.translation import gettext_lazy as _
from modelcluster.fields import ParentalKey
from modelcluster.models import ClusterableModel
from wagtail.admin.panels import FieldPanel, InlinePanel
from wagtail.models import Orderable

from core.models import CommonControlField
from institution.models import Institution, InstitutionHistory

from . import choices
from .forms import ResearcherForm


class Researcher(ClusterableModel, CommonControlField):
    """
    Class that represent the Researcher
    """

    given_names = models.CharField(
        _("Given names"), max_length=128, blank=False, null=False
    )
    last_name = models.CharField(
        _("Last name"), max_length=128, blank=False, null=False
    )
    suffix = models.CharField(_("Suffix"), max_length=20, blank=True, null=True)
    orcid = models.CharField(_("ORCID"), max_length=40, blank=True, null=True)
    lattes = models.CharField(_("Lattes"), max_length=40, blank=True, null=True)
    gender = models.CharField(_("Gender"), max_length=1, choices=choices.GENDER)
    gender_identification_status = models.CharField(
        _("Gender identification status"),
        max_length=10,
        choices=choices.GENDER_IDENTIFICATION_STATUS,
        null=False,
        blank=False,
    )

    def __unicode__(self):
        return "%s%s, %s (%s)" % (
            self.last_name,
            self.suffix and f" {self.suffix}" or "",
            self.given_names,
            self.orcid,
        )

    def __str__(self):
        return "%s%s, %s (%s)" % (
            self.last_name,
            self.suffix and f" {self.suffix}" or "",
            self.given_names,
            self.orcid,
        )

    panels = [
        FieldPanel("given_names"),
        FieldPanel("last_name"),
        FieldPanel("suffix"),
        FieldPanel("orcid"),
        FieldPanel("lattes"),
        InlinePanel("page_email", label=_("Email")),
        FieldPanel("gender"),
        FieldPanel("gender_identification_status"),
        InlinePanel("affiliation", label=_("Affiliation")),
    ]

    base_form_class = ResearcherForm


class FieldEmail(Orderable):
    page = ParentalKey(Researcher, on_delete=models.CASCADE, related_name="page_email")
    email = models.EmailField(_("Email"), max_length=128, blank=True, null=True)


class FieldAffiliation(Orderable, InstitutionHistory):
    page = ParentalKey(Researcher, on_delete=models.CASCADE, related_name="affiliation")
