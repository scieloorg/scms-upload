import logging
from datetime import datetime

from django.db import models
from django.utils.translation import gettext as _
from wagtail.admin.edit_handlers import FieldPanel

from core.models import CommonControlField
from files_storage.models import MinioFile

from . import xml_sps_utils
from . import exceptions


LOGGER = logging.getLogger(__name__)
LOGGER_FMT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def utcnow():
    return datetime.utcnow()
    # return datetime.utcnow().isoformat().replace("T", " ") + "Z"


class XMLJournal(models.Model):
    """
    <journal-meta>
      <journal-id journal-id-type="nlm-ta">J Bras Pneumol</journal-id>
      <journal-id journal-id-type="publisher-id">jbpneu</journal-id>
      <journal-title-group>
        <journal-title>Jornal Brasileiro de Pneumologia</journal-title>
        <abbrev-journal-title abbrev-type="publisher">J. bras. pneumol.</abbrev-journal-title>
      </journal-title-group>
      <issn pub-type="epub">1806-3756</issn>
      <publisher>
        <publisher-name>Sociedade Brasileira de Pneumologia e Tisiologia</publisher-name>
      </publisher>
    </journal-meta>
    """
    issn_electronic = models.CharField(_("issn_epub"), max_length=9, null=True, blank=False)
    issn_print = models.CharField(_("issn_ppub"), max_length=9, null=True, blank=False)

    def __str__(self):
        return f'{self.issn_electronic} {self.issn_print}'

    class Meta:
        unique_together = [
            ['issn_electronic', 'issn_print'],
        ]
        indexes = [
            models.Index(fields=['issn_electronic']),
            models.Index(fields=['issn_print']),
        ]


class XMLIssue(models.Model):
    volume = models.CharField(_("volume"), max_length=10, null=True, blank=False)
    number = models.CharField(_("number"), max_length=10, null=True, blank=False)
    suppl = models.CharField(_("suppl"), max_length=10, null=True, blank=False)
    pub_year = models.IntegerField(_("pub_year"), null=False)
    journal = models.ForeignKey('XMLJournal', on_delete=models.SET_NULL, null=True)

    def __str__(self):
        return f'{self.journal} {self.volume or ""} {self.number or ""} {self.suppl or ""}'

    class Meta:
        unique_together = [
            ['journal', 'pub_year', 'volume', 'number', 'suppl'],
        ]
        indexes = [
            models.Index(fields=['journal']),
            models.Index(fields=['volume']),
            models.Index(fields=['number']),
            models.Index(fields=['suppl']),
            models.Index(fields=['pub_year']),
        ]


class BaseArticle(CommonControlField):
    v3 = models.CharField(_("v3"), max_length=23, null=True, blank=False)
    main_doi = models.CharField(_("main_doi"), max_length=265, null=True, blank=False)
    elocation_id = models.CharField(_("elocation_id"), max_length=23, null=True, blank=False)
    article_titles_texts = models.CharField(_("article_titles_texts"), max_length=64, null=True, blank=False)
    surnames = models.CharField(_("surnames"), max_length=64, null=True, blank=False)
    collab = models.CharField(_("collab"), max_length=64, null=True, blank=False)
    links = models.CharField(_("links"), max_length=64, null=True, blank=False)
    partial_body = models.CharField(_("partial_body"), max_length=64, null=True, blank=False)
    versions = models.ManyToManyField(MinioFile)

    @property
    def latest_version(self):
        if self.versions.count():
            return self.versions.latest('created')

    def add_version(self, version):
        if version:
            if self.latest_version and version.finger_print == self.latest_version.finger_print:
                return
            self.versions.add(version)

    def __str__(self):
        return f'{self.v3}'

    class Meta:
        indexes = [
            models.Index(fields=['v3']),
            models.Index(fields=['main_doi']),
            models.Index(fields=['article_titles_texts']),
            models.Index(fields=['surnames']),
            models.Index(fields=['collab']),
            models.Index(fields=['links']),
            models.Index(fields=['partial_body']),
            models.Index(fields=['elocation_id']),
        ]


class XMLAOPArticle(BaseArticle):
    journal = models.ForeignKey('XMLJournal', on_delete=models.SET_NULL, null=True)
    aop_pid = models.CharField(_("aop_pid"), max_length=23, null=True, blank=False)
    published_in_issue = models.ForeignKey('XMLArticle', on_delete=models.SET_NULL, null=True)

    @property
    def is_aop(self):
        return True

    def __str__(self):
        return f'{self.journal} {self.v3 or ""} {self.uri or ""}'

    class Meta:
        indexes = [
            models.Index(fields=['journal']),
            models.Index(fields=['aop_pid']),
            models.Index(fields=['published_in_issue']),
        ]


class XMLArticle(BaseArticle):
    v2 = models.CharField(_("v2"), max_length=23, null=True, blank=False)
    issue = models.ForeignKey('XMLIssue', on_delete=models.SET_NULL, null=True)
    fpage = models.CharField(_("fpage"), max_length=10, null=True, blank=False)
    fpage_seq = models.CharField(_("fpage_seq"), max_length=10, null=True, blank=False)
    lpage = models.CharField(_("lpage"), max_length=10, null=True, blank=False)

    @property
    def is_aop(self):
        return False

    def __str__(self):
        return f'{self.issue and self.issue.journal or ""} {self.v3 or ""}'

    class Meta:
        indexes = [
            models.Index(fields=['v2']),
            models.Index(fields=['issue']),
            models.Index(fields=['fpage']),
            models.Index(fields=['fpage_seq']),
            models.Index(fields=['lpage']),
        ]
