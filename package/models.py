import logging
import mimetypes
import os
import sys
from datetime import datetime
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from django.core.files.base import ContentFile
from django.db.models import Q
from django.db import models
from django.utils.translation import gettext_lazy as _
from packtools import HTMLGenerator
from packtools.sps.models.v2.article_assets import ArticleAssets
from packtools.sps.pid_provider.xml_sps_lib import (
    XMLWithPre,
    get_xml_with_pre,
    get_xml_with_pre_from_uri,
)
from packtools.utils import SPPackage
from modelcluster.fields import ParentalKey
from modelcluster.models import ClusterableModel
from wagtail.admin.panels import FieldPanel, InlinePanel, ObjectList, TabbedInterface
from wagtailautocomplete.edit_handlers import AutocompletePanel
from wagtail.models import Orderable

from collection import choices as collection_choices
from collection.models import Language
from core.models import CommonControlField
from files_storage.models import FileLocation, MinioConfiguration
from package import choices
from pid_provider.requester import PidRequester
from tracker.models import UnexpectedEvent


pid_provider_app = PidRequester()


class SPSPkgOptimizeError(Exception):
    ...


class SPSPkgAddPidV3ToZipFileError(Exception):
    ...


def now():
    return datetime.utcnow().isoformat().replace(":", "-").replace(".", "-")


def minio_push_file_content(content, mimetype, object_name):
    # TODO MinioStorage.fput_content
    try:
        minio = MinioConfiguration.get_files_storage(name="website")
        return {"uri": minio.fput_content(content, mimetype, object_name)}
    except Exception as e:
        logging.exception(e)
        return {"error_type": str(type(e)), "error_msg": str(e)}


class CheckIsSynchronizedToPidProviderError(Exception):
    ...


class SPSPkgComponentCreateOrUpdateError(Exception):
    ...


class SPSPackageCreateOrUpdateError(Exception):
    ...


class OptimisedSPSPackageError(Exception):
    ...


class XMLVersionXmlWithPreError(Exception):
    ...


class BasicXMLFileSaveError(Exception):
    ...


class PreviewArticlePageFileSaveError(Exception):
    ...


def basic_xml_directory_path(instance, filename):
    try:
        pid = instance.pid
        subdir = os.path.join(pid[1:10], pid[10:14], pid[14:18], pid[18:])
    except AttributeError:
        # file will be uploaded to MEDIA_ROOT/user_<id>/<filename>
        name, ext = os.path.splitext(filename)
        subdir = f"{name[0]}/{name[-1]}"
    return f"package/xml/{subdir}/{filename}"


class BasicXMLFile(models.Model):
    file = models.FileField(upload_to=basic_xml_directory_path, null=True, blank=True)

    panels = [
        FieldPanel("file"),
    ]

    class Meta:
        abstract = True

    def __str__(self):
        try:
            return f"{self.file.path}"
        except Exception as e:
            return str(e)

    @property
    def xml_with_pre(self):
        try:
            for item in XMLWithPre.create(path=self.file.path):
                return item
        except Exception as e:
            raise XMLVersionXmlWithPreError(
                _("Unable to get xml with pre (XMLVersion) {}: {} {}").format(
                    self.file.path, type(e), e
                )
            )

    def save_file(self, name, content):
        try:
            self.file.delete(save=True)
        except Exception as e:
            pass
        try:
            self.file.save(name, ContentFile(content))
        except Exception as e:
            raise BasicXMLFileSaveError(f"Unable to save {name}. Exception: {e}")

    @property
    def text(self):
        with open(self.file.path, "r") as fp:
            return fp.read()

    @property
    def filename(self):
        return f"{now()}.xml"

    @property
    def sps_pkg_name(self):
        try:
            return self.xml_with_pre.sps_pkg_name
        except AttributeError:
            return


def pkg_directory_path(instance, filename):
    try:
        sps_pkg_name = instance.sps_pkg_name
    except AttributeError:
        sps_pkg_name = instance.sps_pkg.sps_pkg_name
    subdir = "/".join(sps_pkg_name.split("-"))
    return f"pkg/{subdir}/{filename}"


class SPSPkgComponent(FileLocation, Orderable):
    # herdados de FileLocation
    # - basename = models.TextField(_("Basename"), null=True, blank=True)
    # - uri = models.URLField(_("URI"), null=True, blank=True)
    sps_pkg = ParentalKey("SPSPkg", related_name="component")
    component_type = models.CharField(
        _("Package component type"),
        max_length=32,
        null=True,
        blank=True,
    )
    lang = models.ForeignKey(Language, null=True, blank=True, on_delete=models.SET_NULL)
    xml_elem_id = models.CharField(
        max_length=8,
        null=True,
        blank=True,
    )
    legacy_uri = models.TextField(null=True, blank=True)

    def autocomplete_label(self):
        return f"{self.sps_pkg} {self.basename}"

    class Meta:
        indexes = [
            models.Index(fields=["lang"]),
            models.Index(fields=["component_type"]),
        ]

    panels = FileLocation.panels + [
        FieldPanel("component_type"),
        FieldPanel("lang"),
        FieldPanel("xml_elem_id"),
        FieldPanel("legacy_uri"),
    ]

    @property
    def data(self):
        return dict(
            basename=self.basename,
            uri=self.uri,
            component_type=self.component_type,
            legacy_uri=self.legacy_uri,
            lang=self.lang and self.lang.code2,
            xml_elem_id=self.xml_elem_id,
        )

    @classmethod
    def get(cls, sps_pkg=None, uri=None, basename=None):
        if uri and sps_pkg:
            return cls.objects.get(sps_pkg=sps_pkg, uri=uri)
        if basename and sps_pkg:
            return cls.objects.get(sps_pkg=sps_pkg, basename=basename)
        raise ValueError("SPSPkgComponent.get requires sps_pkg and (uri or basename)")

    @classmethod
    def create_or_update(
        cls,
        user,
        sps_pkg,
        uri=None,
        basename=None,
        component_type=None,
        lang=None,
        legacy_uri=None,
    ):
        try:
            obj = cls.objects.get(sps_pkg=sps_pkg, uri=uri, basename=basename)
            obj.updated_by = user
        except cls.DoesNotExist:
            obj = cls()
            obj.creator = user
            obj.sps_pkg = sps_pkg

        try:
            obj.legacy_uri = legacy_uri or obj.legacy_uri
            obj.uri = uri or obj.uri
            obj.basename = basename or obj.basename
            obj.component_type = component_type or obj.component_type
            if lang:
                obj.lang = Language.get_or_create(creator=user, code2=lang)
            obj.save()
            return obj
        except Exception as e:
            raise SPSPkgComponentCreateOrUpdateError(
                f"Unable to create or update componentfile: {uri} {basename} {e} {str(type(e))}"
            )


class PreviewArticlePage(Orderable):
    # herdados de FileLocation
    # - basename = models.TextField(_("Basename"), null=True, blank=True)
    # - uri = models.URLField(_("URI"), null=True, blank=True)
    sps_pkg = ParentalKey("SPSPkg", related_name="article_page")
    lang = models.ForeignKey(Language, null=True, blank=True, on_delete=models.SET_NULL)
    file = models.FileField(upload_to=pkg_directory_path, null=True, blank=True)

    panels = [
        FieldPanel("lang"),
        FieldPanel("file"),
    ]

    def autocomplete_label(self):
        return f"{self.sps_pkg} {self.lang}"

    class Meta:
        indexes = [
            models.Index(fields=["lang"]),
        ]

    @classmethod
    def get(cls, sps_pkg=None, lang=None):
        if lang and sps_pkg:
            return cls.objects.get(sps_pkg=sps_pkg, lang=lang)
        raise ValueError("SPSPkgComponent.get requires sps_pkg and lang")

    @classmethod
    def create_or_update(
        cls,
        user,
        sps_pkg,
        lang,
        content,
    ):
        try:
            obj = cls.objects.get(sps_pkg=sps_pkg, lang=lang)
            obj.updated_by = user
        except cls.DoesNotExist:
            obj = cls()
            obj.creator = user
            obj.sps_pkg = sps_pkg
            obj.lang = lang

        try:
            obj.save_file(sps_pkg.sps_pkg_name + "-" + lang.code2 + ".html", content)
            obj.save()
            return obj
        except Exception as e:
            raise SPSPkgComponentCreateOrUpdateError(
                f"Unable to create or update componentfile: {e} {str(type(e))}"
            )

    def save_file(self, name, content):
        try:
            self.file.delete(save=True)
        except Exception as e:
            pass
        try:
            self.file.save(name, ContentFile(content))
        except Exception as e:
            raise PreviewArticlePageFileSaveError(
                f"Unable to save {name}. Exception: {e}"
            )


class SPSPkg(CommonControlField, ClusterableModel):
    pid_v3 = models.CharField(max_length=23, null=True, blank=True)
    sps_pkg_name = models.CharField(_("SPS Name"), max_length=32, null=True, blank=True)

    # zip
    file = models.FileField(upload_to=pkg_directory_path, null=True, blank=True)

    # compontents do pacote
    components = models.ManyToManyField(SPSPkgComponent)

    # XML URI
    xml_uri = models.URLField(null=True, blank=True)

    # pacote veio da migração ou do ingresso de novos conteúdos
    origin = models.CharField(
        max_length=32,
        null=True,
        blank=True,
        choices=choices.PKG_ORIGIN,
        default=choices.PKG_ORIGIN_INGRESS_WITHOUT_VALIDATION,
    )
    # publicar somente a partir da data informada
    scheduled = models.DateTimeField(null=True, blank=True)

    # o pacote pode ter pid_v3, sem estar registrado no pid provider core
    registered_in_core = models.BooleanField(null=True, blank=True)

    valid_components = models.BooleanField(null=True, blank=True)

    texts = models.JSONField(null=True, blank=True)
    valid_texts = models.BooleanField(null=True, blank=True)

    # pacote pode estar presente no Core (pid provider) antes de ser publicado,
    # então é necessário informar para o Core a situação
    is_public = models.BooleanField(null=True, blank=True)

    def __str__(self):
        try:
            return self.file.path
        except Exception as e:
            return self.sps_pkg_name

    panel_files = [
        FieldPanel("xml_uri"),
        FieldPanel("file"),
        InlinePanel("article_page", label=_("Article Page")),
        InlinePanel("component", label=_("Package component")),
    ]

    panel_status = [
        FieldPanel("origin", read_only=True),
        FieldPanel("is_public", read_only=True),
        FieldPanel("registered_in_core", read_only=True),
        FieldPanel("valid_texts", read_only=True),
        FieldPanel("valid_components", read_only=True),
        FieldPanel("texts", read_only=True),
    ]

    edit_handler = TabbedInterface(
        [
            ObjectList(panel_status, heading=_("Status")),
            ObjectList(panel_files, heading=_("Files")),
        ]
    )

    class Meta:
        indexes = [
            models.Index(fields=["pid_v3"]),
            models.Index(fields=["sps_pkg_name"]),
            models.Index(fields=["valid_texts"]),
            models.Index(fields=["valid_components"]),
            models.Index(fields=["registered_in_core"]),
        ]

    autocomplete_search_field = "sps_pkg_name"

    def autocomplete_label(self):
        return f"{self.sps_pkg_name} {self.pid_v3}"

    @property
    def xml_with_pre(self):
        for item in XMLWithPre.create(path=self.file.path):
            return item

    @property
    def is_migrated(self):
        return self.origin == choices.PKG_ORIGIN_MIGRATION

    @property
    def pdfs(self):
        return self.components.filter(component_type="rendition").iterator()

    @property
    def supplementary_material(self):
        return self.components.filter(
            component_type='"supplementary-material"'
        ).iterator()

    @classmethod
    def get(cls, pid_v3):
        return cls.objects.get(pid_v3=pid_v3)

    @staticmethod
    def is_registered_in_core(pid_v3):
        if not pid_v3:
            return False
        try:
            obj = cls.objects.get(pid_v3=pid_v3)
            return obj.registered_in_core
        except cls.DoesNotExist:
            return False

    @classmethod
    def _get_or_create(cls, user, pid_v3, sps_pkg_name, registered_in_core):
        try:
            obj = cls.objects.get(pid_v3=pid_v3)
            obj.updated_by = user
        except cls.DoesNotExist:
            obj = cls()
            obj.creator = user
            obj.pid_v3 = pid_v3
        obj.sps_pkg_name = sps_pkg_name
        obj.registered_in_core = registered_in_core
        obj.save()
        return obj

    @classmethod
    def create_or_update(
        cls,
        user,
        sps_pkg_zip_path,
        origin,
        is_public,
        original_pkg_components,
        texts,
        article_proc,
    ):
        try:
            operation = article_proc.start(user, "SPSPkg.create_or_update")

            obj = cls.add_pid_v3_to_zip(user, sps_pkg_zip_path, is_public, article_proc)
            obj.origin = origin or obj.origin
            obj.is_public = is_public or obj.is_public
            obj.texts = texts
            obj.save()

            obj.save_pkg_zip_file(user, sps_pkg_zip_path)

            obj.save_package_in_cloud(user, original_pkg_components, article_proc)

            obj.generate_article_html_page(user)

            obj.validate(True)

            logging.info(f"Depois de criar sps_pkg.pid_v3: {obj.pid_v3}")
            article_proc.update_sps_pkg_status()
            operation.finish(user, completed=obj.is_complete, detail=obj.data)

            return obj

        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            operation.finish(
                user,
                exc_traceback=exc_traceback,
                exception=e,
            )

    def validate(self, save=False):
        texts = self.texts
        if not texts:
            self.valid_texts = False
        elif texts.get("html_langs"):
            self.valid_texts = (
                set(texts.get("xml_langs"))
                == set(texts.get("pdf_langs"))
                == set(texts.get("html_langs"))
            )
        else:
            self.valid_texts = set(texts.get("xml_langs")) == set(texts.get("pdf_langs"))
        if save:
            self.save()

    @property
    def is_complete(self):
        return (
            self.registered_in_core
            and self.valid_texts
            and self.valid_components
        )

    @property
    def data(self):
        return dict(
            registered_in_core=self.registered_in_core,
            texts=self.texts,
            components=[item.data for item in self.components.all()]
        )

    @classmethod
    def is_registered_xml_zip(cls, zip_xml_file_path):
        """
        Check if zip_xml_file_path is registered
        """
        for item in pid_provider_app.is_registered_xml_zip(zip_xml_file_path):
            pid_v3 = item.get("v3")
            if pid_v3:
                try:
                    obj = cls.objects.get(pid_v3=pid_v3)
                    item["synchronized"] = obj.registered_in_core
                except cls.DoesNotExist:
                    pass
            yield item

    @classmethod
    def add_pid_v3_to_zip(cls, user, zip_xml_file_path, is_public, article_proc):
        """
        Solicita PID versão 3

        """
        try:
            response = None
            operation = None

            for response in pid_provider_app.request_pid_for_xml_zip(
                zip_xml_file_path, user, is_published=is_public
            ):
                logging.info(f"package response: {response}")
                operation = article_proc.start(user, "request_pid_for_xml_zip")

                xml_with_pre = response.pop("xml_with_pre")

                obj = cls._get_or_create(
                    user=user,
                    pid_v3=response["v3"],
                    sps_pkg_name=response["pkg_name"],
                    registered_in_core=response.get("synchronized"),
                )

                if response.get("xml_changed"):
                    # atualiza conteúdo de zip
                    with ZipFile(zip_xml_file_path, "a") as zf:
                        zf.writestr(
                            response["filename"], xml_with_pre.tostring()
                        )

                operation.finish(
                    user,
                    completed=obj.registered_in_core,
                    detail=response,
                )
                return obj
        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            if operation:
                operation.finish(
                    user,
                    exc_traceback=exc_traceback,
                    exception=e,
                    detail=response,
                )
            raise SPSPkgAddPidV3ToZipFileError(
                f"Unable to add pid v3 to {zip_xml_file_path}, got {response}. Exception {type(e)} {e}"
            )

    def save_pkg_zip_file(self, user, zip_file_path):
        filename = self.sps_pkg_name + ".zip"
        try:
            with TemporaryDirectory() as targetdir:
                with TemporaryDirectory() as workdir:
                    target = os.path.join(targetdir, filename)
                    package = SPPackage.from_file(zip_file_path, workdir)
                    package.optimise(new_package_file_path=target, preserve_files=False)

                with open(target, "rb") as fp:
                    # saved optimised
                    self.file.save(filename, ContentFile(fp.read()))
        except Exception as e:
            with open(zip_file_path, "rb") as fp:
                # saved original
                self.file.save(filename, ContentFile(fp.read()))
        self.save()

    def generate_article_html_page(self, user):
        try:
            generator = HTMLGenerator.parse(
                file=self.xml_uri,
                valid_only=False,
                xslt="3.0",
            )
            for lang in generator.languages:
                PreviewArticlePage.create_or_update(
                    user,
                    self,
                    lang=Language.get_or_create(creator=user, code2=lang),
                    content=str(generator.generate(lang)),
                )
        except Exception as e:
            logging.exception(f"PreviewArticlePage {self.sps_pkg_name} {e}")

    @property
    def subdir(self):
        if not hasattr(self, '_subdir') or not self._subdir:
            sps_pkg_name = self.sps_pkg_name
            subdir = sps_pkg_name[:9]
            suffix = sps_pkg_name[10:]
            self._subdir = os.path.join(subdir, "/".join(suffix.split("-")))
        return self._subdir

    def save_package_in_cloud(self, user, original_pkg_components, article_proc):
        self.save()
        xml_with_pre = self._save_components_in_cloud(
            user, original_pkg_components, article_proc,
        )
        self._local_to_remote(xml_with_pre)
        self._save_xml_in_cloud(user, xml_with_pre, article_proc)
        self.valid_components = self.components.filter(uri__isnull=True).count() == 0
        self.save()

    def _save_components_in_cloud(self, user, original_pkg_components, article_proc):
        op = article_proc.start(user, "_save_components_in_cloud")
        xml_with_pre = None
        mimetypes.init()
        self.components.all().delete()

        failures = []
        with ZipFile(self.file.path) as optimised_fp:
            for item in optimised_fp.namelist():
                name, ext = os.path.splitext(item)

                with optimised_fp.open(item, "r") as optimised_item_fp:
                    content = optimised_item_fp.read()

                if ext == ".xml":
                    xml_with_pre = get_xml_with_pre(content.decode("utf-8"))

                component_data = original_pkg_components.get(item) or {}
                self._save_component_in_cloud(
                    user, item, content, ext, component_data, failures,
                )
        op.finish(user, completed=not failures, detail=failures)
        return xml_with_pre

    def _save_component_in_cloud(self, user, item, content, ext, component_data, failures):
        try:
            response = minio_push_file_content(
                content=content,
                mimetype=mimetypes.types_map[ext],
                object_name=f"{self.subdir}/{item}",
            )
            uri = response["uri"]
        except Exception as e:
            uri = None
            failures.append(
                dict(
                    item_id=item,
                    response=response,
                )
            )
        self.components.add(
            SPSPkgComponent.create_or_update(
                user=user,
                sps_pkg=self,
                uri=uri,
                basename=item,
                component_type=component_data.get("component_type"),
                lang=component_data.get("lang"),
                legacy_uri=component_data.get("legacy_uri"),
            )
        )

    def _local_to_remote(self, xml_with_pre):
        replacements = {
            item.basename: item.uri
            for item in self.components.filter(uri__isnull=False).iterator()
        }
        if replacements:
            xml_assets = ArticleAssets(xml_with_pre.xmltree)
            xml_assets.replace_names(replacements)

    def _save_xml_in_cloud(self, user, xml_with_pre, article_proc):
        op = article_proc.start(user, "_save_xml_in_cloud")
        filename = self.sps_pkg_name + ".xml"
        try:
            response = minio_push_file_content(
                content=xml_with_pre.tostring().encode("utf-8"),
                mimetype=mimetypes.types_map[".xml"],
                object_name=f"{self.subdir}/{filename}",
            )
            uri = response["uri"]
        except Exception as e:
            uri = None
            op.finish(user, completed=False, detail=response)
        self.xml_uri = uri
        self.save()
        self.components.add(
            SPSPkgComponent.create_or_update(
                user=user,
                sps_pkg=self,
                uri=uri,
                basename=filename,
                component_type="xml",
                lang=None,
                legacy_uri=None,
            )
        )
        op.finish(user, completed=True)

    def synchronize(self, user, article_proc):
        zip_xml_file_path = self.file.path

        logging.info(f"Synchronize {zip_xml_file_path}")
        for response in pid_provider_app.request_pid_for_xml_zip(
            zip_xml_file_path, user, is_published=self.is_public
        ):
            if not response["synchronized"]:
                continue

            if response.get("v3") and self.pid_v3 != response.get("v3"):
                # atualiza conteúdo de zip
                with ZipFile(zip_xml_file_path, "a") as zf:
                    zf.writestr(
                        response["filename"], response["xml_with_pre"].tostring()
                    )

                self._save_xml_in_cloud(user, response["xml_with_pre"], article_proc)
                self.generate_article_html_page(user)

            self.registered_in_core = response["synchronized"]
            self.save()
