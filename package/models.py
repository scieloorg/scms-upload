import logging
import mimetypes
import os
from datetime import datetime
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from django.core.files.base import ContentFile
from django.db import models
from django.utils.translation import gettext_lazy as _
from packtools.sps.models.v2.article_assets import ArticleAssets
from packtools.sps.pid_provider.xml_sps_lib import XMLWithPre, get_xml_with_pre
from packtools.utils import SPPackage
from wagtail.admin.panels import FieldPanel, InlinePanel
from wagtailautocomplete.edit_handlers import AutocompletePanel

from collection.models import Language
from collection import choices as collection_choices
from core.models import CommonControlField
from files_storage.models import FileLocation, MinioConfiguration
from package import choices
from pid_requester.controller import PidRequester

pid_requester_app = PidRequester()


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


class SPSComponentCreateOrUpdateError(Exception):
    ...


class SPSPackageCreateOrUpdateError(Exception):
    ...


class OptimisedSPSPackageError(Exception):
    ...


class XMLVersionXmlWithPreError(Exception):
    ...


def basic_xml_directory_path(instance, filename):
    # file will be uploaded to MEDIA_ROOT/user_<id>/<filename>
    pid = instance.pid
    return f"xmlsps/basic/{filename[0]}/{filename[-1]}/{filename}"


class BasicXMLFile(CommonControlField):
    file = models.FileField(upload_to=basic_xml_directory_path, null=True, blank=True)

    panels = [
        FieldPanel("file"),
    ]

    class Meta:
        abstract = True

    def __str__(self):
        return f"{self.file.path}"

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
        if self.file:
            try:
                with open(self.file.path, "rb") as fp:
                    c = fp.read()
                    if c == content:
                        logging.info("skip save file")
                        return
                    else:
                        self.file.delete(save=True)
            except Exception as e:
                pass
        self.file.save(name, ContentFile(content))
        logging.info(f"Saved {self.file.path}")

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


class PkgAnnotation(CommonControlField):
    sps_pkg = models.ForeignKey(
        "SPSPkg", on_delete=models.SET_NULL, null=True, blank=True
    )
    annotation_type = models.CharField(
        max_length=32,
        null=True,
        blank=True,
        choices=choices.ANNOTATION_TYPES,
        default=choices.ANNOTATION_COMMENT,
    )
    annotation_subtype = models.TextField(null=True, blank=True)
    annotation_text = models.TextField(null=True, blank=True)
    detail = models.JSONField(null=True, blank=True)

    panels = [
        AutocompletePanel("sps_pkg", target_model="SPSPkg"),
        FieldPanel("annotation_type"),
        FieldPanel("annotation_subtype"),
        FieldPanel("annotation_text"),
        FieldPanel("detail"),
    ]

    @classmethod
    def create(
        cls,
        creator,
        annotation_type,
        annotation_text,
        annotation_subtype=None,
        e=None,
        sps_pkg=None,
        detail=None,
    ):
        logging.info(f"PkgAnnotation {annotation_text}")
        logging.exception(e)

        if e:
            detail = detail or {}
            detail["exception_msg"] = str(e)

        # exc_type, exc_value, exc_traceback = sys.exc_info()
        obj = cls()
        obj.creator = creator
        obj.sps_pkg = sps_pkg
        obj.detail = detail
        obj.annotation_type = annotation_type
        obj.annotation_subtype = annotation_subtype or (str(type(e)) if e else None)
        obj.annotation_text = annotation_text
        obj.save()
        return obj


def pkg_directory_path(instance, filename):
    subdir = "/".join(instance.sps_pkg_name.split("-"))
    return f"pkg/{subdir}/{filename}"


class SPSComponent(FileLocation):
    category = models.CharField(
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

    autocomplete_search_field = "uri"

    class Meta:
        indexes = [
            models.Index(fields=["lang"]),
            models.Index(fields=["category"]),
        ]

    panels = FileLocation.panels + [
        FieldPanel("category"),
        AutocompletePanel("lang"),
    ]

    @classmethod
    def get(cls, uri=None):
        if uri:
            return cls.objects.get(uri=uri)

    @classmethod
    def create_or_update(cls, user, uri, basename=None, category=None, lang=None):
        try:
            obj = cls.objects.get(uri=uri)
            obj.updated_by = user
        except cls.DoesNotExist:
            obj = cls()
            obj.uri = uri
            obj.basename = basename
            obj.creator = user

        try:
            obj.category = category
            if lang:
                obj.lang = Language.get_or_create(creator=user, code2=lang)
            obj.save()
            return obj
        except Exception as e:
            raise SPSComponentCreateOrUpdateError(
                f"Unable to create or update componentfile: {uri} {basename} {e} {str(type(e))}"
            )


class SPSPkg(CommonControlField):
    pid_v3 = models.CharField(max_length=23, null=True, blank=True)
    sps_pkg_name = models.CharField(_("SPS Name"), max_length=32, null=True, blank=True)
    file = models.FileField(upload_to=pkg_directory_path, null=True, blank=True)
    components = models.ManyToManyField(SPSComponent)
    xml_uri = models.URLField(null=True, blank=True)
    origin = models.CharField(
        max_length=32,
        null=True,
        blank=True,
        choices=choices.PKG_ORIGIN,
        default=choices.PKG_ORIGIN_INGRESS_WITHOUT_VALIDATION,
    )
    annotations = models.ManyToManyField(PkgAnnotation)
    is_published = models.BooleanField(null=True, blank=True)
    panels = [
        FieldPanel("sps_pkg_name"),
        # FieldPanel("file")
        FieldPanel("pid_v3"),
        FieldPanel("xml_uri"),
        InlinePanel("components"),
        FieldPanel("origin"),
        InlinePanel("annotations"),
    ]

    class Meta:
        indexes = [
            models.Index(fields=["pid_v3"]),
        ]

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
        return self.components.filter(category="rendition").iterator()

    @property
    def supplementary_material(self):
        return self.components.filter(category='"supplementary-material"').iterator()

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
        reset_failures,
        is_published,
    ):
        response = cls.request_pid_v3(user, sps_pkg_zip_path, is_published)

        try:
            obj = cls.get_or_create(user, response["v3"], response["filename"])
            obj.sps_pkg_name = response["xml_with_pre"].sps_pkg_name
            obj.origin = origin or obj.origin
            obj.is_published = is_published or obj.is_published

        except (TypeError, ValueError, KeyError) as e:
            raise SPSPackageCreateOrUpdateError(
                f"Unable to SPSPkg.create_or_update {e} {response}"
            )

        if reset_failures:
            try:
                obj.annotations.filter(
                    annotation_type=choices.ANNOTATION_EXECUTION_FAILURE
                ).delete()
            except Exception as e:
                logging.exception(e)

        if response["xml_changed"]:
            # atualiza conteúdo de zip
            with ZipFile(sps_pkg_zip_path, "a") as zf:
                zf.writestr(response["filename"], response["xml_with_pre"].tostring())

        obj.optimise_pkg(sps_pkg_zip_path, user)
        obj.push_package(user)
        obj.save()
        return obj

    @classmethod
    def request_pid_v3(cls, user, zip_xml_file_path, is_published):
        """
        Solicita PID versão 3
        """
        try:
            logging.info(f"Request PID V3 para {zip_xml_file_path}")
            responses = pid_requester_app.request_pid_for_xml_zip(
                zip_xml_file_path, user, is_published=is_published
            )
        except Exception as e:
            message = _("Unable to request_pid_v3 {}").format(zip_xml_file_path)
            PkgAnnotation.create(
                creator=user,
                annotation_type=choices.ANNOTATION_EXECUTION_FAILURE,
                annotation_text=message,
                e=e,
                sps_pkg=None,
                detail={
                    "action": "request_pid_v3",
                    "zip_xml_file_path": zip_xml_file_path,
                },
            )
            return
        for response in responses:
            logging.info(f"pid requester response: {response}")
            if not response.get("v3"):
                PkgAnnotation.create(
                    creator=user,
                    annotation_type=choices.ANNOTATION_EXECUTION_FAILURE,
                    annotation_text=message,
                    e=None,
                    sps_pkg=None,
                    detail={
                        "action": "request_pid_v3",
                        "zip_xml_file_path": zip_xml_file_path,
                        "responses": list(responses),
                    },
                )

            return response

    def optimise_pkg(self, zip_file_path, user):
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
            message = _("Unable to build optimised sps package {}").format(
                self.sps_pkg_name
            )
            self.annotations.add(
                PkgAnnotation.create(
                    creator=user,
                    annotation_type=choices.ANNOTATION_EXECUTION_FAILURE,
                    annotation_text=message,
                    e=e,
                    sps_pkg=self,
                    detail={"action": "optimise_pkg"},
                )
            )

    def push_package(self, user):
        sps_pkg_name = self.sps_pkg_name
        subdir = sps_pkg_name[:9]
        suffix = sps_pkg_name[10:]
        subdir = os.path.join(subdir, "/".join(suffix.split("-")))

        xml_with_pre = self._push_components(user, subdir)

        xml_assets = ArticleAssets(xml_with_pre.xmltree)
        self._set_component_category_and_lang(xml_assets, user)

        self._local_to_remote(xml_assets)
        self._push_xml(user, xml_with_pre, subdir, self.sps_pkg_name + ".xml")

    def _push_components(self, user, subdir):
        xml_with_pre = None
        with ZipFile(self.file.path) as optimised_fp:
            for item in optimised_fp.namelist():
                logging.info(f"{self.file.path} {item}")
                with optimised_fp.open(item, "r") as optimised_item_fp:
                    name, ext = os.path.splitext(item)
                    if ext == ".xml":
                        xml_name = item
                        xml_with_pre = get_xml_with_pre(
                            optimised_item_fp.read().decode("utf-8")
                        )
                        continue

                    response = self._push_file(
                        content=optimised_item_fp.read(),
                        ext=ext,
                        subdir=subdir,
                        sps_filename=item,
                        user=user,
                    )
        return xml_with_pre

    def _set_component_category_and_lang(self, xml_assets, user):
        for asset in xml_assets.items:
            try:
                component = self.components.filter(
                    basename=asset.xlink_href,
                )[0]
            except IndexError:
                continue
            else:
                component.xml_elem_id = asset.id
                component.category = (
                    "supplementary-material"
                    if asset.is_supplementary_material
                    else "asset"
                )
                component.save()
        for component in self.components.filter(category__isnull=True):
            name, ext = os.path.splitext(component.basename)
            if ext == ".pdf":
                if name[-3] == "-":
                    if name[-2:]:
                        component.lang = Language.get_or_create(
                            creator=user, code2=name[-2:]
                        )
                component.category = "rendition"
            elif ext == ".xml":
                component.category = "xml"
            component.save()

    def _local_to_remote(self, xml_assets):
        # Troca href local por href remoto (sps_filename -> uri)
        xml_assets.replace_names(
            {item.basename: item.uri for item in self.components.iterator()}
        )

    def _push_xml(self, user, xml_with_pre, subdir, filename):
        response = self._push_file(
            content=xml_with_pre.tostring().encode("utf-8"),
            ext=".xml",
            subdir=subdir,
            sps_filename=filename,
            user=user,
        )
        self.xml_uri = response.get("uri")
        self.save()

    def _push_file(self, content, ext, subdir, sps_filename, user):
        mimetypes.init()
        try:
            # fput_content(self, content, mimetype, object_name)
            logging.info(f"ArticlePackages._push_file {sps_filename}")
            response = minio_push_file_content(
                content=content,
                mimetype=mimetypes.types_map[ext],
                object_name=f"{subdir}/{sps_filename}",
            )
            self.components.add(
                SPSComponent.create_or_update(
                    user=user, uri=response["uri"], basename=sps_filename
                )
            )
            return response
        except Exception as e:
            logging.info(response)
            logging.exception(e)
            message = _("Unable to register file in minio {} {}").format(
                sps_filename, response
            )
            self.annotations.add(
                PkgAnnotation.create(
                    creator=user,
                    annotation_type=choices.ANNOTATION_EXECUTION_FAILURE,
                    annotation_text=message,
                    e=e,
                    sps_pkg=None,
                    detail={"action": "minio_push_file_content", "response": response},
                )
            )
            return response

    def add_annotation(
        self,
        user,
        annotation_type,
        annotation_text,
        annotation_subtype=None,
        e=None,
        detail=None,
    ):
        self.annotations.add(
            PkgAnnotation.create(
                creator=user,
                annotation_type=annotation_type,
                annotation_text=annotation_text,
                annotation_subtype=annotation_subtype,
                e=e,
                sps_pkg=self,
                detail=detail,
            )
        )
