from django.db import models
from django.utils.translation import gettext_lazy as _

from wagtail.core.models import Orderable
from wagtail.admin.edit_handlers import FieldPanel, InlinePanel
from modelcluster.fields import ParentalKey
from modelcluster.models import ClusterableModel
from wagtailautocomplete.edit_handlers import AutocompletePanel

from core.models import CommonControlField
from institution.models import Institution, InstitutionHistory
from journal.models import Journal

from .forms import ResearcherForm
from . import choices


class Researcher(ClusterableModel, CommonControlField):
    """
    Class that represent the Researcher
    """
    def __unicode__(self):
        return u'%s%s, %s (%s)' % (self.last_name, self.suffix and f" {self.suffix}" or "", self.given_names, self.orcid)

    def __str__(self):
        return u'%s%s, %s (%s)' % (self.last_name, self.suffix and f" {self.suffix}" or "", self.given_names, self.orcid)

    given_names = models.CharField(_('Given names'), max_length=128, blank=False, null=False)
    last_name = models.CharField(_('Last name'), max_length=128, blank=False, null=False)
    suffix = models.CharField(_('Suffix'), max_length=128, blank=True, null=True)
    orcid = models.CharField(_('ORCID'), max_length=128, blank=True, null=True)
    lattes = models.CharField(_('Lattes'), max_length=128, blank=True, null=True)
    gender = models.CharField(_('Gender'), max_length=255, choices=choices.GENDER, null=False, blank=False)
    gender_identification_status = models.CharField(_('Gender identification status'), max_length=255, choices=choices.GENDER_IDENTIFICATION_STATUS, null=False, blank=False)

    panels = [
        FieldPanel('given_names'),
        FieldPanel('last_name'),
        FieldPanel('suffix'),
        FieldPanel('orcid'),
        FieldPanel('lattes'),
        InlinePanel('page_email', label=_('Email')),
        FieldPanel('gender'),
        FieldPanel('gender_identification_status'),
        InlinePanel('affiliation', label=_('Affiliation'))
    ]

    autocomplete_search_field = 'last_name'

    def autocomplete_label(self):
        return str(self)

    base_form_class = ResearcherForm


class FieldEmail(Orderable):
    page = ParentalKey(Researcher, on_delete=models.CASCADE, related_name='page_email')
    email = models.EmailField(_('Email'), max_length=128, blank=True, null=True)


class FieldAffiliation(Orderable, InstitutionHistory):
    page = ParentalKey(Researcher, on_delete=models.CASCADE, related_name='affiliation')


class EditorialBoardMember(models.Model):
    journal = models.ForeignKey(Journal, null=True, blank=True, related_name='+', on_delete=models.CASCADE)
    member = models.ForeignKey(Researcher, null=True, blank=True, related_name='+', on_delete=models.CASCADE)
    role = models.CharField(_('Role'), max_length=255, choices=choices.ROLE, null=False, blank=False)
    initial_year =  models.IntegerField(blank=True, null=True)
    initial_month = models.IntegerField(blank=True, null=True, choices=choices.MONTHS)
    final_year = models.IntegerField(blank=True, null=True)
    final_month = models.IntegerField(blank=True, null=True, choices=choices.MONTHS)

    panels = [
        AutocompletePanel('journal'),
        AutocompletePanel('member'),
        FieldPanel('role'),
        FieldPanel('initial_year'),
        FieldPanel('initial_month'),
        FieldPanel('final_year'),
        FieldPanel('final_month')
    ]
