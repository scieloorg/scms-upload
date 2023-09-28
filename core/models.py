import os
from datetime import datetime

from django.contrib.auth import get_user_model
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext as _
from wagtail.admin.panels import FieldPanel
from wagtail.fields import RichTextField
from wagtail.snippets.models import register_snippet

from core.forms import CoreAdminModelForm

from . import choices

User = get_user_model()


class CommonControlField(models.Model):
    """
    Class with common control fields.

    Fields:
        created: Date time when the record was created
        updated: Date time with the last update date
        creator: The creator of the record
        updated_by: Store the last updator of the record
    """

    # Creation date
    created = models.DateTimeField(verbose_name=_("Creation date"), auto_now_add=True)

    # Update date
    updated = models.DateTimeField(verbose_name=_("Last update date"), auto_now=True)

    # Creator user
    creator = models.ForeignKey(
        User,
        verbose_name=_("Creator"),
        related_name="%(class)s_creator",
        editable=False,
        on_delete=models.CASCADE,
    )

    # Last modifier user
    updated_by = models.ForeignKey(
        User,
        verbose_name=_("Updater"),
        related_name="%(class)s_last_mod_user",
        editable=False,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )

    @classmethod
    def get_latest_change(cls):
        dates = []
        try:
            dates.append(cls.objects.latest("updated").updated)
        except:
            pass
        try:
            dates.append(cls.objects.latest("created").created)
        except:
            pass
        try:
            return max(dates)
        except ValueError:
            return

    class Meta:
        abstract = True

    base_form_class = CoreAdminModelForm


class RichTextWithLang(models.Model):
    text = RichTextField(null=False, blank=False)
    language = models.CharField(
        _("Language"), max_length=2, choices=choices.LANGUAGE, null=False, blank=False
    )

    panels = [FieldPanel("text"), FieldPanel("language")]

    class Meta:
        abstract = True


class TextWithLangAndValidity(models.Model):
    text = models.TextField(_("Text"), null=False, blank=False)
    language = models.CharField(
        _("Language"), max_length=2, choices=choices.LANGUAGE, null=False, blank=False
    )
    initial_date = models.DateField(null=True, blank=True)
    final_date = models.DateField(null=True, blank=True)

    panels = [
        FieldPanel("text"),
        FieldPanel("language"),
        FieldPanel("initial_date"),
        FieldPanel("final_date"),
    ]

    class Meta:
        abstract = True


class RichTextWithLangAndValidity(RichTextWithLang):
    initial_date = models.DateField(null=True, blank=True)
    final_date = models.DateField(null=True, blank=True)

    panels = [
        FieldPanel("text"),
        FieldPanel("language"),
        FieldPanel("initial_date"),
        FieldPanel("final_date"),
    ]

    class Meta:
        abstract = True


class TextWithLang(models.Model):
    text = models.TextField(_("Text"), null=False, blank=False)
    language = models.CharField(
        _("Language"), max_length=2, choices=choices.LANGUAGE, null=False, blank=False
    )

    panels = [FieldPanel("text"), FieldPanel("language")]

    class Meta:
        abstract = True


class PublicationMonthModel(models.Model):
    """
    Class PublicationMonthModel

    """

    publication_month_number = models.IntegerField(
        verbose_name=_("Publication month number"),
        null=True,
        blank=True,
        choices=choices.MONTHS,
    )
    publication_month_name = models.CharField(
        verbose_name=_("Publication month name"),
        max_length=20,
        null=True,
        blank=True,
    )

    class Meta:
        abstract = True


class PublicationMonthsRangeModel(models.Model):
    """
    Class PublicationMonthsRangeModel

    """

    publication_initial_month_number = models.IntegerField(
        verbose_name=_("Publication initial month number"),
        choices=choices.MONTHS,
        null=True,
        blank=True,
    )
    publication_initial_month_name = models.CharField(
        verbose_name=_("Publication initial month name"),
        max_length=20,
        null=True,
        blank=True,
    )
    publication_final_month_number = models.IntegerField(
        verbose_name=_("Publication final month number"),
        choices=choices.MONTHS,
        null=True,
        blank=True,
    )
    publication_final_month_name = models.CharField(
        verbose_name=_("Publication final month name"),
        max_length=20,
        null=True,
        blank=True,
    )

    class Meta:
        abstract = True


class IssuePublicationDate(PublicationMonthsRangeModel):
    """
    Class IssuePublicationDate
    """

    publication_date_text = models.CharField(
        verbose_name=_("Publication date text"),
        max_length=255,
        null=True,
    )
    publication_year = models.IntegerField(
        verbose_name=_("Publication year"),
        null=True,
    )

    @property
    def publication_date(self):
        date = {
            "publication_date_text": self.publication_date_text,
            "publication_year": self.publication_year,
            "publication_initial_month_name": self.publication_initial_month_name,
            "publication_initial_month_number": self.publication_initial_month_number,
            "publication_final_month_name": self.publication_final_month_name,
            "publication_final_month_number": self.publication_final_month_number,
        }
        return {k: v for k, v in date.items() if v}

    class Meta:
        abstract = True


class DocumentPublicationDate(IssuePublicationDate):
    """
    Class IssuePublicationDate
    """

    publication_day = models.IntegerField(
        verbose_name=_("Publication year"),
        null=True,
    )

    @property
    def publication_date(self):
        date = {
            "publication_date_text": self.publication_date_text,
            "publication_year": self.publication_year,
            "publication_initial_month_name": self.publication_initial_month_name,
            "publication_initial_month_number": self.publication_initial_month_number,
            "publication_final_month_name": self.publication_final_month_name,
            "publication_final_month_number": self.publication_final_month_number,
            "publication_day": self.publication_day,
        }
        return {k: v for k, v in date.items() if v}

    class Meta:
        abstract = True


class FlexibleDateFieldAdapter:
    def __init__(
        self,
        text=None,
        year=None,
        first_month_number=None,
        first_month_name=None,
        last_month_number=None,
        last_month_name=None,
        day=None,
        data=None,
    ):
        self._data = data or {}
        self._text = data.get("text") or text
        self._year = data.get("year") or year
        self._first_month_number = data.get("first_month_number") or first_month_number
        self._last_month_number = data.get("last_month_number") or last_month_number
        self._first_month_name = data.get("first_month_name") or first_month_name
        self._last_month_name = data.get("last_month_name") or last_month_name
        self._day = data.get("day") or day

    @property
    def data(self):
        if not self._data:
            names = (
                "text",
                "year",
                "first_month_name",
                "first_month_number",
                "last_month_name",
                "last_month_number",
                "day",
            )
            values = (
                self.text,
                self.year,
                self.first_month_name,
                self.first_month_number,
                self.last_month_name,
                self.last_month_number,
                self.day,
            )
            self._data = {}
            for name, value in zip(names, values):
                if value:
                    self._data[name] = value
        return self._data

    @property
    def text(self):
        return self._text

    @text.setter
    def text(self, value):
        # TODO parse value e preenche day, month, year
        self._text = value

    @property
    def day(self):
        return self._day

    @day.setter
    def day(self, value):
        self._day = int(value)

    @property
    def last_month_name(self):
        return self._last_month_name

    @last_month_name.setter
    def last_month_name(self, value):
        self._last_month_name = value

    @property
    def first_month_name(self):
        return self._first_month_name

    @first_month_name.setter
    def first_month_name(self, value):
        self._first_month_name = value

    @property
    def last_month_number(self):
        return self._last_month_number

    @last_month_number.setter
    def last_month_number(self, value):
        self._last_month_number = int(value)

    @property
    def first_month_number(self):
        return self._first_month_number

    @first_month_number.setter
    def first_month_number(self, value):
        self._first_month_number = int(value)

    @property
    def year(self):
        return self._year

    @year.setter
    def year(self, value):
        self._year = int(value)
