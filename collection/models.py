import logging
from datetime import datetime
from copy import deepcopy

from django.db import models
from django.utils.translation import gettext_lazy as _
from packtools.sps.models.article_renditions import ArticleRenditions
from packtools.sps.models.related_articles import RelatedItems
from packtools.sps.models.article_assets import (
    ArticleAssets,
    SupplementaryMaterials,
)
from packtools.sps.models.article_ids import ArticleIds
from core.models import CommonControlField
from core.forms import CoreAdminModelForm

from journal.models import OfficialJournal
from issue.models import Issue
from article.models import Article
from .choices import JOURNAL_AVAILABILTY_STATUS, WEBSITE_KIND
from . import exceptions
from libs.xml_sps_utils import get_xml_with_pre_from_uri
from files_storage.models import MinioFile


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
    def get_or_create(cls, acron, creator, name=None):
        try:
            return cls.objects.get(acron=acron)
        except cls.DoesNotExist:
            collection = cls()
            collection.acron = acron
            collection.name = name
            collection.creator = creator
            collection.save()
            return collection
        except Exception as e:
            raise exceptions.GetOrCreateCollectionError(
                _('Unable to get_or_create_collection {} {} {}').format(
                    acron, type(e), e
                )
            )


class SciELOJournal(CommonControlField):
    """
    Class that represents journals data in a SciELO Collection context
    Its attributes are related to the journal in collection
    For official data, use Journal model
    """
    collection = models.ForeignKey(Collection, on_delete=models.SET_NULL, null=True, blank=True)
    scielo_issn = models.CharField(_('SciELO ISSN'), max_length=9, null=False, blank=False)
    acron = models.CharField(_('Acronym'), max_length=25, null=True, blank=True)
    title = models.CharField(_('Title'), max_length=255, null=True, blank=True)
    availability_status = models.CharField(
        _('Availability Status'), max_length=10, null=True, blank=True,
        choices=JOURNAL_AVAILABILTY_STATUS)
    official_journal = models.ForeignKey(
        OfficialJournal, on_delete=models.SET_NULL, null=True, blank=True)

    @classmethod
    def get_or_create(cls, collection_acron, scielo_issn, creator):
        try:
            logging.info("Create or Get SciELOJournal {} {}".format(
                collection_acron, scielo_issn))
            return cls.objects.get(
                collection__acron=collection_acron,
                scielo_issn=scielo_issn,
            )
        except cls.DoesNotExist:
            scielo_journal = cls()
            scielo_journal.collection = Collection.get_or_create(
                collection_acron, creator
            )
            scielo_journal.scielo_issn = scielo_issn
            scielo_journal.creator = creator
            scielo_journal.save()
            logging.info("Created SciELOJournal {}".format(scielo_journal))
            return scielo_journal
        except Exception as e:
            raise exceptions.GetOrCreateScieloJournalError(
                _('Unable to get_or_create_scielo_journal {} {} {} {}').format(
                    collection_acron, scielo_issn, type(e), e
                )
            )

    @classmethod
    def get(cls, collection_acron, scielo_issn):
        try:
            return cls.objects.get(
                collection__acron=collection_acron,
                scielo_issn=scielo_issn,
            )
        except Exception as e:
            raise exceptions.GetSciELOJournalError(
                _('Unable to get_scielo_journal {} {} {} {}').format(
                    collection_acron, scielo_issn, type(e), e
                )
            )

    def update(
            self, updated_by,
            acron=None, title=None, availability_status=None,
            official_journal=None,
            ):
        try:
            updated = False
            if acron and self.acron != acron:
                self.acron = acron
                updated = True
            if title and self.title != title:
                self.title = title
                updated = True
            if availability_status and self.availability_status != availability_status:
                self.availability_status = availability_status
                updated = True
            if official_journal and self.official_journal != official_journal:
                self.official_journal = official_journal
                updated = True
            if updated:
                self.updated_by = updated_by
                self.updated = datetime.utcnow()
                self.save()
        except Exception as e:
            params = (
                updated_by, acron, title,
                availability_status, official_journal)
            raise exceptions.UpdateSciELOJournalError(
                _("Unable to update SciELOJournal %s %s %s") %
                (str(params), type(e), str(e))
            )

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
        SciELOJournal, on_delete=models.SET_NULL, null=True, blank=True)
    issue_pid = models.CharField(_('Issue PID'), max_length=23, null=False, blank=False)
    # v30n1 ou 2019nahead
    issue_folder = models.CharField(_('Issue Folder'), max_length=23, null=False, blank=False)
    official_issue = models.ForeignKey(
        Issue, on_delete=models.SET_NULL, null=True, blank=True)

    @classmethod
    def get(self, issue_pid, issue_folder):
        try:
            return SciELOIssue.objects.get(
                issue_pid=issue_pid,
                issue_folder=issue_folder,
            )
        except Exception as e:
            raise exceptions.GetOrCreateScieloIssueError(
                _('Unable to get_scielo_issue {} {} {} {}').format(
                    issue_pid, issue_folder, type(e), e
                )
            )

    @classmethod
    def get_or_create(cls, scielo_journal, issue_pid, issue_folder, creator):
        try:
            logging.info("Get or create SciELOIssue {} {} {}".format(scielo_journal, issue_pid, issue_folder))
            return cls.objects.get(
                scielo_journal=scielo_journal,
                issue_pid=issue_pid,
                issue_folder=issue_folder,
            )
        except SciELOIssue.DoesNotExist:
            scielo_issue = cls()
            scielo_issue.scielo_journal = scielo_journal
            scielo_issue.issue_folder = issue_folder
            scielo_issue.issue_pid = issue_pid
            scielo_issue.creator = creator
            scielo_issue.save()
            logging.info("Created {}".format(scielo_issue))
            return scielo_issue
        except Exception as e:
            raise exceptions.GetOrCreateScieloIssueError(
                _('Unable to get_or_create_scielo_issue {} {} {} {}').format(
                    scielo_journal, issue_pid, type(e), e
                )
            )

    def update(
            self, updated_by,
            official_issue=None,
            ):
        try:
            updated = False
            if official_issue and self.official_issue != official_issue:
                self.official_issue = official_issue
                updated = True
            if updated:
                self.updated_by = updated_by
                self.updated = datetime.utcnow()
                self.save()
        except Exception as e:
            params = (updated_by, official_issue)
            raise exceptions.UpdateSciELOJournalError(
                _("Unable to update SciELOJournal %s %s %s") %
                (str(params), type(e), str(e))
            )

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

    scielo_issue = models.ForeignKey(SciELOIssue, on_delete=models.SET_NULL, null=True, blank=True)
    pid = models.CharField(_('PID'), max_length=23, null=True, blank=True)
    # filename without extension
    key = models.CharField(_('File key'), max_length=50, null=True, blank=True)
    official_document = models.ForeignKey(Article, on_delete=models.SET_NULL, null=True, blank=True)

    xml_files = models.ManyToManyField('XMLFile', related_name='xml_files')
    rendition_files = models.ManyToManyField('FileWithLang', related_name='rendition_files')
    html_files = models.ManyToManyField('SciELOHTMLFile', related_name='html_files')

    def get_xml_with_pre_with_remote_assets(self, issue_assets_uris):
        for xml_file in self.xml_files.iterator():
            return xml_file.get_xml_with_pre_with_remote_assets(
                issue_assets_uris)

    @classmethod
    def get(cls, pid, key):
        try:
            return cls.objects.get(
                pid=pid,
                key=key,
            )
        except Exception as e:
            raise exceptions.GetSciELODocumentError(
                _('Unable to get_scielo_document {} {} {} {}').format(
                    pid, key, type(e), e
                )
            )

    @classmethod
    def get_or_create(cls, scielo_issue, pid, key, creator):
        try:
            logging.info("Get or create SciELODocument {} {} {}".format(
                scielo_issue, pid, key
            ))
            return cls.objects.get(
                scielo_issue=scielo_issue,
                pid=pid,
                key=key,
            )
        except cls.DoesNotExist:
            scielo_document = cls()
            scielo_document.scielo_issue = scielo_issue
            scielo_document.pid = pid
            scielo_document.key = key
            scielo_document.creator = creator
            scielo_document.save()
            logging.info("Created {}".format(scielo_document))
            return scielo_document
        except Exception as e:
            raise exceptions.GetOrCreateScieloDocumentError(
                _('Unable to get_or_create_scielo_document {} {} {} {}').format(
                    scielo_issue, pid, type(e), e
                )
            )

    def set_rendition_files(self, files, update_by):
        self.rendition_files.set(files)
        self.updated_by = update_by
        self.update = datetime.utcnow()
        self.save()

    def set_xml_files(self, files, update_by):
        self.xml_files.set(files)
        self.updated_by = update_by
        self.update = datetime.utcnow()
        self.save()

    def set_html_files(self, files, update_by):
        self.html_files.set(files)
        self.updated_by = update_by
        self.update = datetime.utcnow()
        self.save()

    def set_langs(self):
        for xml_file in self.xml_files.iterator():
            xml_file.set_langs()

    def add_assets(self, issue_assets_dict):
        for xml_file in self.xml_files.iterator():
            xml_file.add_assets(issue_assets_dict)

    @property
    def xml_files_with_lang(self):
        if not hasattr(self, '_xml_with_pre_and_with_lang') or not self._xml_with_pre_and_with_lang:
            self._xml_with_pre_and_with_lang = {}
            for xml_file in self.xml_files:
                self._xml_with_pre_and_with_lang[xml_file.lang] = xml_file
        return self._xml_with_pre_and_with_lang

    @property
    def text_langs(self):
        if not hasattr(self, '_text_langs') or not self._text_langs:
            self._text_langs = [
                {"lang": lang}
                for lang in self.xml_files_with_lang.keys()
            ]
        return self._text_langs

    @property
    def related_items(self):
        if not hasattr(self, '_related_items') or not self._related_items:
            items = []
            for lang, xml_file in self.xml_files_with_lang.items():
                items.extend(xml_file.related_articles)
            self._related_items = items
        return self._related_items

    @property
    def supplementary_materials(self):
        if not hasattr(self, '_supplementary_materials') or not self._supplementary_materials:
            items = []
            for lang, xml_file in self.xml_files_with_lang.items():
                items.extend(xml_file.supplementary_materials)
            self._supplementary_materials = items
        return self._supplementary_materials

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
    scielo_issue = models.ForeignKey(SciELOIssue, on_delete=models.SET_NULL, null=True, blank=True)
    # filename without extension
    key = models.CharField(_('File key'), max_length=255, null=True, blank=True)
    relative_path = models.CharField(_('Relative Path'), max_length=255, null=True, blank=True)
    name = models.CharField(_('Filename'), max_length=255, null=True, blank=True)
    versions = models.ManyToManyField(MinioFile)

    @property
    def uri(self):
        if self.latest_version:
            return self.latest_version.uri

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
        return f"{self.scielo_issue} {self.name}"

    @classmethod
    def create_or_update(cls, item):
        logging.info("Register stored classic file {}".format(item))

        params = {
            k: item[k]
            for k in item.keys()
            if hasattr(cls, k)
        }
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

    def __str__(self):
        return f"{self.scielo_issue} {self.name} {self.lang} {self.languages}"

    @property
    def xml_with_pre(self):
        if not hasattr(self, '_xml_with_pre') or not self._xml_with_pre:
            try:
                self._xml_with_pre = get_xml_with_pre_from_uri(self.uri)
            except Exception as e:
                raise exceptions.AddLangsToXMLFilesError(
                    _("Unable to set main lang to xml {}: {} {}").format(
                        self.uri, type(e), e
                    )
                )
        return self._xml_with_pre

    @property
    def related_articles(self):
        if not hasattr(self, '_related_articles') or not self._related_articles:
            self._related_articles = self.xml_with_pre.related_items
        return self._related_articles

    @property
    def supplementary_materials(self):
        if not hasattr(self, '_supplementary_materials') or not self._supplementary_materials:
            supplmats = SupplementaryMaterials(self.xml_with_pre.xmltree)
            self._supplementary_materials = []
            names = [item.name for item in suppl_mats.items]
            for asset_file in self.assets_files:
                if asset_file.name in names:
                    asset_file.is_supplementary_material = True
                    asset_file.save()
                if asset_file.is_supplementary_material:
                    self._supplementary_materials.append({
                        "uri": asset_file.uri,
                        "lang": self.lang,
                        "ref_id": None,
                        "filename": asset_file.name,
                    })
        return self._supplementary_materials

    def add_assets(self, issue_assets_dict):
        """
        Atribui asset_files
        """
        try:
            # obtém os assets do XML
            article_assets = ArticleAssets(self.xml_with_pre.xmltree)
            for asset_in_xml in article_assets.article_assets:
                asset = issue_assets_dict.get(asset_in_xml.name)
                if asset:
                    # FIXME tratar asset_file nao encontrado
                    self.assets_files.add(asset)
            self.save()
        except Exception as e:
            raise exceptions.AddAssetFilesError(
                _("Unable to add assets to public XML to {} {} {})").format(
                    xml_file, type(e), e
                ))

    def get_xml_with_pre_with_remote_assets(self, issue_assets_uris):
        xml_with_pre = deepcopy(self.xml_with_pre)
        article_assets = ArticleAssets(xml_with_pre.xmltree)
        article_assets.replace_names(issue_assets_uris)
        return {"xml_with_pre": xml_with_pre, "name": self.name}

    def set_langs(self):
        try:
            article = ArticleRenditions(self.xml_with_pre.xmltree)
            renditions = article.article_renditions
            self.lang = renditions[0].language
            self.languages = [
                {"lang": rendition.language}
                for rendition in renditions
            ]
            self.save()
        except Exception as e:
            raise exceptions.AddLangsToXMLFilesError(
                _("Unable to set main lang to xml {}: {} {}").format(
                    self.uri, type(e), e
                )
            )


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

    collection = models.ForeignKey(Collection, on_delete=models.SET_NULL, null=True, blank=True)

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
