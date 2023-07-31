from django.db import models
from django.utils.translation import gettext as _
from modelcluster.models import ClusterableModel
from wagtail.admin.edit_handlers import FieldPanel, InlinePanel

from core.models import CommonControlField
from location.models import Location

from . import choices
from .forms import InstitutionForm


class Institution(CommonControlField, ClusterableModel):
    name = models.TextField(_("Name"), null=True, blank=True)
    institution_type = models.CharField(
        _("Institution Type"),
        choices=choices.inst_type,
        max_length=255,
        null=True,
        blank=True,
    )

    location = models.ForeignKey(
        Location, null=True, blank=True, on_delete=models.SET_NULL
    )

    acronym = models.TextField(_("Institution Acronym"), blank=True, null=True)

    level_1 = models.TextField(_("Organization Level 1"), blank=True, null=True)

    level_2 = models.TextField(_("Organization Level 2"), blank=True, null=True)

    level_3 = models.TextField(_("Organization Level 3"), blank=True, null=True)

    url = models.URLField("url", blank=True, null=True)

    logo = models.ImageField(_("Logo"), blank=True, null=True)

    panels = [
        FieldPanel("name"),
        FieldPanel("acronym"),
        FieldPanel("institution_type"),
        FieldPanel("location"),
        FieldPanel("level_1"),
        FieldPanel("level_2"),
        FieldPanel("level_3"),
        FieldPanel("url"),
        FieldPanel("logo"),
    ]

    def __unicode__(self):
        return "%s | %s | %s | %s | %s" % (
            self.name,
            self.acronym,
            self.level_1,
            self.level_2,
            self.level_3,
            self.location,
        )

    def __str__(self):
        return "%s | %s | %s | %s | %s" % (
            self.name,
            self.acronym,
            self.level_1,
            self.level_2,
            self.level_3,
            self.location,
        )

    @property
    def data(self):
        d = {"institution__name": self.name, "institution__acronym": self.acronym}
        d.update(self.location.data)
        return d

    @classmethod
    def get(cls, inst_name=None, inst_acronym=None, location=None):
        parms = {}
        if inst_name:
            parms["name__iexact"] = inst_name
        if inst_acronym:
            parms["acronym"] = inst_acronym
        try:
            return cls.objects.get(**parms)
        except cls.MultipleObjectsReturned:
            selected = None
            for item in cls.objects.filter(**parms).iterator():
                if not selected:
                    selected = item
                    continue
                if count(item.data.values(), None) < count(
                    selected.data.values(), None
                ):
                    selected = item
            return selected

    @classmethod
    def get_or_create(
        cls,
        inst_name=None,
        inst_acronym=None,
        level_1=None,
        level_2=None,
        level_3=None,
        location=None,
        user=None,
    ):
        # Institution
        # check if exists the institution
        try:
            return cls.get(
                inst_name=inst_name, inst_acronym=inst_acronym, location=location
            )
        except cls.DoesNotExist:
            institution = cls()
            institution.name = inst_name
            institution.acronym = inst_acronym
            institution.level_1 = level_1
            institution.level_2 = level_2
            institution.level_3 = level_3
            institution.location = location
            institution.creator = user
            institution.save()
            return institution

    base_form_class = InstitutionForm


class InstitutionHistory(models.Model):
    institution = models.ForeignKey(
        "Institution", null=True, blank=True, related_name="+", on_delete=models.CASCADE
    )
    initial_date = models.DateField(_("Initial Date"), null=True, blank=True)
    final_date = models.DateField(_("Final Date"), null=True, blank=True)

    panels = [
        FieldPanel("institution", heading=_("Institution")),
        FieldPanel("initial_date"),
        FieldPanel("final_date"),
    ]
