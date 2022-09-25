from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import CommonControlField
from core.forms import CoreAdminModelForm

from journal.models import OfficialJournal
from issue.models import Issue
from article.models import Article
from .choices import JOURNAL_PUBLICATION_STATUS, WEBSITE_KIND


class Collection(CommonControlField):
    """
    Class that represent the Collection
    """

    def __unicode__(self):
        return u'%s %s' % (self.name, self.acron)

    def __str__(self):
        return u'%s %s' % (self.name, self.acron)

    acron = models.CharField(_('Collection Acronym'), max_length=255, null=True, blank=True)
    name = models.CharField(_('Collection Name'), max_length=255, null=True, blank=True)

    base_form_class = CoreAdminModelForm


class SciELOJournal(CommonControlField):
    """
    Class that represent the Journal in a Collection
    """
    scielo_issn = models.CharField(_('SciELO ISSN'), max_length=9, null=False, blank=False)
    collection = models.ForeignKey(Collection, on_delete=models.CASCADE)
    acron = models.CharField(_('Acronym'), max_length=25, null=True, blank=True)
    title = models.CharField(_('Title'), max_length=255, null=True, blank=True)
    publication_status = models.CharField(
        _('Publication Status'), max_length=10, null=True, blank=True,
        choices=JOURNAL_PUBLICATION_STATUS)

    # TODO acrescentar
    # data de entrada
    # data de saída
    # motivo da saída

    class Meta:
        unique_together = [
            ['collection', 'scielo_issn'],
            ['collection', 'acron'],
        ]
        indexes = [
            models.Index(fields=['acron']),
            models.Index(fields=['collection']),
            models.Index(fields=['scielo_issn']),
            models.Index(fields=['publication_status']),
        ]

    def __unicode__(self):
        return u'%s %s' % (self.collection, self.scielo_issn)

    def __str__(self):
        return u'%s %s' % (self.collection, self.scielo_issn)


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

    class Meta:

        indexes = [
            models.Index(fields=['official_journal']),
        ]


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
    # v30n1 ou 2019nahead
    issue_folder = models.CharField(_('Issue Folder'), max_length=17, null=False, blank=False)
    pub_year = models.CharField(_('Publicatin year'), max_length=4, null=True, blank=True)

    class Meta:
        unique_together = [
            ['scielo_journal', 'issue_pid'],
            ['scielo_journal', 'issue_folder'],
            ['issue_pid', 'issue_folder'],
        ]
        indexes = [
            models.Index(fields=['scielo_journal']),
            models.Index(fields=['issue_pid']),
            models.Index(fields=['issue_folder']),
            models.Index(fields=['pub_year']),
        ]


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

    class Meta:
        indexes = [
            models.Index(fields=['official_issue']),
        ]


class SciELODocument(CommonControlField):
    """
    Class that represent a document in a SciELO Collection
    """

    def __unicode__(self):
        return u'%s %s' % (self.scielo_issue, self.pid)

    def __str__(self):
        return u'%s %s' % (self.scielo_issue, self.pid)

    scielo_issue = models.ForeignKey(SciELOIssue, on_delete=models.CASCADE)
    pid = models.CharField(_('PID'), max_length=23, null=True, blank=True)
    file_id = models.CharField(_('File ID'), max_length=17, null=True, blank=True)

    class Meta:
        unique_together = [
            ['scielo_issue', 'pid'],
            ['scielo_issue', 'file_id'],
            ['pid', 'file_id'],
        ]
        indexes = [
            models.Index(fields=['scielo_issue']),
            models.Index(fields=['pid']),
            models.Index(fields=['file_id']),
        ]


class DocumentInCollections(CommonControlField):
    """
    Class that represent a document and its collections
    """

    def __unicode__(self):
        return u'%s %s' % (self.official_document, " | ".join([str(item) for item in self.scielo_documents]))

    def __str__(self):
        return u'%s %s' % (self.official_document, " | ".join([str(item) for item in self.scielo_documents]))

    official_document = models.ForeignKey(Article, on_delete=models.CASCADE, null=True, blank=True)
    scielo_documents = models.ManyToManyField(SciELODocument)

    class Meta:
        indexes = [
            models.Index(fields=['official_document']),
        ]


class NewWebSiteConfiguration(CommonControlField):
    url = models.CharField(
        _('New website url'), max_length=255, null=True, blank=True)
    db_uri = models.CharField(
        _('Mongodb Info'), max_length=255, null=True, blank=True,
        help_text=_('mongodb://login:password@host:port/database'))

    def __str__(self):
        return f"{self.url}"

    class Meta:
        indexes = [
            models.Index(fields=['url']),
        ]

    base_form_class = CoreAdminModelForm


class FilesStorageConfiguration(CommonControlField):

    host = models.CharField(
        _('Host'), max_length=255, null=True, blank=True)
    bucket_root = models.CharField(
        _('Bucket root'), max_length=255, null=True, blank=True)
    bucket_subdir = models.CharField(
        _('Bucket subdir'), max_length=64, null=True, blank=True)
    bucket_public_subdir = models.CharField(
        _('Bucket public subdir'), max_length=64, null=True, blank=True)
    bucket_migration_subdir = models.CharField(
        _('Bucket migration subdir'), max_length=64, null=True, blank=True)
    bucket_temp_subdir = models.CharField(
        _('Bucket temp subdir'), max_length=64, null=True, blank=True)
    bucket_versions_subdir = models.CharField(
        _('Bucket versions subdir'), max_length=64, null=True, blank=True)
    access_key = models.CharField(
        _('Access key'), max_length=255, null=True, blank=True)
    secret_key = models.CharField(
        _('Secret key'), max_length=255, null=True, blank=True)
    secure = models.BooleanField(_('Secure'), default=True)

    def __str__(self):
        return f"{self.host} {self.bucket_root}"

    class Meta:
        unique_together = [
            ['host', 'bucket_root'],
        ]
        indexes = [
            models.Index(fields=['host']),
            models.Index(fields=['bucket_root']),
        ]

    base_form_class = CoreAdminModelForm


class ClassicWebsiteConfiguration(CommonControlField):

    collection = models.ForeignKey(Collection, on_delete=models.CASCADE)

    title_path = models.CharField(
        _('Title path'), max_length=255, null=True, blank=True,
        help_text=_('Title path: title.id path or title.mst path without extension'))
    issue_path = models.CharField(
        _('Issue path'), max_length=255, null=True, blank=True,
        help_text=_('Issue path: issue.id path or issue.mst path without extension'))
    serial_path = models.CharField(
        _('Serial path'), max_length=255, null=True, blank=True,
        help_text=_('Serial path'))
    cisis_path = models.CharField(
        _('Cisis path'), max_length=255, null=True, blank=True,
        help_text=_('Cisis path where there are CISIS utilities such as mx and i2id'))
    bases_work_path = models.CharField(
        _('Bases work path'), max_length=255, null=True, blank=True,
        help_text=_('Bases work path'))
    bases_pdf_path = models.CharField(
        _('Bases pdf path'), max_length=255, null=True, blank=True,
        help_text=_('Bases translation path'))
    bases_translation_path = models.CharField(
        _('Bases translation path'), max_length=255, null=True, blank=True,
        help_text=_('Bases translation path'))
    bases_xml_path = models.CharField(
        _('Bases XML path'), max_length=255, null=True, blank=True,
        help_text=_('Bases XML path'))
    htdocs_img_revistas_path = models.CharField(
        _('Htdocs img revistas path'), max_length=255, null=True, blank=True,
        help_text=_('Htdocs img revistas path'))

    def __str__(self):
        return f"{self.collection}"

    class Meta:
        indexes = [
            models.Index(fields=['collection']),
        ]

    base_form_class = CoreAdminModelForm
