import logging
import os
from copy import deepcopy
from datetime import datetime
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from django.core.files.base import ContentFile
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from packtools.sps.models.v2.article_assets import ArticleAssets
from packtools.sps.pid_provider.xml_sps_lib import XMLWithPre

from collection.models import Collection, Language
from core.forms import CoreAdminModelForm
from core.models import CommonControlField
from package.models import SPSPkg
from scielo_classic_website import classic_ws
from scielo_classic_website.htmlbody.html_body import HTMLContent

from . import choices, exceptions


def now():
    return datetime.utcnow().isoformat().replace(":", "-").replace(".", "-")


class MigratedFileGetError(Exception):
    ...


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

    collection = models.ForeignKey(
        Collection, on_delete=models.SET_NULL, null=True, blank=True
    )

    pid = models.CharField(_("PID"), max_length=1, null=True, blank=True)

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
        max_length=26,
        choices=choices.MIGRATION_STATUS,
        default=choices.MS_TO_MIGRATE,
    )

    class Meta:
        indexes = [
            models.Index(fields=["pid"]),
            models.Index(fields=["status"]),
            models.Index(fields=["isis_updated_date"]),
        ]

    def __str__(self):
        return f"{self.collection} {self.pid}"

    @classmethod
    def get(cls, collection, pid):
        logging.info(f"MigratedData.get collection={collection} pid={pid}")
        return cls.objects.get(collection=collection, pid=pid)

    @classmethod
    def create_or_update(
        cls,
        collection,
        pid,
        creator=None,
        isis_created_date=None,
        isis_updated_date=None,
        data=None,
        status=None,
        force_update=None,
    ):
        logging.info(f"MigratedData.create_or_update {collection} {pid}")
        try:
            obj = cls.get(collection=collection, pid=pid)

            if (
                force_update
                or data != obj.data
                or not obj.isis_updated_date
                or (isis_updated_date and obj.isis_updated_date < isis_updated_date)
            ):
                logging.info(f"Update MigratedData {obj}")
                obj.updated_by = creator
            else:
                logging.info("Skip updating MigratedData")
                return obj
        except cls.DoesNotExist:
            obj = cls()
            obj.collection = collection
            obj.pid = pid
            obj.creator = creator
            logging.info("Create MigratedData {}".format(obj))

        try:
            obj.isis_created_date = isis_created_date or obj.isis_created_date
            obj.isis_updated_date = isis_updated_date or obj.isis_updated_date

            if obj.isis_created_date:
                if not obj.isis_updated_date:
                    obj.isis_updated_date = now()[:12].replace("-", "")
            else:
                obj.isis_created_date = now()[:12].replace("-", "")

            obj.status = status or obj.status
            obj.data = data or obj.data
            obj.save()
            logging.info("Created / Updated MigratedData {}".format(obj))
            return obj
        except Exception as e:
            raise exceptions.CreateOrUpdateMigratedError(
                _("Unable to create_or_update_migrated_journal {} {} {} {}").format(
                    collection, pid, type(e), e
                )
            )


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
    issue_pid = instance.pid
    return (
        f"migration/{issue_pid[:9]}/"
        f"{issue_pid[9:13]}/"
        f"{issue_pid[13:]}/{instance.pkg_name}/"
        f"{filename}"
    )


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
        if self.original_path:
            return self.original_path
        return f"{self.pkg_name} {self.category} {self.lang} {self.part}"

    def save_file(self, name, content):
        if self.file:
            try:
                with open(self.file.path, "rb") as fp:
                    c = fp.read()
                    if c == content:
                        logging.info("skip save file")
                        return
            except Exception as e:
                pass
        self.file.save(name, ContentFile(content))
        logging.info(f"Saved {self.file.path}")

    @property
    def text(self):
        if self.category == "xml":
            with open(self.file.path, "r") as fp:
                return fp.read()
        if self.category == "html":
            try:
                with open(self.file.path, mode="r", encoding="iso-8859-1") as fp:
                    return fp.read()
            except:
                with open(self.file.path, mode="r", encoding="utf-8") as fp:
                    return fp.read()

    @property
    def xml_with_pre(self):
        if self.category == "xml":
            for item in XMLWithPre.create(path=self.file.path):
                return item

    @classmethod
    def get(
        cls,
        migrated_issue,
        original_path=None,
        original_name=None,
        original_href=None,
        pkg_name=None,
        category=None,
        part=None,
        lang=None,
    ):
        if not migrated_issue:
            raise MigratedFileGetError(_("MigratedFile.get requires migrated_issue"))
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
                original_path=original_path,
            )

        if category and lang and part and pkg_name:
            # bases/pdf/acron/volume/file.pdf
            return cls.objects.get(
                migrated_issue=migrated_issue,
                pkg_name=pkg_name,
                category=category,
                lang=lang,
                part=part,
            )
        raise MigratedFileGetError(
            _(
                "MigratedFile.get requires original_path or original_name or"
                " original_href or pkg_name or category and lang and part"
            )
        )

    def is_out_of_date(self, file_content):
        if not self.file:
            return True
        try:
            with open(self.file.path, "rb") as fp:
                c = fp.read()
            return c != file_content
        except Exception as e:
            return True

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
        force_update=None,
    ):
        try:
            input_data = dict(
                migrated_issue=migrated_issue,
                original_path=original_path,
                # original_name=original_name,
                # original_href=original_href,
                pkg_name=pkg_name,
                lang=lang,
                part=part,
                category=category,
            )
            logging.info(f"Create or update MigratedFile {input_data}")

            if source_path:
                with open(source_path, "rb") as fp:
                    file_content = fp.read()

            obj = cls.get(**input_data)

            if force_update or obj.is_out_of_date(file_content):
                logging.info(f"Update MigratedFile {input_data}")
                obj.updated_by = creator
            else:
                logging.info(f"MigratedFile is already up-to-date")
                return obj
        except cls.DoesNotExist:
            logging.info(f"Create MigratedFile {input_data}")
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
            if lang:
                obj.lang = Language.get_or_create(code2=lang, creator=creator)
            obj.part = part
            obj.save()

            # cria / atualiza arquivo
            obj.save_file(file_name or obj.filename, file_content)
            obj.save()
            logging.info(f"Created {obj}")
            return obj
        except Exception as e:
            raise exceptions.CreateOrUpdateMigratedFileError(
                _("Unable to get_or_create_migrated_issue_file {} {} {} {}").format(
                    migrated_issue, original_path, type(e), e
                )
            )

    @property
    def filename(self):
        collection_acron = (
            self.migrated_issue.migrated_journal.scielo_journal.collection.acron
        )
        journal_acron = self.migrated_issue.migrated_journal.scielo_journal.acron
        issue_folder = self.migrated_issue.issue_folder
        basename = os.path.basename(self.original_path)
        return f"{collection_acron}_{journal_acron}_{issue_folder}_{basename}"


class MigratedJournal(MigratedData):
    """
    Dados migrados do periódico do site clássico
    """

    pid = models.CharField(_("PID"), max_length=9, null=True, blank=True)


class MigratedIssue(MigratedData):
    pid = models.CharField(_("PID"), max_length=17, null=True, blank=True)
    migrated_journal = models.ForeignKey(MigratedJournal)
    migrated_files = models.ManyToManyField(MigratedFile)
    files_status = models.CharField(
        _("Files Status"),
        max_length=26,
        choices=choices.MIGRATION_STATUS,
        default=choices.MS_TO_MIGRATE,
    )
    docs_status = models.CharField(
        _("Document Status"),
        max_length=26,
        choices=choices.MIGRATION_STATUS,
        default=choices.MS_TO_MIGRATE,
    )


class MigratedDocumentRecord(MigratedData):
    pid = models.CharField(_("PID"), max_length=23, null=True, blank=True)


class MigratedParagraphRecord(MigratedData):
    pid = models.CharField(_("PID"), max_length=23, null=True, blank=True)


class MigratedDocument(MigratedData):
    pid = models.CharField(_("PID"), max_length=23, null=True, blank=True)
    migrated_issue = models.ForeignKey(MigratedIssue)
    pkg_name = models.TextField(_("Package name"), null=True, blank=True)
    sps_pkg_name = models.TextField(_("SPS Package name"), null=True, blank=True)
    file_type = models.CharField(_("File type"), max_length=5, null=True, blank=True)
    missing_assets = models.JSONField(null=True, blank=True)
    migrated_files = models.ManyToManyField(MigratedFile)
    body_and_back_files = models.ManyToManyField("BodyAndBackFile")
    generated_xml = models.ManyToManyField("GeneratedXMLFile")

    def __unicode__(self):
        return f"{self.pid} {self.pkg_name}"

    def __str__(self):
        return f"{self.pid} {self.pkg_name}"

    class Meta:
        indexes = [
            models.Index(fields=["file_type"]),
            models.Index(fields=["pkg_name"]),
        ]

    @classmethod
    def create_or_update(
        cls,
        collection,
        pid,
        pkg_name=None,
        creator=None,
        isis_created_date=None,
        isis_updated_date=None,
        data=None,
        status=None,
        sps_pkg_name=None,
        file_type=None,
        force_update=None,
    ):
        try:
            obj = cls.get(collection=collection, pid=pid)
            if (
                force_update
                or not obj.isis_updated_date
                or obj.isis_updated_date < isis_updated_date
                or obj.data != data
            ):
                logging.info("Update MigratedDocument {}".format(obj))
                obj.updated_by = creator
            else:
                logging.info("Skip updating document {}".format(obj))
                return obj
        except cls.MultipleObjectsReturned as e:
            logging.exception(e)
            cls.objects.filter(collection=collection, pid=pid).delete()
            obj = cls()
            obj.collection = collection
            obj.pid = pid
            obj.creator = creator
            logging.info("Create MigratedDocument {}".format(obj))
        except cls.DoesNotExist:
            obj = cls()
            obj.collection = collection
            obj.pid = pid
            obj.creator = creator
            logging.info("Create MigratedDocument {}".format(obj))
        try:
            obj.file_type = file_type or obj.file_type
            obj.pkg_name = pkg_name or obj.pkg_name
            obj.isis_created_date = isis_created_date
            obj.isis_updated_date = isis_updated_date
            obj.status = status or obj.status
            obj.sps_pkg_name = sps_pkg_name or obj.sps_pkg_name
            obj.data = data or obj.data
            obj.save()
            logging.info("Created / Updated MigratedDocument {}".format(obj))
            return obj
        except Exception as e:
            raise exceptions.CreateOrUpdateMigratedDocumentError(
                _("Unable to create_or_update_migrated_document {} {} {} {}").format(
                    collection, pid, type(e), e
                )
            )

    @property
    def html_translations(self):
        """
        {
            "pt": {"before references": [], "after references": []},
            "es": {"before references": [], "after references": []},
        }
        """
        logging.info(f"html_translations: {self.migrated_issue} {self.pkg_name}")
        _html_texts = {}
        for html_file in self.migrated_files.filter(category="html").iterator():
            lang = html_file.lang.code2
            _html_texts.setdefault(lang, {})
            part = f"{html_file.part} references"
            _html_texts[lang][part] = html_file.text
        return _html_texts

    @property
    def xhtml_translations(self):
        """
        {
            "pt": {"before references": [], "after references": []},
            "es": {"before references": [], "after references": []},
        }
        """
        logging.info(f"xhtml_translations: {self.migrated_issue} {self.pkg_name}")
        xhtmls = {}
        for html_file in self.migrated_files.filter(category="xhtml").iterator():
            logging.info(f"get xhtml {html_file}")
            lang = html_file.lang.code2
            logging.info(f"lang={lang}")
            xhtmls.setdefault(lang, {})
            part = f"{html_file.part} references"
            xhtmls[lang][part] = html_file.text
            logging.info(xhtmls.keys())
        return xhtmls

    def html2xhtml(self):
        for html_file in self.migrated_files.filter(category="html").iterator():
            hc = HTMLContent(html_file.text)
            # FIXME
            logging.info(f"lang={html_file.lang.code2}")
            self.migrated_files.add(
                MigratedFile.create_or_update(
                    migrated_issue=html_file.migrated_issue,
                    file_content=hc.content,
                    file_name=f"{html_file.pkg_name}-{html_file.lang.code2}-{html_file.part}.xhtml",
                    category="xhtml",
                    lang=html_file.lang.code2,
                    part=html_file.part,
                    pkg_name=html_file.pkg_name,
                    creator=html_file.creator,
                )
            )

    @property
    def translations(self):
        logging.info(f"translations: {self.xhtml_translations.keys()}")
        logging.info(len(self.xhtml_translations.items()))
        if not self.xhtml_translations:
            self.html2xhtml()
        return self.xhtml_translations

    @property
    def migrated_xml(self):
        try:
            return self.migrated_files.filter(category="xml")[0]
        except (AttributeError, IndexError):
            return None

    @property
    def xml_with_pre(self):
        logging.info("xml_with_pre...")
        if self.migrated_xml:
            logging.info("return migrated_xml.xml_with_pre")
            return self.migrated_xml.xml_with_pre
        if self.generated_xml:
            logging.info("return generated_xml.xml_with_pre")
            return self.generated_xml.xml_with_pre
        logging.info("Not found xml_with_pre")

    @property
    def sps_status(self):
        xml_status = None
        if self.file_type == "html":
            try:
                if self.generated_xml.status != choices.HTML2XML_DONE:
                    xml_status = choices.MS_XML_WIP
            except AttributeError:
                xml_status = choices.MS_XML_WIP

        if self.missing_assets:
            if xml_status:
                return choices.MS_XML_WIP_AND_MISSING_ASSETS
            return choices.MS_MISSING_ASSETS
        return choices.MS_IMPORTED

    def register_failure(
        self, e, migrated_item_name, migrated_item_id, message, action_name, user
    ):
        logging.info(message)
        logging.exception(e)
        MigrationFailure.create(
            collection_acron=self.collection.acron,
            migrated_item_name=migrated_item_name,
            migrated_item_id=migrated_item_id,
            message=message,
            action_name=action_name,
            e=e,
            creator=user,
        )

    def generate_xml_body_and_back(self, user):
        migrated_item_id = f"{self}"

        pkg_name = self.pkg_name
        logging.info(f"DocumentMigration.generate_xml_from_html {pkg_name}")

        try:
            classic_ws_doc = classic_ws.Document(self.data)

            # obtém as traduções
            translated_texts = self.translations
            logging.info(f"translated_texts: {translated_texts}")

            # obtém um XML com body e back a partir dos arquivos HTML / traduções
            classic_ws_doc.generate_body_and_back_from_html(translated_texts)

            logging.info(
                f"classic_ws_doc.xml_body_and_back: {len(classic_ws_doc.xml_body_and_back)}"
            )

            for i, xml_body_and_back in enumerate(classic_ws_doc.xml_body_and_back):
                # guarda cada versão de body/back
                migrated_item_id = f"{self} {i}"
                self.body_and_back_files.add(
                    BodyAndBackFile.create_or_update(
                        migrated_document=self,
                        creator=user,
                        file_content=xml_body_and_back,
                        version=i,
                    )
                )
        except Exception as e:
            message = _("Unable to generate body and back from HTML {}").format(
                migrated_item_id
            )
            self.register_failure(
                e,
                migrated_item_name="document",
                migrated_item_id=migrated_item_id,
                message=message,
                action_name="xml-body-and-back",
            )
            return

    @property
    def xml_body_and_back(self):
        try:
            return (
                self.body_and_back_files.filter(
                    migrated_document=self,
                )
                .latest("version")
                .text
            )
        except Exception as e:
            logging.exception(e)

    def generate_xml_from_html(self, user):
        migrated_item_id = f"{self}"

        pkg_name = self.pkg_name
        logging.info(f"DocumentMigration.generate_xml_from_html {pkg_name}")

        try:
            classic_ws_doc = classic_ws.Document(self.data)

            xml_body_and_back = self.xml_body_and_back

            xml_content = classic_ws_doc.generate_full_xml(xml_body_and_back)
            self.generated_xml = GeneratedXMLFile.create_or_update(
                migrated_document=self,
                creator=user,
                file_content=xml_content,
            )
        except Exception as e:
            migrated_item_id = f"{self}"
            message = _("Unable to generate XML from HTML {}").format(migrated_item_id)
            self.register_failure(
                e,
                migrated_item_name="document",
                migrated_item_id=migrated_item_id,
                message=message,
                action_name="xml-to-html",
            )

    def build_sps_package(self, user):
        """
        A partir do XML original ou gerado a partir do HTML, e
        dos ativos digitais, todos registrados em MigratedFile,
        cria o zip com nome no padrão SPS (ISSN-ACRON-VOL-NUM-SUPPL-ARTICLE) e
        o armazena em SPSPkg.not_optimised_zip_file.
        Neste momento o XML não contém pid v3.
        """
        try:
            self.sps_pkg_name = self.xml_with_pre.sps_pkg_name

            # gera nome de pacote padrão SPS ISSN-ACRON-VOL-NUM-SUPPL-ARTICLE
            with TemporaryDirectory() as tmpdirname:
                logging.info("TemporaryDirectory %s" % tmpdirname)
                tmp_sps_pkg_zip_path = os.path.join(
                    tmpdirname, f"{self.sps_pkg_name}.zip"
                )

                # cria pacote zip
                with ZipFile(tmp_sps_pkg_zip_path, "w") as zf:
                    # add renditions (pdf) to zip
                    self._build_sps_package_add_renditions(zf, user)

                    # A partir do XML, obtém os nomes dos arquivos dos ativos digitais
                    self._build_sps_package_add_assets(zf, user)

                    # adiciona XML em zip
                    self._build_sps_package_add_xml(zf, user)

                sps_pkg = SPSPkg.get_or_create(
                    self.sps_pkg_name, tmp_sps_pkg_zip_path, user
                )
                if self.sps_status == choices.MS_IMPORTED:
                    sps_pkg.task_name = "push_articles_files_to_remote_storage"
                    sps_pkg.save()

            # XML_WIP or MISSING_ASSETS or XML_WIP_AND_MISSING_ASSETS
            self.status = self.sps_status
            self.save()

        except Exception as e:
            message = _("Unable to build sps package {} {}").format(
                self.collection.acron, self.pkg_name
            )
            self.register_failure(
                e,
                migrated_item_name="zip",
                migrated_item_id=self.pkg_name,
                message=message,
                action_name="build-sps-package",
            )

    def _build_sps_package_add_renditions(self, zf, user):
        if not self.sps_pkg_name:
            self.sps_pkg_name = self.xml_with_pre.sps_pkg_name
        for rendition in self.migrated_files.filter(category="rendition"):
            try:
                if rendition.lang:
                    sps_filename = f"{self.sps_pkg_name}-{rendition.lang}.pdf"
                else:
                    sps_filename = f"{self.sps_pkg_name}.pdf"
                rendition.sps_pkg_name = sps_filename
                zf.write(rendition.file.path, arcname=rendition.sps_pkg_name)
            except Exception as e:
                message = _(
                    "Unable to _build_sps_package_add_renditions {} {} {}"
                ).format(self.collection.acron, self.sps_pkg_name, rendition)
                self.register_failure(
                    e,
                    migrated_item_name="rendition",
                    migrated_item_id=str(rendition),
                    message=message,
                    action_name="build-sps-package",
                )

    def _build_sps_package_add_assets(self, zf, user):
        replacements = {}
        xml_assets = ArticleAssets(self.xml_with_pre.xmltree)
        for xml_graphic in xml_assets.items:
            logging.info(f"Find asset: {xml_graphic.xlink_href}")
            name = os.path.basename(xml_graphic.xlink_href)

            found = False
            for asset in self.migrated_issue.migrated_files.filter(
                Q(original_name=name) | Q(original_name__startswith=name + "."),
                category="asset",
            ):
                found = True
                self._build_sps_package_add_asset(
                    zf, asset, xml_graphic, replacements, user
                )
            if not found:
                subdir = os.path.join(
                    self.migrated_issue.migrated_journal.scielo_journal.acron,
                    self.migrated_issue.issue_folder,
                )
                path = os.path.join("/img/revistas/", subdir, xml_graphic.xlink_href)
                original_href = os.path.normpath(path)
                logging.info(xml_graphic.xlink_href)
                logging.info(path)

                for asset in MigratedFile.objects.filter(
                    Q(original_href=original_href)
                    | Q(original_href__startswith=original_href + "."),
                    category="asset",
                ):
                    found = True
                    self._build_sps_package_add_asset(
                        zf, asset, xml_graphic, replacements, user
                    )
            if not found:
                subdir = os.path.join(
                    self.migrated_issue.migrated_journal.scielo_journal.acron,
                    self.migrated_issue.issue_folder,
                    "html",
                )
                path = os.path.join("/img/revistas/", subdir, xml_graphic.xlink_href)
                original_href = os.path.normpath(path)
                logging.info(xml_graphic.xlink_href)
                logging.info(path)

                for asset in MigratedFile.objects.filter(
                    Q(original_href=original_href)
                    | Q(original_href__startswith=original_href + "."),
                    category="asset",
                ):
                    found = True
                    self._build_sps_package_add_asset(
                        zf, asset, xml_graphic, replacements, user
                    )
            if not found:
                self.missing_assets.append(xml_graphic.xlink_href)
        xml_assets.replace_names(replacements)

    def _build_sps_package_add_asset(self, zf, asset, xml_graphic, replacements, user):
        try:
            logging.info(f"Add asset {asset.original_href}")

            # obtém o nome do arquivo no padrão sps
            sps_filename = xml_graphic.name_canonical(self.sps_pkg_name)
            asset.sps_pkg_name = sps_filename

            # indica a troca de href original para o padrão SPS
            replacements[xml_graphic.xlink_href] = sps_filename
            logging.info(f"replacements: {replacements}")

            # adiciona componente ao pacote
            if asset.sps_pkg_name and asset.sps_pkg_name != sps_filename:
                # cria uma cópia
                obj = deepcopy(asset)
                obj.sps_pkg_name = sps_filename
                obj.save()
            zf.write(asset.file.path, arcname=sps_filename)

        except Exception as e:
            message = _("Unable to _build_sps_package_add_asset {} {}").format(
                self.sps_pkg_name, asset.original_name
            )
            self.register_failure(
                e=e,
                migrated_item_name="asset",
                migrated_item_id=asset.original_name,
                message=message,
                action_name="build-sps-package",
            )

    def _build_sps_package_add_xml(self, zf, user):
        try:
            sps_xml_name = self.sps_pkg_name + ".xml"
            zf.writestr(sps_xml_name, self.xml_with_pre.tostring())

        except Exception as e:
            message = _("Unable to _build_sps_package_add_xml {} {} {}").format(
                self.collection.acron, self.sps_pkg_name, sps_xml_name
            )
            self.register_failure(
                e,
                migrated_item_name="xml",
                migrated_item_id=sps_xml_name,
                message=message,
                action_name="build-sps-package",
            )


def body_and_back_directory_path(instance, filename):
    # file will be uploaded to MEDIA_ROOT/user_<id>/<filename>
    pid = instance.migrated_document.pid
    return (
        f"migration/{pid[1:10]}/"
        f"{pid[10:14]}/{pid[14:18]}/"
        f"{instance.migrated_document.pkg_name}/"
        f"body/"
        f"{instance.version}/{filename}"
    )


class BodyAndBackFile(CommonControlField):
    migrated_document = models.ForeignKey(
        "MigratedDocument", on_delete=models.SET_NULL, null=True, blank=True
    )
    file = models.FileField(
        upload_to=body_and_back_directory_path, null=True, blank=True
    )
    version = models.IntegerField()

    class Meta:
        indexes = [
            models.Index(fields=["migrated_document"]),
            models.Index(fields=["version"]),
        ]

    def __str__(self):
        return f"{self.migrated_document} {self.version}"

    @property
    def text(self):
        with open(self.file.path, mode="r", encoding="utf-8") as fp:
            return fp.read()

    def save_file(self, name, content):
        if self.file:
            try:
                with open(self.file.path, "rb") as fp:
                    c = fp.read()
                    if c == content:
                        logging.info("skip save file")
                        return
            except Exception as e:
                pass
        self.file.save(name, ContentFile(content))
        logging.info(f"Saved {self.file.path}")

    @classmethod
    def get(cls, migrated_document, version):
        logging.info(f"Get BodyAndBackFile {migrated_document} {version}")
        return cls.objects.get(
            migrated_document=migrated_document,
            version=version,
        )

    @classmethod
    def create_or_update(cls, migrated_document, version, file_content, creator):
        try:
            logging.info(
                f"Create or update BodyAndBackFile {migrated_document} {version}"
            )
            obj = cls.get(migrated_document, version)
            obj.updated_by = creator
            obj.updated = datetime.utcnow()
        except cls.DoesNotExist:
            obj = cls()
            obj.creator = creator
            obj.migrated_document = migrated_document

        try:
            obj.version = version
            obj.save()

            # cria / atualiza arquivo
            obj.save_file(obj.filename, file_content)
            obj.save()
            logging.info("Created {}".format(obj))
            return obj
        except Exception as e:
            raise exceptions.CreateOrUpdateBodyAndBackFileError(
                _("Unable to create_or_update_body and back file {} {} {} {}").format(
                    migrated_document, version, type(e), e
                )
            )

    @property
    def filename(self):
        return f"{now()}.xml"


def generated_xml_directory_path(instance, filename):
    pid = instance.migrated_document.pid
    return (
        f"migration/{pid[1:10]}/"
        f"{pid[10:14]}/{pid[14:18]}/"
        f"{instance.migrated_document.pkg_name}/"
        f"gen_xml/"
        f"{filename}"
    )


class GeneratedXMLFile(CommonControlField):
    migrated_document = models.ForeignKey(
        MigratedDocument, on_delete=models.SET_NULL, null=True, blank=True
    )
    file = models.FileField(
        upload_to=generated_xml_directory_path, null=True, blank=True
    )
    status = models.CharField(
        _("status"),
        max_length=25,
        choices=choices.HTML2XML_STATUS,
        default=choices.HTML2XML_NOT_EVALUATED,
    )

    class Meta:
        indexes = [
            models.Index(fields=["migrated_document"]),
        ]

    def __str__(self):
        return f"{self.migrated_document}"

    def save_file(self, name, content):
        if self.file:
            try:
                with open(self.file.path, "rb") as fp:
                    c = fp.read()
                    if c == content:
                        logging.info("skip save file")
                        return
            except Exception as e:
                pass
        self.file.save(name, ContentFile(content))
        logging.info(f"Saved {self.file.path}")

    @classmethod
    def get(cls, migrated_document):
        logging.info(f"Get GeneratedXMLFile {migrated_document}")
        return cls.objects.get(
            migrated_document=migrated_document,
        )

    @classmethod
    def create_or_update(cls, migrated_document, file_content, creator):
        try:
            logging.info(
                "Create or update GeneratedXMLFile {}".format(migrated_document)
            )
            obj = cls.get(migrated_document)
            obj.updated_by = creator
            obj.updated = datetime.utcnow()
        except cls.DoesNotExist:
            obj = cls()
            obj.creator = creator
            obj.migrated_document = migrated_document
        try:
            obj.save()

            # cria / atualiza arquivo
            obj.save_file(obj.filename, file_content)
            obj.save()
            logging.info("Created {}".format(obj))
            return obj
        except Exception as e:
            raise exceptions.CreateOrUpdateGeneratedXMLFileError(
                _("Unable to create_or_update_generated xml file {} {} {}").format(
                    migrated_document, type(e), e
                )
            )

    @property
    def filename(self):
        return f"{now()}.xml"

    @property
    def xml_with_pre(self):
        for item in XMLWithPre.create(path=self.file.path):
            return item
