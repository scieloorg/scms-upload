import logging
from datetime import datetime

from django.db import models
from django.utils.translation import gettext_lazy as _
from modelcluster.fields import ParentalKey
from modelcluster.models import ClusterableModel
from wagtail.admin.panels import FieldPanel, InlinePanel, TabbedInterface, ObjectList
from wagtail.models import Orderable
from wagtailautocomplete.edit_handlers import AutocompletePanel

from core.models import CommonControlField
from institution.models import InstitutionHistory

from . import choices
from .forms import OfficialJournalForm


class OfficialJournal(CommonControlField):
    """
    Class that represent the Official Journal
    """

    title = models.TextField(_("Official Title"), null=True, blank=True)
    title_iso = models.TextField(_("ISO Title"), null=True, blank=True)
    foundation_year = models.CharField(
        _("Foundation Year"), max_length=4, null=True, blank=True
    )
    issn_print = models.CharField(_("ISSN Print"), max_length=9, null=True, blank=True)
    issn_electronic = models.CharField(
        _("ISSN Eletronic"), max_length=9, null=True, blank=True
    )
    issnl = models.CharField(_("ISSNL"), max_length=9, null=True, blank=True)

    base_form_class = OfficialJournalForm

    autocomplete_search_field = "title"

    def autocomplete_label(self):
        return str(self.title)

    class Meta:
        verbose_name = _("Official Journal")
        verbose_name_plural = _("Official Journals")
        indexes = [
            models.Index(
                fields=[
                    "issn_print",
                ]
            ),
            models.Index(
                fields=[
                    "issn_electronic",
                ]
            ),
            models.Index(
                fields=[
                    "issnl",
                ]
            ),
        ]

    def __unicode__(self):
        return self.title or self.issn_electronic or self.issn_print or ""

    def __str__(self):
        return self.title or self.issn_electronic or self.issn_print or ""

    @property
    def data(self):
        d = {
            "official_journal__title": self.title,
            "official_journal__foundation_year": self.foundation_year,
            "official_journal__issn_print": self.issn_print,
            "official_journal__issn_electronic": self.issn_electronic,
            "official_journal__issnl": self.issnl,
        }
        return d

    @classmethod
    def get(cls, issn_print=None, issn_electronic=None, issnl=None):
        logging.info(f"OfficialJournal.get({issn_print}, {issn_electronic}, {issnl})")
        if issn_electronic:
            return cls.objects.get(issn_electronic=issn_electronic)
        if issn_print:
            return cls.objects.get(issn_print=issn_print)
        if issnl:
            return cls.objects.get(issnl=issnl)

    @classmethod
    def create_or_update(
        cls,
        user,
        issn_print=None,
        issn_electronic=None,
        issnl=None,
        title=None,
        title_iso=None,
        foundation_year=None,
    ):
        logging.info(
            f"OfficialJournal.create_or_update({issn_print}, {issn_electronic}, {issnl})"
        )
        try:
            obj = cls.get(issn_print, issn_electronic, issnl)
            obj.updated_by = user
            obj.updated = datetime.utcnow()
        except cls.DoesNotExist:
            obj = cls()
            obj.creator = user

        obj.issnl = issnl or obj.issnl
        obj.title_iso = title_iso or obj.title_iso
        obj.title = title or obj.title
        obj.issn_print = issn_print or obj.issn_print
        obj.issn_electronic = issn_electronic or obj.issn_electronic
        obj.foundation_year = foundation_year or obj.foundation_year
        obj.save()
        logging.info(f"return {obj}")
        return obj


class Journal(CommonControlField, ClusterableModel):
    """
    Journal para site novo
    """
    short_title = models.CharField(
        _("Short Title"), max_length=100, null=True, blank=True
    )
    title = models.CharField(
        _("Title"), max_length=265, null=True, blank=True
    )
    official_journal = models.ForeignKey(
        "OfficialJournal",
        null=True,
        blank=True,
        related_name="+",
        on_delete=models.SET_NULL,
    )

    def __unicode__(self):
        return self.title or self.short_title or str(self.official_journal)

    def __str__(self):
        return self.title or self.short_title or str(self.official_journal)

    base_form_class = OfficialJournalForm

    panels_identification = [
        AutocompletePanel("official_journal"),
        FieldPanel("short_title"),
    ]

    panels_owner = [
        InlinePanel("owner", label=_("Owner"), classname="collapsed"),
    ]

    panels_publisher = [
        InlinePanel("publisher", label=_("Publisher"), classname="collapsed"),
    ]

    edit_handler = TabbedInterface(
        [
            ObjectList(panels_identification, heading=_("Identification")),
            ObjectList(panels_owner, heading=_("Owners")),
            ObjectList(panels_publisher, heading=_("Publisher")),
        ]
    )

    @property
    def data(self):
        return dict(
            title=self.title,
            issn_print=self.official_journal.issn_print,
            issn_electronic=self.official_journal.issn_electronic,
            foundation_year=self.official_journal.foundation_year,
            created=self.created.isoformat(),
            updated=self.updated.isoformat(),
        )

    def autocomplete_label(self):
        return self.title or self.official_journal.title

    @property
    def logo_url(self):
        return self.logo and self.logo.url

    @classmethod
    def get(cls, official_journal):
        logging.info(f"Journal.get({official_journal})")
        if official_journal:
            return cls.objects.get(official_journal=official_journal)

    @classmethod
    def create_or_update(
        cls,
        user,
        official_journal=None,
        title=None,
        short_title=None,
    ):
        logging.info(f"Journal.create_or_update({official_journal}")
        try:
            obj = cls.get(official_journal=official_journal)
            logging.info("update {}".format(obj))
            obj.updated_by = user
            obj.updated = datetime.utcnow()
        except cls.DoesNotExist:
            obj = cls()
            obj.official_journal = official_journal
            obj.creator = user
            logging.info("create {}".format(obj))

        obj.official_journal = official_journal or obj.official_journal
        obj.title = title or obj.title
        obj.short_title = short_title or obj.short_title

        obj.save()
        logging.info(f"return {obj}")
        return obj

    @property
    def any_issn(self):
        return self.official_journal and (self.official_journal.issn_electronic or self.official_journal.issn_print)


class Owner(Orderable, InstitutionHistory):
    journal = ParentalKey(Journal, related_name="owner", null=True, blank=True, on_delete=models.SET_NULL)


class Publisher(Orderable, InstitutionHistory):
    journal = ParentalKey(Journal, related_name="publisher", null=True, blank=True, on_delete=models.SET_NULL)
