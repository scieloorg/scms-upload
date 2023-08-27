import logging
import mimetypes
import os
from zipfile import ZipFile

from django.db import models
from django.utils.translation import gettext_lazy as _
from packtools.sps.models.v2.article_assets import ArticleAssets
from packtools.sps.pid_provider.xml_sps_lib import get_xml_with_pre
from wagtail.admin.panels import FieldPanel

from core.forms import CoreAdminModelForm
from core.models import CommonControlField
from files_storage import exceptions
from files_storage.minio import MinioStorage
from package.models import SPSPkg


class MinioConfiguration(CommonControlField):
    name = models.TextField(_("Name"), null=True, blank=False)
    host = models.TextField(_("Host"), null=True, blank=True)
    bucket_root = models.TextField(_("Bucket root"), null=True, blank=True)
    bucket_app_subdir = models.TextField(_("Bucket app subdir"), null=True, blank=True)
    access_key = models.TextField(_("Access key"), null=True, blank=True)
    secret_key = models.TextField(_("Secret key"), null=True, blank=True)
    # indicar como False para uso no desenvolvimento
    secure = models.BooleanField(_("Secure"), default=True)

    class Meta:
        indexes = [
            models.Index(fields=["name"]),
            models.Index(fields=["host"]),
            models.Index(fields=["bucket_root"]),
        ]

    panels = [
        FieldPanel("name"),
        FieldPanel("host"),
        FieldPanel("bucket_root"),
        FieldPanel("bucket_app_subdir"),
        FieldPanel("access_key"),
        FieldPanel("secret_key"),
        FieldPanel("secure"),
    ]

    base_form_class = CoreAdminModelForm

    def __str__(self):
        return f"{self.host} {self.bucket_root}"

    def __unicode__(self):
        return f"{self.host} {self.bucket_root}"

    @classmethod
    def get_or_create(
        cls,
        name,
        host=None,
        access_key=None,
        secret_key=None,
        secure=None,
        bucket_root=None,
        bucket_app_subdir=None,
        user=None,
    ):
        try:
            return cls.objects.get(name=name)
        except cls.DoesNotExist:
            files_storage = cls()
            files_storage.name = name
            files_storage.host = host
            files_storage.secure = secure
            files_storage.access_key = access_key
            files_storage.secret_key = secret_key
            files_storage.bucket_root = bucket_root
            files_storage.bucket_app_subdir = bucket_app_subdir
            files_storage.creator = user
            files_storage.save()
            return files_storage

    @classmethod
    def get(cls, name):
        try:
            return cls.objects.get(name=name)
        except cls.DoesNotExist:
            return

    @classmethod
    def get_files_storage(cls, name, minio_http_client=None):
        try:
            obj = cls.get(name=name) or cls.objects.first()
        except:
            return

        return MinioStorage(
            minio_host=obj.host,
            minio_access_key=obj.access_key,
            minio_secret_key=obj.secret_key,
            bucket_root=obj.bucket_root,
            bucket_subdir=obj.bucket_app_subdir,
            minio_secure=obj.secure,
            minio_http_client=minio_http_client,
        )


class FileLocation(CommonControlField):
    basename = models.TextField(_("Basename"), null=True, blank=True)
    uri = models.URLField(_("URI"), null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["basename"]),
        ]

    def __unicode__(self):
        return f"{self.uri} {self.created}"

    def __str__(self):
        return f"{self.uri} {self.created}"

    @classmethod
    def get_or_create(cls, creator, uri, basename=None):
        try:
            return cls.objects.get(uri=uri)
        except cls.DoesNotExist:
            obj = cls()
            obj.uri = uri
            obj.basename = basename
            obj.creator = creator
            obj.save()
            return obj
        except Exception as e:
            raise exceptions.MinioFileGetOrCreateError(
                "Unable to create file: %s %s %s" % (type(e), e, obj)
            )


class RemoteSPSPkg(CommonControlField):
    sps_pkg = models.ForeignKey(
        SPSPkg, null=True, blank=True, on_delete=models.SET_NULL
    )
    locations = models.ManyToManyField(FileLocation)

    @property
    def xml_with_pre(self):
        return self.sps_pkg.xml_with_pre

    def update_xml(self, xml_with_pre):
        self.update_xml(xml_with_pre)

    @classmethod
    def create_or_update(cls, user, sps_pkg):
        try:
            obj = cls.objects.get(sps_pkg=sps_pkg)
            obj.updated_by = user
        except cls.DoesNotExist:
            obj = cls()
            obj.sps_pkg = sps_pkg
            obj.creator = user
        obj.save()
        return obj

    def publish_package(self, minio_push_file_content, user):
        mimetypes.init()

        sps_pkg_name = self.sps_pkg.sps_pkg_name
        subdir = sps_pkg_name[:9]
        suffix = sps_pkg_name[10:]
        subdir = os.path.join(subdir, "/".join(suffix.split("-")))
        xml_with_pre = None

        local_to_remote = {}
        with ZipFile(self.sps_pkg.file.path) as optimised_fp:
            for item in optimised_fp.namelist():
                with optimised_fp.open(item) as optimised_item_fp:
                    name, ext = os.path.splitext(item)
                    if ext == ".xml":
                        xml_name = item
                        xml_with_pre = get_xml_with_pre(
                            optimised_item_fp.read().decode("utf-8")
                        )
                        continue

                    response = self._register_remote_file(
                        minio_push_file_content,
                        content=optimised_item_fp.read(),
                        ext=ext,
                        subdir=subdir,
                        sps_filename=item,
                        user=user,
                    )
                    try:
                        local_to_remote[item] = response["uri"]
                    except KeyError:
                        pass
                    yield response

            if xml_with_pre:
                if local_to_remote:
                    # Troca href local por href remoto (sps_filename -> uri)
                    xml_assets = ArticleAssets(xml_with_pre.xmltree)
                    xml_assets.replace_names(local_to_remote)
                response = self._register_remote_file(
                    minio_push_file_content,
                    content=xml_with_pre.tostring(),
                    ext=".xml",
                    subdir=subdir,
                    sps_filename=xml_name,
                    user=user,
                )
                yield response

    def _register_remote_file(
        self, minio_push_file_content, content, ext, subdir, sps_filename, user
    ):
        try:
            # fput_content(self, content, mimetype, object_name)
            logging.info(f"ArticlePackages._register_remote_file {sps_filename}")
            response = minio_push_file_content(
                content=content,
                mimetype=mimetypes.types_map[ext],
                object_name=f"{subdir}/{sps_filename}",
            )
            self.locations.add(
                FileLocation.get_or_create(
                    creator=user, uri=response["uri"], basename=sps_filename
                )
            )
            return response
        except Exception as e:
            logging.info(response)
            logging.exception(e)
            message = _("Unable to register file in minio {} {}").format(
                sps_filename, response
            )
            return dict(
                e=e,
                migrated_item_name="remote_file",
                migrated_item_id=sps_filename,
                message=message,
                action_name="minio_push_file_content",
            )
