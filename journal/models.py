from django.db import models
from django.utils.translation import gettext_lazy as _

from wagtail.core.models import Orderable
from wagtail.admin.edit_handlers import (
    FieldPanel, InlinePanel,
    TabbedInterface, ObjectList,
)
from wagtail.images.edit_handlers import ImageChooserPanel

from modelcluster.fields import ParentalKey
from modelcluster.models import ClusterableModel

from core.models import CommonControlField, RichTextWithLang

from institution.models import InstitutionHistory
from . import choices
from .forms import OfficialJournalForm


class OfficialJournal(CommonControlField):
    """
    Class that represent the Official Journal
    """

    def __unicode__(self):
        return u'%s' % (self.title)

    def __str__(self):
        return u'%s' % (self.title)

    title = models.CharField(_('Official Title'), max_length=256, null=True, blank=True)
    title_iso = models.CharField(_('Title ISO'), max_length=256, null=True, blank=True)
    short_title = models.CharField(_('Short Title'), max_length=256, null=True, blank=True)
    nlm_title = models.CharField(_('NLM Title'), max_length=256, null=True, blank=True)

    foundation_date = models.CharField(_('Foundation Date'), max_length=25, null=True, blank=True)
    ISSN_print = models.CharField(_('ISSN Print'), max_length=9, null=True, blank=True)
    ISSN_electronic = models.CharField(_('ISSN Electronic'), max_length=9, null=True, blank=True)
    ISSNL = models.CharField(_('ISSNL'), max_length=9, null=True, blank=True)

    autocomplete_search_field = 'title'

    def autocomplete_label(self):
        return self.title

    base_form_class = OfficialJournalForm

    class Meta:
        indexes = [
            models.Index(fields=['title']),
            models.Index(fields=['title_iso']),
            models.Index(fields=['short_title']),
            models.Index(fields=['nlm_title']),
            models.Index(fields=['foundation_date']),
            models.Index(fields=['ISSN_print']),
            models.Index(fields=['ISSN_electronic']),
            models.Index(fields=['ISSNL']),
        ]


class NonOfficialJournalTitle(ClusterableModel, CommonControlField):

    def __unicode__(self):
        return u'%s' % (self.official_journal.title)

    def __str__(self):
        return u'%s' % (self.official_journal.title)

    official_journal = models.ForeignKey('OfficialJournal', null=True, blank=True, related_name='OfficialJournal', on_delete=models.CASCADE)

    panels = [
        FieldPanel('official_journal'),
        InlinePanel('page_non_official_title', label=_('Non Official Journal Title'))
    ]

    base_form_class = OfficialJournalForm


class NonOfficialTitle(Orderable):
   page = ParentalKey(NonOfficialJournalTitle, related_name='page_non_official_title')
   non_official_journal_title = models.CharField(_('Non Official Journal Title'), max_length=255, null=False, blank=False)


class JournalMission(ClusterableModel):
    official_journal = models.ForeignKey('OfficialJournal', null=True, blank=True, related_name='JournalMission_OfficialJournal', on_delete=models.CASCADE)

    panels=[
        FieldPanel('official_journal'),
        InlinePanel('mission', label=_('Mission'), classname="collapsed")
    ]


class FieldMission(Orderable, RichTextWithLang):
    page = ParentalKey(JournalMission, on_delete=models.CASCADE, related_name='mission')
    def __unicode__(self):
        return u'%s %s' % (self.text, self.language)

    def __str__(self):
        return u'%s %s' % (self.text, self.language)
        

class SocialNetwork(models.Model):
    name = models.CharField(_('Name'), max_length=255, choices=choices.SOCIAL_NETWORK_NAMES, null=False, blank=False)
    url = models.URLField(_("URL"), max_length=255, null=True, blank=False)

    panels=[
        FieldPanel('name'),
        FieldPanel('url')
    ]

    class Meta:
        abstract = True


class Journal(ClusterableModel, SocialNetwork):
    short_title = models.CharField(_('Short Title'), max_length=100, null=True, blank=True)
    official_journal = models.ForeignKey('OfficialJournal', null=True, blank=True, related_name='+', on_delete=models.CASCADE)
    logo = models.ForeignKey(
        'wagtailimages.Image',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+'
    )
    submission_online_url =  models.URLField(_("Submission online URL"), max_length=255, null=True, blank=True)

    panels_identification = [
        FieldPanel('official_journal'),
        FieldPanel('short_title'),
    ]

    panels_mission = [
        InlinePanel('mission', label=_('Mission'), classname="collapsed"),
    ]

    panels_owner = [
        InlinePanel('owner', label=_('Owner'), classname="collapsed"),
    ]

    panels_editorial_manager = [
        InlinePanel('editorialmanager', label=_('Editorial Manager'), classname="collapsed"),
    ]

    panels_publisher = [
        InlinePanel('publisher', label=_('Publisher'), classname="collapsed"),
    ]

    panels_sponsor = [
        InlinePanel('sponsor', label=_('Sponsor'), classname="collapsed"),
    ]

    panels_website = [
        ImageChooserPanel('logo', heading=_('Logo')),
        FieldPanel('submission_online_url'),
        InlinePanel('journalsocialnetwork', label=_('Social Network'))
    ]

    edit_handler = TabbedInterface(
        [
            ObjectList(panels_identification, heading=_('Identification')),
            ObjectList(panels_mission, heading=_('Missions')),
            ObjectList(panels_owner, heading=_('Owners')),
            ObjectList(panels_editorial_manager, heading=_('Editorial Manager')),
            ObjectList(panels_publisher, heading=_('Publisher')),
            ObjectList(panels_sponsor, heading=_('Sponsor')),
            ObjectList(panels_website, heading=_('Website')),
        ]
    )

    autocomplete_search_field = 'official_journal__title'

    def autocomplete_label(self):
        return str(self.official_journal__title)


class Mission(Orderable, RichTextWithLang):
    page = ParentalKey(Journal, on_delete=models.CASCADE, related_name='mission')


class Owner(Orderable, InstitutionHistory):
    page = ParentalKey(Journal, on_delete=models.CASCADE, related_name='owner')


class EditorialManager(Orderable, InstitutionHistory):
    page = ParentalKey(Journal, on_delete=models.CASCADE, related_name='editorialmanager')


class Publisher(Orderable, InstitutionHistory):
    page = ParentalKey(Journal, on_delete=models.CASCADE, related_name='publisher')


class Sponsor(Orderable, InstitutionHistory):
    page = ParentalKey(Journal, on_delete=models.CASCADE, related_name='sponsor')


class JournalSocialNetwork(Orderable, SocialNetwork):
    page = ParentalKey(Journal, on_delete=models.CASCADE, related_name='journalsocialnetwork')

