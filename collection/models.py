import logging

from django.db import models
from django.utils.translation import gettext_lazy as _
from wagtailautocomplete.edit_handlers import AutocompletePanel
from wagtail.admin.panels import FieldPanel, InlinePanel

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

    def autocomplete_label(self):
        return self.name

    @classmethod
    def get(cls, acron):
        if acron:
            return Collection.objects.get(acron=acron)
        raise ValueError("Collection.get requires acron")

    @classmethod
    def get_or_create(cls, acron, name=None, user=None):
        try:
            return Collection.get(acron=acron)
        except Collection.DoesNotExist:
            collection = Collection()
            collection.acron = acron
            collection.name = name
            collection.creator = user
            collection.save()
            return collection


class WebSiteConfiguration(CommonControlField):
    collection = models.ForeignKey(
        Collection, null=True, blank=True, on_delete=models.SET_NULL
    )
    url = models.URLField(_("Website URL"), max_length=255, null=True, blank=True)
    api_url_article = models.URLField(
        _("Article API URL"), max_length=255, null=True, blank=True
    )
    api_url_issue = models.URLField(
        _("Issue API URL"), max_length=255, null=True, blank=True
    )
    api_url_journal = models.URLField(
        _("Journal API URL"), max_length=255, null=True, blank=True
    )
    api_get_token_url = models.URLField(
        _("Get token API URL"), max_length=255, null=True, blank=True
    )
    api_username = models.CharField(max_length=64, null=True, blank=True)
    api_password = models.CharField(max_length=64, null=True, blank=True)
    api_token = models.CharField(max_length=255, null=True, blank=True)

    db_name = models.CharField(
        _("Database name"), max_length=255, null=True, blank=True
    )
    db_uri = models.CharField(
        _("Mongodb Info"),
        max_length=255,
        null=True,
        blank=True,
        help_text=_("mongodb://login:password@host:port/database"),
    )
    purpose = models.CharField(
        _("Purpose"), max_length=25, choices=WEBSITE_KIND, null=True, blank=True
    )
    enabled = models.BooleanField()

    def __str__(self):
        return f"{self.url} {self.collection} {self.purpose}"

    class Meta:
        indexes = [
            models.Index(fields=["purpose"]),
            models.Index(fields=["url"]),
        ]

    base_form_class = CoreAdminModelForm

    panels = [
        AutocompletePanel("collection"),
        FieldPanel("url"),
        FieldPanel("purpose"),
        FieldPanel("db_uri"),
        FieldPanel("db_name"),
        FieldPanel("api_url_article"),
        FieldPanel("api_url_issue"),
        FieldPanel("api_url_journal"),
        FieldPanel("api_get_token_url"),
        FieldPanel("api_username"),
        FieldPanel("api_password"),
        FieldPanel("api_token"),
        FieldPanel("enabled"),
    ]

    @classmethod
    def get(cls, url=None, collection=None, purpose=None):
        if url:
            return cls.objects.get(url=url)
        if collection and purpose:
            return cls.objects.get(collection=collection, purpose=purpose)
        raise ValueError(
            "WebSiteConfiguration.get requires url or collection and purpose parameters"
        )

    @classmethod
    def create_or_update(
        cls,
        user,
        collection,
        url=None,
        purpose=None,
        db_uri=None,
        db_name=None,
        api_url_article=None,
        api_url_issue=None,
        api_url_journal=None,
        api_get_token_url=None,
        api_username=None,
        api_password=None,
        api_token=None,
        enabled=None,
    ):
        try:
            obj = cls.get(url, collection, purpose)
            obj.updated_by = user
        except cls.DoesNotExist:
            obj = cls()
            obj.creator = user
            obj.collection = collection or obj.collection
            obj.url = url or obj.url
            obj.purpose = purpose or obj.purpose

        obj.db_name = db_name or obj.db_name
        obj.db_uri = db_uri or obj.db_uri
        obj.api_url_journal = api_url_journal or obj.api_url_journal
        obj.api_url_issue = api_url_issue or obj.api_url_issue
        obj.api_url_article = api_url_article or obj.api_url_article
        obj.api_get_token_url = api_get_token_url or obj.api_get_token_url
        obj.api_username = api_username or obj.api_username
        obj.api_password = api_password or obj.api_password
        obj.api_token = api_token or obj.api_token
        obj.enabled = bool(enabled or obj.enabled)
        obj.save()
        return obj


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

    def autocomplete_label(self):
        return self.code2

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
