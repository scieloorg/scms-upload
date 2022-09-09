from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import CommonControlField
from journal.models import OfficialJournal
from issue.models import Issue


class Collection(CommonControlField):
    """
    Class that represent the Collection
    """

    def __unicode__(self):
        return u'%s' % self.name

    def __str__(self):
        return u'%s' % self.name

    name = models.CharField(_('Collection Name'), max_length=255, null=False, blank=False)


class SciELOJournal(CommonControlField):
    """
    Class that represent the Journal in a Collection
    """

    # TODO futuramente ter um formulário para gerir os dados

    def __unicode__(self):
        return u'%s %s' % (self.collection, self.scielo_issn)

    def __str__(self):
        return u'%s %s' % (self.collection, self.scielo_issn)

    scielo_issn = models.CharField(_('SciELO ISSN'), max_length=9, null=False, blank=False)
    collection = models.ForeignKey(Collection, on_delete=models.CASCADE)
    acron = models.CharField(_('Acronym'), max_length=25, null=True, blank=True)
    title = models.CharField(_('Title'), max_length=255, null=True, blank=True)

    # TODO acrescentar
    # data de entrada
    # data de saída
    # motivo da saída


class JournalCollections(CommonControlField):
    """
    Class that represent the journal and its collections
    """

    def __unicode__(self):
        return u'%s %s' % (self.official_issue, " | ".join([str(item) for item in self.scielo_journals]))

    def __str__(self):
        return u'%s %s' % (self.official_issue, " | ".join([str(item) for item in self.scielo_journals]))

    official_journal = models.ForeignKey(OfficialJournal, on_delete=models.CASCADE)
    scielo_journals = models.ManyToManyField(SciELOJournal)


class SciELOIssue(CommonControlField):
    """
    Class that represent an issue in a SciELO Collection
    """

    def __unicode__(self):
        return u'%s %s' % (self.scielo_journal, self.issue_pid)

    def __str__(self):
        return u'%s %s' % (self.scielo_journal, self.issue_pid)

    scielo_journal = models.ForeignKey(SciELOJournal, on_delete=models.CASCADE)
    issue_pid = models.CharField(_('Issue PID'), max_length=17, null=False, blank=False)
    issue_folder = models.CharField(_('Issue Folder'), max_length=17, null=False, blank=False)


class IssueInCollections(CommonControlField):
    """
    Class that represent an issue and its collections
    """

    def __unicode__(self):
        return u'%s %s' % (self.official_issue, " | ".join([str(item) for item in self.scielo_issues]))

    def __str__(self):
        return u'%s %s' % (self.official_issue, " | ".join([str(item) for item in self.scielo_issues]))

    official_issue = models.ForeignKey(Issue, on_delete=models.CASCADE)
    scielo_issues = models.ManyToManyField(SciELOIssue)


class SciELODocument(CommonControlField):
    """
    Class that represent a document in a SciELO Collection
    """

    def __unicode__(self):
        return u'%s %s' % (self.scielo_issue, self.pid)

    def __str__(self):
        return u'%s %s' % (self.scielo_issue, self.pid)

    # official_doc = models.ForeignKey(Article, on_delete=models.CASCADE)
    scielo_issue = models.ForeignKey(SciELOIssue, on_delete=models.CASCADE)
    pid = models.CharField(_('PID'), max_length=17, null=True, blank=True)
    file_id = models.CharField(_('File ID'), max_length=17, null=True, blank=True)

