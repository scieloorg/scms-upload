import logging
import mimetypes
import os
import sys
from io import BytesIO
from shutil import copyfile
from datetime import datetime
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile

from django.core.files.base import ContentFile
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from modelcluster.fields import ParentalKey
from modelcluster.models import ClusterableModel
from lxml import etree
from packtools import HTMLGenerator
from packtools.sps.models.v2.article_assets import ArticleAssets
from packtools.sps.pid_provider.xml_sps_lib import (
    XMLWithPre,
    get_xml_with_pre,
    get_xml_with_pre_from_uri,
)
from packtools.utils import SPPackage
from wagtail.admin.panels import FieldPanel, InlinePanel, ObjectList, TabbedInterface
from wagtail.models import Orderable
from wagtailautocomplete.edit_handlers import AutocompletePanel

from collection import choices as collection_choices
from collection.models import Language
from core.models import CommonControlField
from core.utils.requester import fetch_data
from files_storage.models import FileLocation, MinioConfiguration
from package import choices
from pid_provider.requester import PidRequester
from tracker.models import UnexpectedEvent

pid_provider_app = PidRequester()


class SPSPkgOptimizeError(Exception):
    ...


class SPSPkgAddPidV3ToZipFileError(Exception):
    ...


class AddPidV3ToXMLFileError(Exception):
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


def update_zip_file(zip_xml_file_path, response, xml_with_pre):
    try:
        if not response.pop("xml_changed"):
            return
    except KeyError:
        return

    new_xml = xml_with_pre.tostring(pretty_print=True)
    with TemporaryDirectory() as targetdir:
        new_zip_path = os.path.join(targetdir, os.path.basename(zip_xml_file_path))
        with ZipFile(new_zip_path, "a", compression=ZIP_DEFLATED) as new_zfp:
            with ZipFile(zip_xml_file_path) as zfp:
                for item in zfp.namelist():
                    if item == response["filename"]:
                        new_zfp.writestr(item, new_xml)
                    else:
                        new_zfp.writestr(item, zfp.read(item))
        copyfile(new_zip_path, zip_xml_file_path)


def basic_xml_directory_path(instance, filename):
    try:
        return f"{instance.directory_path}/{filename}"
    except AttributeError:
        name, ext = os.path.splitext(filename)
        if "-" in filename:
            subdir = name.replace("-", "/")
            return f"sps_pkg/{subdir}/{filename}"
        else:
            subdir = os.path.join(name[0], name[-1], name)
            return f"xml/{filename}"


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
    sps_pkg_name = instance.sps_pkg_name
    subdir = "/".join(sps_pkg_name.split("-"))
    return f"sps_pkg/{subdir}/{filename}"


def preview_page_directory_path(instance, filename):
    sps_pkg_name = instance.sps_pkg.sps_pkg_name
    subdir = "/".join(sps_pkg_name.split("-"))
    return f"sps_pkg/{subdir}/{filename}"


class SPSPkgComponent(FileLocation, Orderable):
    # herdados de FileLocation
    # - basename = models.TextField(_("Basename"), null=True, blank=True)
    # - uri = models.URLField(_("URI"), null=True, blank=True)
    sps_pkg = ParentalKey("SPSPkg", related_name="components")
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
    legacy_uri = models.CharField(max_length=120, null=True, blank=True)

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
    file = models.FileField(
        upload_to=preview_page_directory_path, null=True, blank=True
    )

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

    # XML URI
    xml_uri = models.URLField(null=True, blank=True)

    # pacote veio da migração ou do ingresso de novos conteúdos
    origin = models.CharField(
        max_length=32,
        null=True,
        blank=True,
        choices=choices.PKG_ORIGIN,
    )
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
        InlinePanel("components", label=_("Package component")),
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
        ordering = ["-updated"]

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
        for item in self.components.filter(component_type="rendition"):
            yield {
                "lang": item.lang and item.lang.code2,
                "url": item.uri,
                "basename": item.basename,
                "legacy_uri": item.legacy_uri,
            }

    @property
    def htmls(self):
        for item in self.components.filter(component_type="html"):
            yield {"lang": item.lang and item.lang.code2, "url": item.uri}

    @property
    def supplementary_materials(self):
        for item in self.components.filter(component_type="supplementary-material"):
            yield {
                "lang": item.lang and item.lang.code2,
                "url": item.uri,
                "basename": item.basename,
                "legacy_uri": item.legacy_uri,
                "xml_elem_id": item.xml_elem_id,
            }

    @classmethod
    def get(cls, pid_v3):
        return cls.objects.get(pid_v3=pid_v3)

    def set_registered_in_core(self, value):
        PidRequester.set_registered_in_core(self.pid_v3, value)

    @staticmethod
    def is_registered_in_core(pid_v3):
        if not pid_v3:
            return False
        try:
            obj = SPSPkg.objects.get(pid_v3=pid_v3)
            return obj.registered_in_core
        except SPSPkg.DoesNotExist:
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

            obj.upload_package_to_the_cloud(user, original_pkg_components, article_proc)
            obj.validate(True)

            article_proc.update_sps_pkg_status()
            operation.finish(user, completed=obj.is_complete, detail=obj.data)

            return obj

        except Exception as e:
            logging.exception(e)
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
                == set(texts.get("html_langs"))
            )
        else:
            self.valid_texts = set(texts.get("xml_langs")) == set(
                texts.get("pdf_langs")
            )
        if save:
            self.save()

    @property
    def is_complete(self):
        return self.registered_in_core and self.valid_texts and self.valid_components

    @property
    def data(self):
        return dict(
            registered_in_core=self.registered_in_core,
            texts=self.texts,
            components=[item.data for item in self.components.all()],
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

    def fix_pid_v2(self, user, correct_pid_v2):
        return pid_provider_app.fix_pid_v2(user, self.pid_v3, correct_pid_v2)

    @classmethod
    def add_pid_v3_to_zip(cls, user, zip_xml_file_path, is_public, article_proc):
        """
        Solicita PID versão 3

        """
        try:
            response = None
            operation = None

            for response in pid_provider_app.request_pid_for_xml_zip(
                zip_xml_file_path,
                user,
                is_published=is_public,
                article_proc=article_proc,
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

                update_zip_file(zip_xml_file_path, response, xml_with_pre)

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

                # saved optimised
                with open(target, "rb") as fp:
                    self.save_file(filename, fp.read())
        except Exception as e:
            # saved original
            with open(zip_file_path, "rb") as fp:
                self.save_file(filename, fp.read())

    def save_file(self, name, content):
        try:
            self.file.delete(save=True)
        except Exception as e:
            pass
        try:
            self.file.save(name, ContentFile(content))
        except Exception as e:
            raise Exception(f"Unable to save {name}. Exception: {e}")

    @property
    def subdir(self):
        if not hasattr(self, "_subdir") or not self._subdir:
            sps_pkg_name = self.sps_pkg_name
            subdir = sps_pkg_name[:9]
            suffix = sps_pkg_name[10:]
            self._subdir = os.path.join(subdir, "/".join(suffix.split("-")))
        return self._subdir

    def upload_package_to_the_cloud(self, user, original_pkg_components, article_proc):
        self.save()
        self.components.all().delete()

        xml_with_pre = self.upload_items_to_the_cloud(
            user,
            article_proc,
            "upload_assets_to_the_cloud",
            self.upload_assets_to_the_cloud,
            **{"original_pkg_components": original_pkg_components},
        )
        self.upload_items_to_the_cloud(
            user,
            article_proc,
            "upload_xml_to_the_cloud",
            self.upload_xml_to_the_cloud,
            **{"xml_with_pre": xml_with_pre},
        )
        self.upload_items_to_the_cloud(
            user,
            article_proc,
            "upload_article_page_to_the_cloud",
            self.upload_article_page_to_the_cloud,
        )
        self.valid_components = not self.components.filter(uri__isnull=True).exists()
        self.save()

    def upload_items_to_the_cloud(
        self, user, article_proc, operation_title, callable_get_items, **params
    ):
        op = article_proc.start(user, operation_title)
        response = callable_get_items(user, **params)
        detail = dict(response)
        try:
            xml_with_pre = detail.pop("xml_with_pre")
        except KeyError:
            xml_with_pre = None

        completed = True
        for item in response["items"]:
            try:
                k = item["uri"]
            except KeyError:
                completed = False
                break
        op.finish(user, completed=completed, detail=detail)
        return xml_with_pre

    def upload_to_the_cloud(
        self,
        user,
        filename,
        ext,
        content,
        component_type,
        lang=None,
        legacy_uri=None,
        error=None,
        error_type=None,
    ):
        try:
            uri = None
            response = {}

            if content:
                response = minio_push_file_content(
                    content=content,
                    mimetype=mimetypes.types_map[ext],
                    object_name=f"{self.subdir}/{filename}",
                )
                uri = response["uri"]
        except Exception as e:
            error = str(e)
            error_type = str(type(e))

        if error:
            response.update(
                dict(
                    basename=filename,
                    error=error,
                    error_type=error_type,
                )
            )
        SPSPkgComponent.create_or_update(
            user=user,
            sps_pkg=self,
            uri=uri,
            basename=filename,
            component_type=component_type,
            lang=lang,
            legacy_uri=legacy_uri,
        )
        response["filename"] = filename
        return response

    def upload_assets_to_the_cloud(self, user, original_pkg_components):
        xml_with_pre = None
        items = []
        with ZipFile(self.file.path) as optimised_fp:
            for item in set(optimised_fp.namelist()):
                name, ext = os.path.splitext(item)
                content = optimised_fp.read(item)
                if ext == ".xml":
                    xml_with_pre = get_xml_with_pre(content.decode("utf-8"))

                else:
                    component = original_pkg_components.get(item) or {}
                    result = self.upload_to_the_cloud(
                        user=user,
                        filename=item,
                        ext=ext,
                        content=content,
                        component_type=component.get("component_type") or "asset",
                        lang=component.get("lang"),
                        legacy_uri=component.get("legacy_uri"),
                    )
                    items.append(result)
        return {"xml_with_pre": xml_with_pre, "items": items}

    def upload_xml_to_the_cloud(self, user, xml_with_pre):
        replacements = {
            item.basename: item.uri
            for item in self.components.filter(uri__isnull=False).iterator()
        }
        if replacements:
            xml_assets = ArticleAssets(xml_with_pre.xmltree)
            xml_assets.replace_names(replacements)

        content = xml_with_pre.tostring(pretty_print=True).encode("utf-8")

        filename = self.sps_pkg_name + ".xml"

        result = self.upload_to_the_cloud(
            user, filename, ".xml", content, "xml", lang=None, legacy_uri=None
        )
        self.xml_uri = result.get("uri")
        self.save()
        return {"items": [result]}

    def generate_article_html_pages(self):
        try:
            generator = HTMLGenerator.parse(
                etree.parse(BytesIO(fetch_data(self.xml_uri))),
                valid_only=False,
                xslt="3.0",
            )
            for lang in generator.languages:
                suffix = f"-{lang}"
                yield {
                    "filename": f"{self.sps_pkg_name}{suffix}.html",
                    "content": str(generator.generate(lang)),
                    "lang": lang,
                    "ext": ".html",
                    "component_type": "html",
                }
        except Exception as exc:
            for lang in self.texts["xml_langs"]:
                suffix = f"-{lang}"
                yield {
                    "uri": self.xml_uri,
                    "filename": f"{self.sps_pkg_name}{suffix}.html",
                    "error": str(exc),
                    "error_type": str(type(exc)),
                    "lang": lang,
                    "ext": ".html",
                    "component_type": "html",
                }

    def upload_article_page_to_the_cloud(self, user):
        items = []
        for item in self.generate_article_html_pages():
            lang = item["lang"]
            try:
                content = item["content"].encode("utf-8")
            except KeyError:
                content = None
            # PreviewArticlePage.create_or_update(
            #     user,
            #     self,
            #     lang=Language.get_or_create(creator=user, code2=lang),
            #     content=content,
            # )
            response = self.upload_to_the_cloud(
                user,
                item["filename"],
                item["ext"],
                content,
                item["component_type"],
                lang,
                legacy_uri=None,
                error=item.get("error"),
                error_type=item.get("error_type"),
            )
            items.append(response)
        return {"items": items}

    def synchronize(self, user, article_proc):
        pass
        # zip_xml_file_path = self.file.path

        # logging.info(f"Synchronize {zip_xml_file_path}")
        # for response in pid_provider_app.request_pid_for_xml_zip(
        #     zip_xml_file_path, user, is_published=self.is_public
        # ):
        #     if not response["synchronized"]:
        #         continue

        #     if response.get("v3") and self.pid_v3 != response.get("v3"):
        #         # atualiza conteúdo de zip
        #         with ZipFile(zip_xml_file_path, "a", compression=ZIP_DEFLATED) as zf:
        #             zf.writestr(
        #                 response["filename"],
        #                 response["xml_with_pre"].tostring(pretty_print=True),
        #             )

        #         self.upload_xml_to_the_cloud(user, response["xml_with_pre"], article_proc)
        #         self.upload_article_page_to_the_cloud(user, article_proc)

        #     self.registered_in_core = response["synchronized"]
        #     self.save()

    def get_zip_filename_and_content(self):
        d = {}
        with open(self.file.path, "rb") as fp:
            d["content"] = fp.read()
        d["filename"] = self.sps_pkg_name + ".zip"
        return d
