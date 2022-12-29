import logging

from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import CommonControlField, IssuePublicationDate
from journal.models import OfficialJournal

from wagtailautocomplete.edit_handlers import AutocompletePanel
from wagtail.admin.edit_handlers import FieldPanel

from .forms import IssueForm
from . import exceptions


arg_names = (
    'official_journal',
    'volume',
    'number',
    'supplement',
)


def _get_args(names, values):
    return {
        k: v
        for k, v in zip(names, values)
        if v
    }


class Issue(CommonControlField, IssuePublicationDate):
    """
    Class that represent Issue
    """

    def __unicode__(self):
        return (u'%s %s %s %s %s' % (
            self.official_journal,
            self.publication_year,
            self.volume or '',
            self.number or '',
            self.supplement or '',
        ))

    def __str__(self):
        return (u'%s %s %s %s %s' % (
            self.official_journal,
            self.publication_year,
            self.volume or '',
            self.number or '',
            self.supplement or '',
        ))

    official_journal = models.ForeignKey(OfficialJournal, on_delete=models.CASCADE)
    volume = models.CharField(_('Volume'), max_length=255, null=True, blank=True)
    number = models.CharField(_('Number'), max_length=255, null=True, blank=True)
    supplement = models.CharField(_('Supplement'), max_length=255, null=True, blank=True)

    autocomplete_search_field = 'official_journal__title'

    def autocomplete_label(self):
        return self.__str__()

    @classmethod
    def get_or_create(
            cls,
            official_journal,
            year,
            volume,
            number,
            supplement,
            creator,
            initial_month_name=None,
            initial_month_number=None,
            final_month_name=None,
            ):
        values = (official_journal, volume, number, supplement, )
        if not any(values):
            raise exceptions.GetOrCreateIssueError(
                _("collections.get_or_create_official_issue requires "
                  "official_journal or volume or number or supplement")
            )

        kwargs = _get_args(arg_names, values)
        try:
            logging.info("Get or create official issue")
            logging.info(kwargs)
            return cls.objects.get(**kwargs)
        except cls.DoesNotExist:
            issue = cls()
            issue.creator = creator
            issue.official_journal = official_journal
            issue.volume = volume
            issue.number = number
            issue.supplement = supplement
            issue.publication_year = year
            issue.publication_initial_month_number = initial_month_number
            issue.publication_initial_month_name = initial_month_name
            issue.publication_final_month_name = final_month_name
            issue.save()
            logging.info("Created official issue")
            return issue
        except Exception as e:
            raise exceptions.GetOrCreateIssueError(
                _('Unable to get or create official issue {} {} {}').format(
                    str(kwargs), type(e), e
                )
            )

    panels = [
        AutocompletePanel('official_journal'),
        FieldPanel('publication_date_text'),
        FieldPanel('publication_year'),
        FieldPanel('publication_initial_month_number'),
        FieldPanel('publication_initial_month_name'),
        FieldPanel('publication_final_month_number'),
        FieldPanel('publication_final_month_name'),
        FieldPanel('volume'),
        FieldPanel('number'),
        FieldPanel('supplement'),
    ]

    base_form_class = IssueForm

    class Meta:
        unique_together = [
            [
                'official_journal',
                'publication_year',
                'volume',
                'number',
                'supplement'
            ],
            [
                'official_journal',
                'volume',
                'number',
                'supplement'
            ],
        ]
        indexes = [
            models.Index(fields=['official_journal']),
            models.Index(fields=['publication_year']),
            models.Index(fields=['volume']),
            models.Index(fields=['number']),
            models.Index(fields=['supplement']),
        ]
