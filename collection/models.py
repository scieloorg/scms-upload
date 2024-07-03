import logging

from django.db import models
from django.utils.translation import gettext_lazy as _
from modelcluster.fields import ParentalKey
from modelcluster.models import ClusterableModel
from wagtail.admin.panels import FieldPanel, InlinePanel
from wagtailautocomplete.edit_handlers import AutocompletePanel

from core.forms import CoreAdminModelForm
from core.models import CommonControlField

from collection import choices
from core.choices import LANGUAGE
from collection.utils import language_iso


class LanguageGetOrCreateError(Exception):
    ...


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

    autocomplete_search_field = "name"

    def autocomplete_label(self):
        return f"{self.name} ({self.acron})"

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


class WebSiteConfiguration(CommonControlField, ClusterableModel):
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
    purpose = models.CharField(
        _("Purpose"), max_length=25, choices=choices.WEBSITE_KIND, null=True, blank=True
    )
    enabled = models.BooleanField()

    autocomplete_search_field = "collection__name"

    def autocomplete_label(self):
        return f"{self.url})"

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
        FieldPanel("api_url_article"),
        FieldPanel("api_url_issue"),
        FieldPanel("api_url_journal"),
        FieldPanel("api_get_token_url"),
        FieldPanel("api_username"),
        FieldPanel("api_password"),
        FieldPanel("enabled"),
        InlinePanel("endpoint", label=_("EndPoints"), classname="collapsed"),
    ]

    @classmethod
    def get(cls, url=None, collection=None, purpose=None):
        params = dict(url=url, collection=collection, purpose=purpose)
        logging.info(f"Collection.get({params})")
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
        api_url_article=None,
        api_url_issue=None,
        api_url_journal=None,
        api_url=None,
        api_get_token_url=None,
        api_username=None,
        api_password=None,
        enabled=None,
    ):
        """
        api_url:
            [{"url": "https://example.com", "name": "example"}]
        """
        try:
            obj = cls.get(url, collection, purpose)
            obj.updated_by = user
        except cls.DoesNotExist:
            obj = cls()
            obj.creator = user
            obj.collection = collection or obj.collection
            obj.url = url or obj.url
            obj.purpose = purpose or obj.purpose

        obj.api_url_journal = api_url_journal or obj.api_url_journal
        obj.api_url_issue = api_url_issue or obj.api_url_issue
        obj.api_url_article = api_url_article or obj.api_url_article
        obj.api_get_token_url = api_get_token_url or obj.api_get_token_url
        obj.api_username = api_username or obj.api_username
        obj.api_password = api_password or obj.api_password
        obj.enabled = bool(enabled or obj.enabled)

        obj.save()
        data = []
        for api in api_url:
            if api:
                we, created = WebSiteConfigurationEndpoint.objects.get_or_create(
                    url=api.get("url"),
                    name=api.get("name"),
                    enabled=True,
                    creator=user,
                )
                data.append(we)
        obj.endpoint.set(data)
        obj.save()
        return obj


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
    def load(cls, user=None):
        if cls.objects.count() == 0:
            for k, v in LANGUAGE:
                cls.get_or_create(name=v, code2=k, creator=user)

    @classmethod
    def get(cls, name=None, code2=None):
        code2 = language_iso(code=code2)
        if code2:
            if not code2.isalpha() or len(code2) != 2:
                raise ValueError(f"Language.get_or_create invalid code2 {code2}")
            return cls.objects.get(code2=code2)
        if name:
            return cls.objects.get(name=name)
        raise ValueError("Language.get_or_create requires name or code2")

    @classmethod
    def get_or_create(cls, name=None, code2=None, creator=None):
        try:
            return cls.get(name, code2)
        except cls.MultipleObjectsReturned as e:
            # logging.exception(f"Language.get_or_create raise {e}: {name} {code2}")
            return cls.objects.filter(code2=code2).first()
        except cls.DoesNotExist:
            if not creator:
                raise ValueError("Language.get_or_create requires creator")
            obj = Language()
            obj.name = name
            obj.code2 = code2
            obj.creator = creator
            try:
                obj.save()
            except Exception as e:
                raise LanguageGetOrCreateError(
                    f"Unable to create Language {code2} {name}. Exception: {e}"
                )
            return obj

    base_form_class = CoreAdminModelForm


class WebSiteConfigurationEndpoint(CommonControlField):
    """
    Registro de Endpoints para WebSiteConfiguration
    """

    config = ParentalKey(
        "WebSiteConfiguration",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="endpoint",
    )
    name = models.CharField(_("Endpoint name"), max_length=255, null=True, blank=True)
    url = models.URLField(_("Endpoint URL"), max_length=128, null=True, blank=True)
    enabled = models.BooleanField(default=False)

    panels = [
        FieldPanel("name"),
        FieldPanel("url"),
        FieldPanel("enabled"),
    ]

    class Meta:
        indexes = [
            models.Index(fields=["name"]),
            models.Index(fields=["enabled"]),
        ]

    def __str__(self):
        return f"{self.url} {self.enabled}"
