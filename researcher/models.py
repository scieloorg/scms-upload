from django.db import models
from django.utils.translation import gettext_lazy as _

from wagtail.admin.edit_handlers import FieldPanel

from core.models import CommonControlField
from institution.models import Institution


class Researcher(CommonControlField):
    """
    Class that represent the Researcher
    """
    def __unicode__(self):
        return u'%s%s, %s (%s)' % (self.surname, self.suffix and f" {self.suffix}" or "", self.given_names, self.orcid)

    def __str__(self):
        return u'%s%s, %s (%s)' % (self.surname, self.suffix and f" {self.suffix}" or "", self.given_names, self.orcid)

    surname = models.CharField(_('Surname'), max_length=128, blank=False, null=False)
    given_names = models.CharField(_('Given names'), max_length=128, blank=False, null=False)
    suffix = models.CharField(_('Suffix'), max_length=128, blank=True, null=True)
    orcid = models.CharField(_('ORCID'), max_length=128, blank=True, null=True)
    email = models.EmailField(_('E-mail'), max_length=128, blank=True, null=True)

    panels = [
        FieldPanel('surname'),
        FieldPanel('given_names'),
        FieldPanel('suffix'),
        FieldPanel('orcid'),
        FieldPanel('email'),
    ]


class ResearcherAffiliation(CommonControlField):
    """
    Class that represents the Researcher + Affiliations
    """
    def __unicode__(self):
        return u'%s %s' % (self.year, self.affiliation)

    def __str__(self):
        return u'%s %s' % (self.year, self.affiliation)

    link_begin_year = models.CharField(_('Begin Year'), max_length=4, blank=True, null=True)
    link_end_year = models.CharField(_('End Year'), max_length=4, blank=True, null=True)
    institution = models.ManyToManyField(Institution)
