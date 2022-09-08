from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import CommonControlField
from journal.models import OfficialJournal


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
    year = models.CharField(_('Publication Year'), max_length=4, null=False, blank=False)
    volume = models.CharField(_('Volume'), max_length=255, null=True, blank=True)
    number = models.CharField(_('Number'), max_length=255, null=True, blank=True)
    supplement = models.CharField(_('Supplement'), max_length=255, null=True, blank=True)
