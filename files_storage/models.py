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

    autocomplete_search_field = "uri"

    class Meta:
        indexes = [
            models.Index(fields=["uri"]),
        ]

    panels = [
        FieldPanel("basename"),
        FieldPanel("uri"),
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
