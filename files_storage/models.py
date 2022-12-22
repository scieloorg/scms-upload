import hashlib

from django.db import models
from django.utils.translation import gettext_lazy as _
from wagtail.admin.edit_handlers import (
    FieldPanel,
)
from core.models import CommonControlField
from core.forms import CoreAdminModelForm
from core import choices as core_choices
from . import exceptions


class MinioFile(CommonControlField):
    source_filename = models.CharField(_('Filename'), max_length=255, null=False, blank=False)
    uri = models.URLField(_('URI'), max_length=255, null=True, blank=True)
    finger_print = models.CharField('Finger print', max_length=64, null=True, blank=True)

    def __str__(self):
        return f"{self.source_filename} {self.created} {self.uri}"

    @classmethod
    def generate_finger_print(cls, content):
        if not content:
            return None
        content = (content or '').strip().upper()
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @classmethod
    def create(cls, creator, uri, source_filename, finger_print=None):
        try:
            obj = cls()
            obj.creator = creator
            obj.uri = uri
            obj.source_filename = source_filename
            obj.finger_print = finger_print
            obj.save()
            return obj
        except Exception as e:
            raise exceptions.SavingError(
                "Unable to save new file version: %s %s %s" %
                (type(e), e, obj)
            )

    class Meta:

        indexes = [
            models.Index(fields=['source_filename']),
            models.Index(fields=['creator']),
            models.Index(fields=['updated_by']),
            models.Index(fields=['finger_print']),
        ]

    panels = [
        FieldPanel('source_filename'),
        FieldPanel('uri'),
    ]

    base_form_class = CoreAdminModelForm


class Configuration(CommonControlField):

    name = models.CharField(
        _('Name'), max_length=255, null=True, blank=False)
    host = models.CharField(
        _('Host'), max_length=255, null=True, blank=True)
    bucket_root = models.CharField(
        _('Bucket root'), max_length=255, null=True, blank=True)
    bucket_app_subdir = models.CharField(
        _('Bucket app subdir'), max_length=64, null=True, blank=True)
    access_key = models.CharField(
        _('Access key'), max_length=255, null=True, blank=True)
    secret_key = models.CharField(
        _('Secret key'), max_length=255, null=True, blank=True)
    secure = models.BooleanField(_('Secure'), default=True)

    def __str__(self):
        return f"{self.host} {self.bucket_root}"

    @classmethod
    def get_or_create(
            cls,
            name=None, host=None,
            access_key=None, secret_key=None, secure=None,
            bucket_root=None, bucket_app_subdir=None,
            user=None,
            ):
        kwargs = {}
        if name:
            kwargs['name'] = name
        if host:
            kwargs['host'] = host
        try:
            return cls.objects.get(**kwargs)
        except cls.DoesNotExist:
            files_storage = Configuration()
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

        raise exceptions.GetFilesStorageConfigurationError(
            f"There is no files storage which configuration matches with {kwargs}"
        )

    class Meta:
        indexes = [
            models.Index(fields=['name']),
            models.Index(fields=['host']),
            models.Index(fields=['bucket_root']),
            models.Index(fields=['bucket_app_subdir']),
        ]

    panels = [
        FieldPanel('name'),
        FieldPanel('host'),
        FieldPanel('bucket_root'),
        FieldPanel('bucket_app_subdir'),
        FieldPanel('access_key'),
        FieldPanel('secret_key'),
        FieldPanel('secure'),
    ]

    base_form_class = CoreAdminModelForm
