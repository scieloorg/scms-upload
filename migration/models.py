import logging
import os
from datetime import datetime

from django.core.files.base import ContentFile
from django.db import models
from django.utils.translation import gettext_lazy as _

from article.models import Article, CollectionArticleId
from collection.models import Collection, Language
from core.forms import CoreAdminModelForm
from core.models import CommonControlField
from issue.models import SciELOIssue
from journal.models import SciELOJournal

from . import choices, exceptions


class ClassicWebsiteConfiguration(CommonControlField):
    collection = models.ForeignKey(
        Collection, on_delete=models.SET_NULL, null=True, blank=True
    )

    title_path = models.CharField(
        _("Title path"),
        max_length=255,
        null=True,
        blank=True,
        help_text=_("Title path: title.id path or title.mst path without extension"),
    )
    issue_path = models.CharField(
        _("Issue path"),
        max_length=255,
        null=True,
        blank=True,
        help_text=_("Issue path: issue.id path or issue.mst path without extension"),
    )
    serial_path = models.CharField(
        _("Serial path"),
        max_length=255,
        null=True,
        blank=True,
        help_text=_("Serial path"),
    )
    cisis_path = models.CharField(
        _("Cisis path"),
        max_length=255,
        null=True,
        blank=True,
        help_text=_("Cisis path where there are CISIS utilities such as mx and i2id"),
    )
    bases_work_path = models.CharField(
        _("Bases work path"),
        max_length=255,
        null=True,
        blank=True,
        help_text=_("Bases work path"),
    )
    bases_pdf_path = models.CharField(
        _("Bases pdf path"),
        max_length=255,
        null=True,
        blank=True,
        help_text=_("Bases translation path"),
    )
    bases_translation_path = models.CharField(
        _("Bases translation path"),
        max_length=255,
        null=True,
        blank=True,
        help_text=_("Bases translation path"),
    )
    bases_xml_path = models.CharField(
        _("Bases XML path"),
        max_length=255,
        null=True,
        blank=True,
        help_text=_("Bases XML path"),
    )
    htdocs_img_revistas_path = models.CharField(
        _("Htdocs img revistas path"),
        max_length=255,
        null=True,
        blank=True,
        help_text=_("Htdocs img revistas path"),
    )

    def __str__(self):
        return f"{self.collection}"

    class Meta:
        indexes = [
            models.Index(fields=["collection"]),
        ]

    @classmethod
    def get_or_create(
        cls,
        collection,
        user=None,
        title_path=None,
        issue_path=None,
        serial_path=None,
        cisis_path=None,
        bases_work_path=None,
        bases_pdf_path=None,
        bases_translation_path=None,
        bases_xml_path=None,
        htdocs_img_revistas_path=None,
        creator=None,
    ):

        try:
            return cls.objects.get(collection=collection)
        except cls.DoesNotExist:
            obj = cls()
            obj.collection = collection
            obj.title_path = title_path
            obj.issue_path = issue_path
            obj.serial_path = serial_path
            obj.cisis_path = cisis_path
            obj.bases_work_path = bases_work_path
            obj.bases_pdf_path = bases_pdf_path
            obj.bases_translation_path = bases_translation_path
            obj.bases_xml_path = bases_xml_path
            obj.htdocs_img_revistas_path = htdocs_img_revistas_path
            obj.creator = user
            obj.save()
            return obj

    base_form_class = CoreAdminModelForm


class MigratedData(CommonControlField):
    # datas no registro da base isis para identificar
    # se houve mudança nos dados durante a migração
    isis_updated_date = models.CharField(
        _("ISIS updated date"), max_length=8, null=True, blank=True
    )
    isis_created_date = models.CharField(
        _("ISIS created date"), max_length=8, null=True, blank=True
    )

    # dados migrados
    data = models.JSONField(blank=True, null=True)

    # status da migração
    status = models.CharField(
        _("Status"),
        max_length=20,
        choices=choices.MIGRATION_STATUS,
        default=choices.MS_TO_MIGRATE,
    )

    class Meta:
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["isis_updated_date"]),
        ]


class MigrationFailure(CommonControlField):
    action_name = models.TextField(_("Action"), null=True, blank=True)
    message = models.TextField(_("Message"), null=True, blank=True)
    migrated_item_name = models.TextField(_("Item name"), null=True, blank=True)
    migrated_item_id = models.TextField(_("Item id"), null=True, blank=True)
    exception_type = models.TextField(_("Exception Type"), null=True, blank=True)
    exception_msg = models.TextField(_("Exception Msg"), null=True, blank=True)
    collection_acron = models.TextField(_("Collection acron"), null=True, blank=True)
    traceback = models.JSONField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["action_name"]),
        ]

    @classmethod
    def create(
        cls,
        message=None,
        action_name=None,
        e=None,
        creator=None,
        migrated_item_name=None,
        migrated_item_id=None,
        collection_acron=None,
    ):
        # exc_type, exc_value, exc_traceback = sys.exc_info()
        obj = cls()
        obj.collection_acron = collection_acron
        obj.action_name = action_name
        obj.migrated_item_name = migrated_item_name
        obj.migrated_item_id = migrated_item_id
        obj.message = message
        obj.exception_msg = str(e)
        obj.exception_type = str(type(e))
        obj.creator = creator
        obj.save()
        return obj


def migrated_files_directory_path(instance, filename):
    # file will be uploaded to MEDIA_ROOT/user_<id>/<filename>
    return f"migrated_files/{instance.migrated_issue.issue_pid}/{filename}"


class MigratedFile(CommonControlField):
    migrated_issue = models.ForeignKey(
        "MigratedIssue", on_delete=models.SET_NULL, null=True, blank=True
    )
    file = models.FileField(
        upload_to=migrated_files_directory_path, null=True, blank=True
    )
    # bases/pdf/acron/volnum/pt_a01.pdf
    original_path = models.TextField(_("Original Path"), null=True, blank=True)
    # /pdf/acron/volnum/pt_a01.pdf
    original_href = models.TextField(_("Original href"), null=True, blank=True)
    # pt_a01.pdf
    original_name = models.TextField(_("Original name"), null=True, blank=True)
    # ISSN-acron-vol-num-suppl
    sps_pkg_name = models.TextField(_("New name"), null=True, blank=True)
    # a01
    pkg_name = models.TextField(_("Package name"), null=True, blank=True)
    # rendition
    category = models.CharField(
        _("Issue File Category"),
        max_length=20,
        null=True,
        blank=True,
    )
    lang = models.ForeignKey(Language, null=True, blank=True, on_delete=models.SET_NULL)
    part = models.CharField(_("Part"), max_length=6, null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["pkg_name"]),
            models.Index(fields=["migrated_issue"]),
            models.Index(fields=["lang"]),
            models.Index(fields=["part"]),
            models.Index(fields=["category"]),
            models.Index(fields=["original_href"]),
            models.Index(fields=["original_name"]),
            models.Index(fields=["sps_pkg_name"]),
        ]

    @classmethod
    def get_original_href(self, original_path):
        try:
            return original_path[original_path.find("/") :]
        except:
            pass

    def __str__(self):
        return f"{self.original_path}"

    def save_file(self, name, content):
        logging.info(f"Save {name}")
        self.file.save(name, ContentFile(content))
        logging.info(self.file.path)
        logging.info(os.path.isfile(self.file.path))

    @classmethod
    def get(
        cls,
        migrated_issue,
        original_path=None,
        original_name=None,
        original_href=None,
        pkg_name=None,
        sps_pkg_name=None,
    ):

        if original_href:
            # /pdf/acron/volume/file.pdf
            return cls.objects.get(
                migrated_issue=migrated_issue,
                original_href=original_href,
            )
        if original_name:
            # file.pdf
            return cls.objects.get(
                migrated_issue=migrated_issue,
                original_name=original_name,
            )
        if original_path:
            # bases/pdf/acron/volume/file.pdf
            return cls.objects.get(
                migrated_issue=migrated_issue,
                original_path=original_path,
            )
        if pkg_name:
            # file
            return cls.objects.get(
                migrated_issue=migrated_issue,
                pkg_name=pkg_name,
            )
        if sps_pkg_name:
            # ISSN-acron-VV-NN-SS-lang.pdf
            return cls.objects.get(
                migrated_issue=migrated_issue,
                sps_pkg_name=sps_pkg_name,
            )

    @classmethod
    def create_or_update(
        cls,
        migrated_issue,
        original_path=None,
        source_path=None,
        file_content=None,
        file_name=None,
        category=None,
        lang=None,
        part=None,
        pkg_name=None,
        sps_pkg_name=None,
        creator=None,
    ):
        try:
            logging.info(
                "Create or update MigratedFile {} {} {} {}".format(
                    migrated_issue,
                    original_path,
                    pkg_name,
                    sps_pkg_name,
                )
            )
            obj = cls.get(
                migrated_issue,
                original_path=original_path,
                pkg_name=pkg_name,
                sps_pkg_name=sps_pkg_name,
            )
            obj.updated_by = creator
            obj.updated = datetime.utcnow()
        except cls.DoesNotExist:
            obj = cls()
            obj.creator = creator

        try:
            obj.migrated_issue = migrated_issue
            obj.original_path = original_path
            obj.original_name = original_path and os.path.basename(original_path)
            obj.original_href = cls.get_original_href(original_path)
            obj.sps_pkg_name = sps_pkg_name
            obj.pkg_name = pkg_name
            obj.category = category
            obj.lang = lang and Language.get_or_create(code2=lang, creator=creator)
            obj.part = part
            obj.save()

            # cria / atualiza arquivo
            collection_acron = migrated_issue.migrated_journal.collection.acron
            journal_acron = migrated_issue.migrated_journal.acron
            issue_folder = migrated_issue.issue_folder
            basename = os.path.basename(original_path)
            file_name = (
                file_name
                or f"{collection_acron}_{journal_acron}_{issue_folder}_{basename}"
            )
            if source_path:
                with open(source_path, "rb") as fp:
                    file_content = fp.read()
            if file_content:
                obj.save_file(file_name, file_content)
                obj.save()
            logging.info("Created {}".format(obj))
            return obj
        except Exception as e:
            raise exceptions.CreateOrUpdateMigratedFileError(
                _("Unable to get_or_create_migrated_issue_file {} {} {} {}").format(
                    migrated_issue, original_path, type(e), e
                )
            )


class MigratedJournal(MigratedData):
    """
    Dados migrados do periódico do site clássico
    """

    scielo_journal = models.ForeignKey(
        SciELOJournal, on_delete=models.SET_NULL, null=True, blank=True
    )

    class Meta:
        indexes = [
            models.Index(fields=["scielo_journal"]),
        ]

    def __str__(self):
        return f"{self.scielo_journal} {self.status}"

    @classmethod
    def get(cls, collection=None, scielo_issn=None, scielo_journal=None):
        logging.info(
            f"MigratedJournal.create_or_update collection={collection} scielo_issn={scielo_issn} scielo_journal={scielo_journal} "
        )
        if collection and scielo_issn:
            return cls.objects.get(
                scielo_journal__collection=collection,
                scielo_journal__scielo_issn=scielo_issn,
            )
        if scielo_journal:
            return cls.objects.get(
                scielo_journal=scielo_journal,
            )

    @classmethod
    def create_or_update(
        cls,
        scielo_journal,
        creator=None,
        isis_created_date=None,
        isis_updated_date=None,
        data=None,
        status=None,
        force_update=None,
    ):

        logging.info(f"MigratedJournal.create_or_update {scielo_journal}")
        try:
            obj = cls.get(scielo_journal=scielo_journal)
            logging.info("Update MigratedJournal {}".format(obj))
            obj.updated_by = creator
            obj.updated = datetime.utcnow()
        except cls.DoesNotExist:
            obj = cls()
            obj.scielo_journal = scielo_journal
            obj.creator = creator
            logging.info("Create MigratedJournal {}".format(obj))

        try:
            if force_update or obj.isis_updated_date != isis_updated_date:
                obj.isis_created_date = isis_created_date or obj.isis_created_date
                obj.isis_updated_date = isis_updated_date or obj.isis_updated_date
                obj.status = status or obj.status
                obj.data = data or obj.data
                obj.save()
                logging.info("Created / Updated MigratedJournal {}".format(obj))
            return obj
        except Exception as e:
            raise exceptions.CreateOrUpdateMigratedJournalError(
                _("Unable to create_or_update_migrated_journal {} {} {}").format(
                    scielo_journal, type(e), e
                )
            )

    @classmethod
    def journals(cls, collection_acron, status):
        return cls.objects.filter(
            scielo_journal__collection__acron=collection_acron,
            status=status,
        ).iterator()

    @property
    def collection(self):
        return self.scielo_journal.collection

    @property
    def acron(self):
        return self.scielo_journal.acron

    @property
    def scielo_issn(self):
        return self.scielo_journal.scielo_issn


class MigratedIssue(MigratedData):
    scielo_issue = models.ForeignKey(
        SciELOIssue, on_delete=models.SET_NULL, null=True, blank=True
    )
    migrated_journal = models.ForeignKey(
        MigratedJournal, on_delete=models.SET_NULL, null=True, blank=True
    )

    class Meta:
        indexes = [
            models.Index(fields=["scielo_issue"]),
            models.Index(fields=["migrated_journal"]),
        ]

    def __unicode__(self):
        return f"{self.scielo_issue} | {self.status}"

    def __str__(self):
        return f"{self.scielo_issue} | {self.status}"

    @property
    def issue_pid(self):
        return self.scielo_issue.issue_pid

    @property
    def issue_folder(self):
        return self.scielo_issue.issue_folder

    @property
    def publication_year(self):
        return self.scielo_issue.official_issue.publication_year

    @classmethod
    def create_or_update(
        cls,
        scielo_issue,
        migrated_journal,
        creator=None,
        isis_created_date=None,
        isis_updated_date=None,
        status=None,
        data=None,
        force_update=None,
    ):

        logging.info("Create or Update MigratedIssue {}".format(scielo_issue))
        try:
            obj = cls.objects.get(scielo_issue=scielo_issue)
            logging.info("Update MigratedIssue {}".format(obj))
            obj.updated_by = creator
            obj.updated = datetime.utcnow()
        except cls.DoesNotExist:
            obj = cls()
            obj.scielo_issue = scielo_issue
            obj.status = choices.MS_IMPORTED
            obj.creator = creator
            logging.info("Create MigratedIssue {}".format(obj))

        try:
            if force_update or obj.isis_updated_date != isis_updated_date:
                obj.migrated_journal = migrated_journal or obj.migrated_journal
                obj.isis_created_date = isis_created_date or obj.isis_created_date
                obj.isis_updated_date = isis_updated_date or obj.isis_updated_date
                obj.status = status or obj.status
                obj.data = data or obj.data
                obj.save()
                logging.info("Created / Updated MigratedIssue {}".format(obj))
            return obj
        except Exception as e:
            raise exceptions.CreateOrUpdateMigratedIssueError(
                _("Unable to create_or_update_migrated_issue {} {} {}").format(
                    scielo_issue, type(e), e
                )
            )


class MigratedDocument(MigratedData):
    migrated_issue = models.ForeignKey(
        MigratedIssue, null=True, blank=True, on_delete=models.SET_NULL
    )
    # os PIDs de artigos podem divergir dentre as coleções
    aids = models.ForeignKey(
        CollectionArticleId, null=True, blank=True, on_delete=models.SET_NULL
    )
    article = models.ForeignKey(
        Article, null=True, blank=True, on_delete=models.SET_NULL
    )
    pid = models.TextField(_("Package name"), null=True, blank=True)
    pkg_name = models.TextField(_("Package name"), null=True, blank=True)
    sps_pkg_name = models.TextField(_("New Package name"), null=True, blank=True)

    def __unicode__(self):
        return "%s %s %s" % (self.migrated_issue, self.pkg_name, self.pid)

    def __str__(self):
        return "%s %s %s" % (self.migrated_issue, self.pkg_name, self.pid)

    class Meta:
        indexes = [
            models.Index(fields=["migrated_issue"]),
            models.Index(fields=["pid"]),
            models.Index(fields=["pkg_name"]),
        ]

    def add_aids(
        self, pid_v3=None, collection=None, pid_v2=None, aop_pid=None, creator=None
    ):
        self.aids = CollectionArticleId.create_or_update(
            collection=collection,
            pid_v3=pid_v3,
            pid_v2=pid_v2,
            aop_pid=aop_pid,
            creator=creator,
        )

    @classmethod
    def get(cls, migrated_issue, pid=None, pkg_name=None):
        if pid:
            return cls.objects.get(
                migrated_issue=migrated_issue,
                pid=pid,
            )
        if pkg_name:
            return cls.objects.get(
                migrated_issue=migrated_issue,
                pkg_name=pkg_name,
            )

    @classmethod
    def create_or_update(
        cls,
        migrated_issue,
        pid=None,
        pkg_name=None,
        creator=None,
        pid_v3=None,
        aop_pid=None,
        isis_created_date=None,
        isis_updated_date=None,
        data=None,
        status=None,
        article=None,
        sps_pkg_name=None,
        force_update=None,
    ):

        logging.info(
            "Create or Update MigratedDocument {} {} {}".format(
                migrated_issue,
                pid,
                pkg_name,
            )
        )

        try:
            obj = cls.get(
                migrated_issue=migrated_issue,
                pid=pid,
                pkg_name=pkg_name,
            )
            logging.info("Update MigratedDocument {}".format(obj))
            obj.updated_by = creator
            obj.updated = datetime.utcnow()
        except cls.DoesNotExist:
            obj = cls()
            obj.migrated_issue = migrated_issue
            obj.creator = creator
            logging.info("Create MigratedDocument {}".format(obj))

        try:
            if force_update or obj.isis_updated_date != isis_updated_date:
                obj.pkg_name = pkg_name or obj.pkg_name
                obj.pid = pid or obj.pid
                obj.isis_created_date = isis_created_date
                obj.isis_updated_date = isis_updated_date
                obj.status = status or obj.status
                obj.article = article or obj.article
                obj.sps_pkg_name = sps_pkg_name or obj.sps_pkg_name
                obj.data = data or obj.data

                if pid or pid_v3 or aop_pid:
                    obj.add_aids(
                        pid_v3=pid_v3,
                        pid_v2=pid,
                        aop_pid=aop_pid,
                        creator=creator,
                        collection=migrated_issue.migrated_journal.collection,
                    )
                obj.save()
                logging.info("Created / Updated MigratedDocument {}".format(obj))
            return obj
        except Exception as e:
            raise exceptions.CreateOrUpdateMigratedDocumentError(
                _("Unable to create_or_update_migrated_document {} {} {} {} {}").format(
                    migrated_issue, pkg_name, pid, type(e), e
                )
            )

    @property
    def html_texts(self):
        _html_texts = {}
        for html_file in MigratedFile.objects.filter(
            migrated_issue=self.migrated_issue,
            pkg_name=self.pkg_name,
            category="html",
        ).iterator():
            lang = html_file.lang.code2
            _html_texts.setdefault(lang, {})
            part = f"{html_file.part} references"
            _html_texts[lang][part] = html_file.text
        return _html_texts

    @property
    def migrated_xml(self):
        for item in MigratedFile.objects.filter(
            migrated_issue=self.migrated_issue,
            pkg_name=self.pkg_name,
            category="xml",
        ).iterator():
            return {"path": item.file.path, "name": item.original_name}

        item = GeneratedXMLFile.latest(
            migrated_issue=self.migrated_issue,
            pkg_name=self.pkg_name,
        )
        if item:
            return {"path": item.file.path, "name": item.original_name}

        raise exceptions.MigratedXMLFileNotFoundError(
            _("Migrated XML file not found: {} {}").format(
                self.migrated_issue, self.pkg_name,
            )
        )


def body_and_back_directory_path(instance, filename):
    # file will be uploaded to MEDIA_ROOT/user_<id>/<filename>
    return f"body_and_back/{instance.migrated_issue.issue_pid}/{filename}"


class BodyAndBackFile(CommonControlField):
    pkg_name = models.TextField(_("Package name"), null=True, blank=True)
    migrated_issue = models.ForeignKey(
        "MigratedIssue", on_delete=models.SET_NULL, null=True, blank=True
    )
    file = models.FileField(
        upload_to=body_and_back_directory_path, null=True, blank=True
    )
    version = models.IntegerField()

    class Meta:
        indexes = [
            models.Index(fields=["pkg_name"]),
            models.Index(fields=["migrated_issue"]),
            models.Index(fields=["version"]),
        ]

    def __str__(self):
        return f"{self.migrated_issue} {self.pkg_name} {self.version}"

    def save_file(self, name, content):
        logging.info(f"Save {name}")
        self.file.save(name, ContentFile(content))
        logging.info(self.file.path)
        logging.info(os.path.isfile(self.file.path))

    @classmethod
    def get(cls, migrated_issue, pkg_name, version):
        logging.info(
            "Get BodyAndBackFile {} {} {}".format(
                migrated_issue,
                pkg_name,
                version,
            )
        )
        return cls.objects.get(
            migrated_issue=migrated_issue,
            pkg_name=pkg_name,
            version=version,
        )

    @classmethod
    def create_or_update(cls, migrated_issue, pkg_name, version, file_content, creator):
        try:
            logging.info(
                "Create or update BodyAndBackFile {} {} {}".format(
                    migrated_issue, pkg_name, version
                )
            )
            obj = cls.get(migrated_issue, pkg_name, version)
            obj.updated_by = creator
            obj.updated = datetime.utcnow()
        except cls.DoesNotExist:
            obj = cls()
            obj.creator = creator
            obj.migrated_issue = migrated_issue

        try:
            obj.version = version
            obj.pkg_name = pkg_name
            obj.save()

            # cria / atualiza arquivo
            collection_acron = migrated_issue.migrated_journal.collection.acron
            journal_acron = migrated_issue.migrated_journal.acron
            issue_folder = migrated_issue.issue_folder
            basename = os.path.basename(original_path)
            file_name = f"{collection_acron}_{journal_acron}_{issue_folder}_{pkg_name}_{version}.xml"
            obj.save_file(file_name, file_content)
            obj.save()
            logging.info("Created {}".format(obj))
            return obj
        except Exception as e:
            raise exceptions.CreateOrUpdateBodyAndBackFileError(
                _(
                    "Unable to create_or_update_body and back file {} {} {} {} {}"
                ).format(migrated_issue, pkg_name, version, type(e), e)
            )


def generated_xml_directory_path(instance, filename):
    # file will be uploaded to MEDIA_ROOT/user_<id>/<filename>
    return f"generated_xml/{instance.migrated_issue.issue_pid}/{filename}"


class GeneratedXMLFile(CommonControlField):
    pkg_name = models.TextField(_("Package name"), null=True, blank=True)
    migrated_issue = models.ForeignKey(
        "MigratedIssue", on_delete=models.SET_NULL, null=True, blank=True
    )
    file = models.FileField(
        upload_to=generated_xml_directory_path, null=True, blank=True
    )
    version = models.IntegerField()

    class Meta:
        indexes = [
            models.Index(fields=["pkg_name"]),
            models.Index(fields=["migrated_issue"]),
            models.Index(fields=["version"]),
        ]

    def __str__(self):
        return f"{self.migrated_issue} {self.pkg_name} {self.version}"

    def save_file(self, name, content):
        logging.info(f"Save {name}")
        self.file.save(name, ContentFile(content))
        logging.info(self.file.path)
        logging.info(os.path.isfile(self.file.path))

    @classmethod
    def latest(cls, migrated_issue, pkg_name):
        try:
            return cls.objects.filter(
                migrated_issue=migrated_issue,
                pkg_name=pkg_name,
            ).latest("version")
        except (cls.DoesNotExist, AttributeError):
            return None

    @classmethod
    def get(cls, migrated_issue, pkg_name, version):
        logging.info(
            "Get GeneratedXMLFile {} {} {}".format(
                migrated_issue,
                pkg_name,
                version,
            )
        )
        return cls.objects.get(
            migrated_issue=migrated_issue,
            pkg_name=pkg_name,
            version=version,
        )

    @classmethod
    def create_or_update(cls, migrated_issue, pkg_name, version, file_content, creator):
        try:
            logging.info(
                "Create or update GeneratedXMLFile {} {} {}".format(
                    migrated_issue, pkg_name, version
                )
            )
            obj = cls.get(migrated_issue, pkg_name, version)
            obj.updated_by = creator
            obj.updated = datetime.utcnow()
        except cls.DoesNotExist:
            obj = cls()
            obj.creator = creator

        try:
            obj.migrated_issue = migrated_issue
            obj.version = version
            obj.pkg_name = pkg_name
            obj.save()

            # cria / atualiza arquivo
            collection_acron = migrated_issue.migrated_journal.collection.acron
            journal_acron = migrated_issue.migrated_journal.acron
            issue_folder = migrated_issue.issue_folder
            basename = os.path.basename(original_path)
            file_name = f"{collection_acron}_{journal_acron}_{issue_folder}_{pkg_name}_{version}.xml"
            obj.save_file(file_name, file_content)
            obj.save()
            logging.info("Created {}".format(obj))
            return obj
        except Exception as e:
            raise exceptions.CreateOrUpdateGeneratedXMLFileError(
                _(
                    "Unable to create_or_update_generated xml file {} {} {} {} {}"
                ).format(migrated_issue, pkg_name, version, type(e), e)
            )
