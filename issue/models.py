from django.db import models
from django.utils.translation import gettext_lazy as _

from core.controller import get_flexible_date
from core.models import CommonControlField, FlexibleDate
from journal.models import OfficialJournal

from wagtail.admin.edit_handlers import FieldPanel

from .forms import IssueForm


class Issue(CommonControlField):
    """
    Class that represent Issue
    """

    def __unicode__(self):
        return (u'%s %s %s %s %s' %
                (self.official_journal, self.year,
                 self.volume, self.number, self.supplement,
                 ))

    def __str__(self):
        return (u'%s %s %s %s %s' %
                (self.official_journal, self.year,
                 self.volume, self.number, self.supplement,
                 ))

    official_journal = models.ForeignKey(OfficialJournal, on_delete=models.CASCADE)
    publication_date = models.ForeignKey(
    	FlexibleDate, verbose_name=_('Publication date'), null=True, on_delete=models.SET_NULL)
    volume = models.CharField(_('Volume'), max_length=255, null=True, blank=True)
    number = models.CharField(_('Number'), max_length=255, null=True, blank=True)
    supplement = models.CharField(_('Supplement'), max_length=255, null=True, blank=True)

    panels = [
        FieldPanel('official_journal'),
        FieldPanel('publication_date'),
        FieldPanel('volume'),
        FieldPanel('number'),
        FieldPanel('supplement'),
    ]

    base_form_class = IssueForm

    class Meta:
        indexes = [
            models.Index(fields=['official_journal']),
            models.Index(fields=['publication_date']),
            models.Index(fields=['volume']),
            models.Index(fields=['number']),
            models.Index(fields=['supplement']),
        ]
