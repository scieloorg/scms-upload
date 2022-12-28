import logging

from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import CommonControlField
from core.forms import CoreAdminModelForm

from journal.models import OfficialJournal
from issue.models import Issue
from article.models import Article
from .choices import JOURNAL_AVAILABILTY_STATUS, WEBSITE_KIND


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

    @classmethod
    def get_or_create(cls, acron, name, user):
        try:
            return cls.objects.get(acron=acron)
        except cls.DoesNotExist:
            collection = cls()
            collection.acron = acron
            collection.name = name
            collection.creator = user
            collection.save()
            return collection


class SciELOJournal(CommonControlField):
    """
    Class that represents journals data in a SciELO Collection context
    Its attributes are related to the journal in collection
    For official data, use Journal model
    """
    collection = models.ForeignKey(Collection, on_delete=models.CASCADE)
    scielo_issn = models.CharField(_('SciELO ISSN'), max_length=9, null=False, blank=False)
    acron = models.CharField(_('Acronym'), max_length=25, null=True, blank=True)
    title = models.CharField(_('Title'), max_length=255, null=True, blank=True)
    availability_status = models.CharField(
        _('Availability Status'), max_length=10, null=True, blank=True,
        choices=JOURNAL_AVAILABILTY_STATUS)
    official_journal = models.ForeignKey(
        OfficialJournal, on_delete=models.SET_NULL, null=True)

    class Meta:
        unique_together = [
            ['collection', 'scielo_issn'],
            ['collection', 'acron'],
        ]
        indexes = [
            models.Index(fields=['acron']),
            models.Index(fields=['collection']),
            models.Index(fields=['scielo_issn']),
            models.Index(fields=['availability_status']),
            models.Index(fields=['official_journal']),
        ]

    def __unicode__(self):
        return u'%s %s' % (self.collection, self.scielo_issn)

    def __str__(self):
        return u'%s %s' % (self.collection, self.scielo_issn)


class SciELOIssue(CommonControlField):
    """
    Class that represents an issue in a SciELO Collection
    Its attributes are related to the issue in collection
    For official data, use Issue model
    """

    def __unicode__(self):
        return u'%s %s' % (self.scielo_journal, self.issue_pid)

    def __str__(self):
        return u'%s %s' % (self.scielo_journal, self.issue_pid)

    scielo_journal = models.ForeignKey(
        SciELOJournal, on_delete=models.SET_NULL, null=True)
    issue_pid = models.CharField(_('Issue PID'), max_length=23, null=False, blank=False)
    # v30n1 ou 2019nahead
    issue_folder = models.CharField(_('Issue Folder'), max_length=23, null=False, blank=False)
    official_issue = models.ForeignKey(
        Issue, on_delete=models.SET_NULL, null=True)

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
            models.Index(fields=['official_issue']),
        ]


class SciELODocument(CommonControlField):
    """
    Class that represents a document in a SciELO Collection
    Its attributes are related to the document in collection
    For official data, use Article model
    """

    def __unicode__(self):
        return u'%s %s' % (self.scielo_issue, self.pid)

    def __str__(self):
        return u'%s %s' % (self.scielo_issue, self.pid)

    scielo_issue = models.ForeignKey(SciELOIssue, on_delete=models.CASCADE)
    pid = models.CharField(_('PID'), max_length=23, null=True, blank=True)
    # filename without extension
    key = models.CharField(_('File key'), max_length=50, null=True, blank=True)
    official_document = models.ForeignKey(Article, on_delete=models.SET_NULL, null=True, blank=True)

    xml_files = models.ManyToManyField('XMLFile', null=True, related_name='xml_files')
    renditions_files = models.ManyToManyField('FileWithLang', null=True, related_name='renditions_files')
    html_files = models.ManyToManyField('SciELOHTMLFile', null=True, related_name='html_files')

    class Meta:
        unique_together = [
            ['scielo_issue', 'pid'],
            ['scielo_issue', 'key'],
            ['pid', 'key'],
        ]
        indexes = [
            models.Index(fields=['scielo_issue']),
            models.Index(fields=['pid']),
            models.Index(fields=['key']),
            models.Index(fields=['official_document']),
        ]


class SciELOFile(models.Model):
    scielo_issue = models.ForeignKey(SciELOIssue, on_delete=models.CASCADE)
    # filename without extension
    key = models.CharField(_('File key'), max_length=255, null=True, blank=True)
    relative_path = models.CharField(_('Relative Path'), max_length=255, null=True, blank=True)
    name = models.CharField(_('Filename'), max_length=255, null=False, blank=False)
    uri = models.URLField(_('URI'), max_length=255, null=True)
    object_name = models.CharField(_('Object name'), max_length=255, null=True)

    def __str__(self):
        return f"{self.scielo_issue} {self.name}"

    @classmethod
    def create_or_update(cls, item):
        logging.info("Register stored classic file {}".format(item))

        params = {
            k: item[k]
            for k in item.keys()
            if hasattr(cls, k)
        }
        params['scielo_issue'] = scielo_issue

        try:
            cls.objects.filter(relative_path=item['relative_path']).delete()
        except Exception as e:
            logging.info(e)

        try:
            return cls.objects.get(**params)
        except cls.DoesNotExist:
            file = cls(**params)
            file.save()
            return file

    class Meta:

        indexes = [
            models.Index(fields=['key']),
            models.Index(fields=['relative_path']),
            models.Index(fields=['name']),
            models.Index(fields=['object_name']),
            models.Index(fields=['scielo_issue']),
        ]


class FileWithLang(SciELOFile):

    lang = models.CharField(
        _('Language'), max_length=4, null=False, blank=False)

    def __str__(self):
        return f"{self.scielo_issue} {self.name} {self.lang}"

    class Meta:

        indexes = [
            models.Index(fields=['lang']),
        ]


class AssetFile(SciELOFile):
    is_supplementary_material = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.scielo_issue} {self.name} {self.is_supplementary_material}"

    class Meta:

        indexes = [
            models.Index(fields=['is_supplementary_material']),
        ]


class XMLFile(FileWithLang):
    assets_files = models.ManyToManyField('AssetFile')
    languages = models.JSONField(null=True)
    v3 = models.CharField(_('V3'), max_length=23, null=True, blank=True)
    public_uri = models.URLField(_('Public URI'), max_length=255, null=True)
    public_object_name = models.CharField(_('Public object name'), max_length=255, null=True)

    def __str__(self):
        return f"{self.scielo_issue} {self.name} {self.lang} {self.languages}"

    class Meta:
        indexes = [
            models.Index(fields=['v3']),
        ]


class SciELOHTMLFile(FileWithLang):
    part = models.CharField(
        _('Part'), max_length=6, null=False, blank=False)
    assets_files = models.ManyToManyField('AssetFile')

    def __str__(self):
        return f"{self.scielo_issue} {self.name} {self.lang} {self.part}"

    class Meta:

        indexes = [
            models.Index(fields=['part']),
        ]


class NewWebSiteConfiguration(CommonControlField):
    url = models.CharField(
        _('New website url'), max_length=255, null=True, blank=True)
    db_uri = models.CharField(
        _('Mongodb Info'), max_length=255, null=True, blank=True,
        help_text=_('mongodb://login:password@host:port/database'))

    def __str__(self):
        return f"{self.url}"

    @classmethod
    def get_or_create(cls, url, db_uri=None, creator=None):
        try:
            return cls.objects.get(url=url)
        except cls.DoesNotExist:
            new_website_config = cls()
            new_website_config.db_uri = db_uri
            new_website_config.url = url
            new_website_config.creator = creator
            new_website_config.save()
            return new_website_config

    class Meta:
        indexes = [
            models.Index(fields=['url']),
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

    @classmethod
    def get_or_create(cls, collection, config, user):
        try:
            return cls.objects.get(collection=collection)
        except cls.DoesNotExist:
            classic_website = cls()
            classic_website.collection = collection
            classic_website.title_path = config['title_path']
            classic_website.issue_path = config['issue_path']
            classic_website.serial_path = config['SERIAL_PATH']
            classic_website.cisis_path = config.get('CISIS_PATH')
            classic_website.bases_work_path = config['BASES_WORK_PATH']
            classic_website.bases_pdf_path = config['BASES_PDF_PATH']
            classic_website.bases_translation_path = (
                config['BASES_TRANSLATION_PATH']
            )
            classic_website.bases_xml_path = (
                config['BASES_XML_PATH']
            )
            classic_website.htdocs_img_revistas_path = (
                config['HTDOCS_IMG_REVISTAS_PATH']
            )
            classic_website.creator = user
            classic_website.save()
            return classic_website

    class Meta:
        indexes = [
            models.Index(fields=['collection']),
        ]

    base_form_class = CoreAdminModelForm
