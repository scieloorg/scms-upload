import logging
import mimetypes
import os

from django.db import models
from django.utils.translation import gettext_lazy as _
from wagtail.admin.panels import FieldPanel

from core.forms import CoreAdminModelForm
from core.models import CommonControlField
from files_storage import exceptions
from files_storage.minio import MinioStorage


COUNTRY_REGION = (
    ("Brasil", "sa-east-1"),
    ("México", "us-west-1"),
    ("Colombia", "sa-east-1"),
    ("Chile", "sa-east-1"),
    ("Cuba", "us-east-1"),
    ("Argentina", "sa-east-1"),
    ("Perú", "sa-east-1"),
    ("Venezuela", "sa-east-1"),
    ("Costa Rica", "us-east-1"),
    ("Bolivia", "sa-east-1"),
    ("Uruguay", "sa-east-1"),
    ("Ecuador", "sa-east-1"),
    ("Paraguay", "sa-east-1"),
    ("España", "eu-south-1"),
    ("Portugal", "eu-west-1"),
    ("South Africa", "af-south-1"),
    ("West Indies", "us-east-1"),
)

class MinioConfiguration(CommonControlField):
    name = models.CharField(_("Name"), max_length=32, null=True, blank=False)
    host = models.CharField(_("Host"), max_length=64, null=True, blank=True)
    bucket_root = models.CharField(_("Bucket root"), max_length=32, null=True, blank=True)
    location = models.CharField(_("Location"), max_length=16, null=True, blank=True, choices=COUNTRY_REGION, default="sa-east-1")
    access_key = models.CharField(_("Access key"), max_length=32, null=True, blank=True)
    secret_key = models.CharField(_("Secret key"), max_length=64, null=True, blank=True)
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
        # FieldPanel("location"),
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
        location=None,
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
            files_storage.location = location
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
            location=obj.location,
            minio_secure=obj.secure,
            minio_http_client=minio_http_client,
        )


class FileLocation(CommonControlField):
    basename = models.CharField(_("Basename"), max_length=100, null=True, blank=True)
    uri = models.URLField(_("URI"), null=True, blank=True, max_length=200)

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
