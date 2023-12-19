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
from pid_requester.controller import PidRequester
from pid_requester.models import PidRequesterXML
from tracker.models import UnexpectedEvent


pid_requester_app = PidRequester()


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
    # file will be uploaded to MEDIA_ROOT/user_<id>/<filename>
    return f"package/basic_xml/{filename[0]}/{filename[-1]}/{filename}"


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
            if self.text == content:
                # it is already updated
                return
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
    is_pid_provider_synchronized = models.BooleanField(null=True, blank=True)

    # porcentagem de ativos digitais registrados no MinIO
    storaged_files_total = models.PositiveSmallIntegerField(null=True, blank=True)
    expected_components_total = models.PositiveSmallIntegerField(null=True, blank=True)
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
        FieldPanel("is_pid_provider_synchronized", read_only=True),
        FieldPanel("valid_texts", read_only=True),
        FieldPanel("valid_components", read_only=True),
        FieldPanel("storaged_files_total", read_only=True),
        FieldPanel("expected_components_total", read_only=True),
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
            models.Index(fields=["is_pid_provider_synchronized"]),
        ]

    def autocomplete_label(self):
        return f"{self.sps_pkg_name} {self.pid_v3}"

    def set_is_pid_provider_synchronized(self):
        try:
            self.is_pid_provider_synchronized = PidRequesterXML.get(
                v3=self.pid_v3
            ).synchronized
        except Exception as e:
            self.is_pid_provider_synchronized = None

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

    @classmethod
    def get_or_create(cls, user, pid_v3, sps_pkg_name):
        try:
            obj = cls.objects.get(pid_v3=pid_v3)
            obj.updated_by = user
        except cls.DoesNotExist:
            obj = cls()
            obj.creator = user
            obj.pid_v3 = pid_v3
        obj.sps_pkg_name = sps_pkg_name
        obj.save()
        return obj

    @classmethod
    def create_or_update(
        cls,
        user,
        sps_pkg_zip_path,
        origin,
        is_public,
        components,
        texts,
    ):
        obj = cls.add_pid_v3_to_zip(user, sps_pkg_zip_path, is_public)
        obj.origin = origin or obj.origin
        obj.is_public = is_public or obj.is_public
        obj.expected_component_total = len(components)
        obj.texts = texts
        if texts.get("html_langs"):
            obj.valid_texts = (
                set(texts.get("xml_langs"))
                == set(texts.get("pdf_langs"))
                == set(texts.get("html_langs"))
            )
        else:
            obj.valid_texts = set(texts.get("xml_langs")) == set(texts.get("pdf_langs"))
        obj.save()

        obj.optimise_pkg(user, sps_pkg_zip_path)

        obj.push_package(user, components)
        obj.storaged_files_total = obj.components.filter(uri__isnull=False).count()
        stored_components = len(
            [item for item in components.values() if item.get("uri")]
        )
        if obj.xml_uri:
            stored_components += 1
        obj.valid_components = stored_components == obj.expected_component_total
        obj.save()

        obj.generate_article_html_page(user)
        return obj

    @classmethod
    def add_pid_v3_to_zip(cls, user, zip_xml_file_path, is_public):
        """
        Solicita PID versão 3

        """
        try:
            response = None
            logging.info(f"Request PID V3 para {zip_xml_file_path}")
            for response in pid_requester_app.request_pid_for_xml_zip(
                zip_xml_file_path, user, is_published=is_public
            ):
                pid_v3 = response["v3"]
                sps_pkg_name = response["xml_with_pre"].sps_pkg_name
                synchronized = response["synchronized"]
                if response["xml_changed"]:
                    # atualiza conteúdo de zip
                    with ZipFile(zip_xml_file_path, "a") as zf:
                        zf.writestr(
                            response["filename"], response["xml_with_pre"].tostring()
                        )

                obj = cls.get_or_create(user, pid_v3, sps_pkg_name)
                obj.is_pid_provider_synchronized = synchronized
                obj.save()
                return obj
        except Exception as e:
            raise SPSPkgAddPidV3ToZipFileError(
                f"Unable to add pid v3 to {zip_xml_file_path}, got {response}. Exception {type(e)} {e}"
            )

    def optimise_pkg(self, user, zip_file_path):
        try:
            with TemporaryDirectory() as targetdir:
                logging.info(f"Cria diretorio destino {targetdir}")

                with TemporaryDirectory() as workdir:
                    logging.info(f"Cria diretorio de trabalho {workdir}")

                    optimised_zip_sps_name = self.sps_pkg_name + ".zip"
                    target = os.path.join(targetdir, optimised_zip_sps_name)

                    package = SPPackage.from_file(zip_file_path, workdir)
                    package.optimise(new_package_file_path=target, preserve_files=False)

                with open(target, "rb") as fp:
                    logging.info(f"Save optimised package {optimised_zip_sps_name}")
                    self.file.save(optimised_zip_sps_name, ContentFile(fp.read()))
        except Exception as e:
            raise SPSPkgOptimizeError(
                f"Unable to optimize package {self.sps_pkg_name}.zip. Exception {type(e)} {e}"
            )

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

    def push_package(self, user, components):
        self.save()
        sps_pkg_name = self.sps_pkg_name
        subdir = sps_pkg_name[:9]
        suffix = sps_pkg_name[10:]
        subdir = os.path.join(subdir, "/".join(suffix.split("-")))

        xml_with_pre = self._push_components(user, subdir, components)

        xml_assets = ArticleAssets(xml_with_pre.xmltree)
        self._local_to_remote(xml_assets)
        self._push_xml(user, xml_with_pre, subdir, sps_pkg_name + ".xml")

    def _push_components(self, user, subdir, components):
        xml_with_pre = None
        mimetypes.init()
        self.components.all().delete()

        # components contém os components antes da otimização
        # que gera novos componentes (miniatura e imagem para web)
        THUMB = ".thumbnail"
        optimised_components = {}
        for k, v in components.items():
            name, ext = os.path.splitext(k)
            if THUMB in name:
                name = name[: name.find(THUMB)]
            optimised_components[name] = v.copy()
            try:
                optimised_components[name].pop("legacy_uri")
            except KeyError:
                logging.info(v)

        with ZipFile(self.file.path) as optimised_fp:
            for item in optimised_fp.namelist():
                name, ext = os.path.splitext(item)

                with optimised_fp.open(item, "r") as optimised_item_fp:
                    content = optimised_item_fp.read()

                if ext == ".xml":
                    xml_name = item
                    try:
                        xml_with_pre = get_xml_with_pre(content.decode("utf-8"))
                    except Exception as e:
                        logging.info(self)
                        logging.exception(e)
                    # registrará XML após trocar o xlink:href por URI do MinIO
                    continue

                try:
                    response = minio_push_file_content(
                        content=content,
                        mimetype=mimetypes.types_map[ext],
                        object_name=f"{subdir}/{item}",
                    )
                    uri = response["uri"]
                except Exception as e:
                    uri = None

                component_data = components.get(item) or {}
                if component_data:
                    components[item]["uri"] = uri
                else:
                    if THUMB in name:
                        name = name[: name.find(THUMB)]
                    component_data = optimised_components.get(name) or {}
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
        return xml_with_pre

    def _local_to_remote(self, xml_assets):
        # Troca href local por href remoto (sps_filename -> uri)
        xml_assets.replace_names(
            {item.basename: item.uri for item in self.components.iterator()}
        )

    def _push_xml(self, user, xml_with_pre, subdir, filename):
        try:
            response = minio_push_file_content(
                content=xml_with_pre.tostring().encode("utf-8"),
                mimetype=mimetypes.types_map[".xml"],
                object_name=f"{subdir}/{filename}",
            )
            uri = response["uri"]
        except Exception as e:
            uri = None
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
