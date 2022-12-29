from datetime import datetime

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
from . import exceptions


arg_names = (
    'title',
    'ISSN_electronic',
    'ISSN_print',
    'ISSNL',
)


def _get_args(names, values):
    return {
        k: v
        for k, v in zip(names, values)
        if v
    }


class OfficialJournal(CommonControlField):
    """
    Class that represent the Official Journal
    """

    def __unicode__(self):
        return u'%s' % (self.title)

    def __str__(self):
        return u'%s' % (self.title)

    title = models.CharField(_('Official Title'), max_length=256, null=True, blank=True)
    short_title = models.CharField(_('ISO Short Title'), max_length=256, null=True, blank=True)

    foundation_date = models.CharField(_('Foundation Date'), max_length=25, null=True, blank=True)
    foundation_year = models.IntegerField(_('Foundation Year'), null=True, blank=True)
    foundation_month = models.IntegerField(_('Foundation Month'), null=True, blank=True)
    foundation_day = models.IntegerField(_('Foundation Day'), null=True, blank=True)
    ISSN_print = models.CharField(_('ISSN Print'), max_length=9, null=True, blank=True)
    ISSN_electronic = models.CharField(_('ISSN Electronic'), max_length=9, null=True, blank=True)
    ISSNL = models.CharField(_('ISSNL'), max_length=9, null=True, blank=True)

    autocomplete_search_field = 'title'

    def autocomplete_label(self):
        return self.title

    base_form_class = OfficialJournalForm

    @classmethod
    def get_or_create(cls, title, issn_l, e_issn, print_issn, creator):
        if not any([title, e_issn, print_issn, issn_l]):
            raise exceptions.GetOrCreateOfficialJournalError(
                "collections.get_or_create_official_journal requires title or e_issn or print_issn or issn_l"
            )

        kwargs = _get_args(arg_names, (title, e_issn, print_issn, issn_l))
        try:
            logging.info("Get or create Official Journal {} {} {} {}".format(
                title, issn_l, e_issn, print_issn
            ))
            return cls.objects.get(**kwargs)
        except cls.DoesNotExist:
            official_journal = cls()
            official_journal.title = title
            official_journal.ISSNL = issn_l
            official_journal.ISSN_electronic = e_issn
            official_journal.ISSN_print = print_issn
            official_journal.creator = creator
            official_journal.save()
            logging.info("Created {}".format(official_journal))
            return official_journal
        except Exception as e:
            raise exceptions.GetOrCreateOfficialJournalError(
                _('Unable to get or create official journal {} {} {} {} {} {}').format(
                    title, issn_l, e_issn, print_issn, type(e), e
                )
            )

    def update(
            self,
            user,
            short_title=None,
            foundation_date=None,
            foundation_year=None,
            foundation_month=None,
            foundation_day=None,
            ):
        updated = False
        if short_title and self.short_title != short_title:
            updated = True
            self.short_title = short_title
        if foundation_date and self.foundation_date != foundation_date:
            updated = True
            self.foundation_date = foundation_date
        if foundation_year and self.foundation_year != foundation_year:
            updated = True
            self.foundation_year = foundation_year
        if foundation_month and self.foundation_month != foundation_month:
            updated = True
            self.foundation_month = foundation_month
        if foundation_day and self.foundation_day != foundation_day:
            updated = True
            self.foundation_day = foundation_day
        if updated:
            self.updated = datetime.utcnow()
            self.updated_by = user
            self.save()

    class Meta:
        indexes = [
            models.Index(fields=['title']),
            models.Index(fields=['short_title']),
            models.Index(fields=['foundation_year']),
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

