from django.db import models
from django.utils.translation import gettext_lazy as _

from core.forms import CoreAdminModelForm
from core.models import CommonControlField

from .choices import JOURNAL_AVAILABILTY_STATUS, WEBSITE_KIND


class Collection(CommonControlField):
    """
    Class that represent the Collection
    """

    def __unicode__(self):
        return self.acron

    def __str__(self):
        return self.acron

    acron = models.TextField(_("Collection Acronym"), null=True, blank=True)
    name = models.TextField(_("Collection Name"), null=True, blank=True)

    base_form_class = CoreAdminModelForm

    @classmethod
    def get_or_create(cls, acron, name=None, user=None):
        try:
            return Collection.objects.get(acron=acron)
        except Collection.DoesNotExist:
            collection = Collection()
            collection.acron = acron
            collection.name = name
            collection.creator = user
            collection.save()
            return collection


class NewWebSiteConfiguration(CommonControlField):
    url = models.CharField(_("New website url"), max_length=255, null=True, blank=True)
    db_uri = models.CharField(
        _("Mongodb Info"),
        max_length=255,
        null=True,
        blank=True,
        help_text=_("mongodb://login:password@host:port/database"),
    )

    def __str__(self):
        return f"{self.url}"

    class Meta:
        indexes = [
            models.Index(fields=["url"]),
        ]

    base_form_class = CoreAdminModelForm


class FilesStorageConfiguration(CommonControlField):
    host = models.CharField(_("Host"), max_length=255, null=True, blank=True)
    bucket_root = models.CharField(
        _("Bucket root"), max_length=255, null=True, blank=True
    )
    bucket_app_subdir = models.CharField(
        _("Bucket app subdir"), max_length=64, null=True, blank=True
    )
    bucket_public_subdir = models.CharField(
        _("Bucket public subdir"), max_length=64, null=True, blank=True
    )
    bucket_migration_subdir = models.CharField(
        _("Bucket migration subdir"), max_length=64, null=True, blank=True
    )
    bucket_temp_subdir = models.CharField(
        _("Bucket temp subdir"), max_length=64, null=True, blank=True
    )
    bucket_versions_subdir = models.CharField(
        _("Bucket versions subdir"), max_length=64, null=True, blank=True
    )
    access_key = models.CharField(
        _("Access key"), max_length=255, null=True, blank=True
    )
    secret_key = models.CharField(
        _("Secret key"), max_length=255, null=True, blank=True
    )
    secure = models.BooleanField(_("Secure"), default=True)

    def __str__(self):
        return f"{self.host} {self.bucket_root}"

    class Meta:
        unique_together = [
            ["host", "bucket_root"],
        ]
        indexes = [
            models.Index(fields=["host"]),
            models.Index(fields=["bucket_root"]),
        ]

    base_form_class = CoreAdminModelForm


class Language(CommonControlField):
    """
    Represent the list of states

    Fields:
        name
        code2
    """

    name = models.TextField(_("Language Name"), blank=True, null=True)
    code2 = models.TextField(_("Language code 2"), blank=True, null=True)

    class Meta:
        verbose_name = _("Language")
        verbose_name_plural = _("Languages")

    def __unicode__(self):
        return self.code2 or "idioma ausente / não informado"

    def __str__(self):
        return self.code2 or "idioma ausente / não informado"

    @classmethod
    def get(cls, name=None, code2=None):
        if code2:
            return cls.objects.get(code2=code2)
        if name:
            return cls.objects.get(name=name)

    @classmethod
    def get_or_create(cls, name=None, code2=None, creator=None):
        try:
            if not name and not code2:
                raise ValueError("Language.get_or_create requires name or code2")
            return cls.get(name, code2)
        except cls.DoesNotExist:
            if not creator:
                raise ValueError("Language.get_or_create requires creator")
            obj = Language()
            obj.name = name
            obj.code2 = code2
            obj.creator = creator
            obj.save()
            return obj

    base_form_class = CoreAdminModelForm
