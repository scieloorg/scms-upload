import logging
from datetime import datetime

from django.db import models
from django.utils.translation import gettext_lazy as _
from modelcluster.fields import ParentalKey
from modelcluster.models import ClusterableModel
from wagtail.admin.panels import FieldPanel, InlinePanel, TabbedInterface, ObjectList
from wagtail.models import Orderable
from wagtailautocomplete.edit_handlers import AutocompletePanel

from proc.models import JournalProc
from core.choices import MONTHS
from core.forms import CoreAdminModelForm
from core.models import CommonControlField, RichTextWithLang
from institution.models import InstitutionHistory

from . import choices
from .forms import OfficialJournalForm
from . exceptions import MissionCreateOrUpdateError, MissionGetError, SubjectCreationOrUpdateError

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
    submission_online_url = models.URLField(
        _("Submission online URL"), null=True, blank=True
    )
    subject = models.ManyToManyField(
        "Subject",
        verbose_name=_("Study Areas"),
        blank=True,
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

    panels_mission = [
        InlinePanel("mission", label=_("Mission"), classname="collapsed"),
    ]

    edit_handler = TabbedInterface(
        [
            ObjectList(panels_identification, heading=_("Identification")),
            ObjectList(panels_owner, heading=_("Owners")),
            ObjectList(panels_publisher, heading=_("Publisher")),
            ObjectList(panels_mission, heading=_("Mission")),
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


class Sponsor(Orderable, InstitutionHistory):
    journal = ParentalKey(Journal, related_name="sponsor", null=True, blank=True, on_delete=models.SET_NULL)


class Mission(Orderable, RichTextWithLang, CommonControlField):
    journal = ParentalKey(
        Journal, on_delete=models.SET_NULL, related_name="mission", null=True
    )

    class Meta:
        indexes = [
            models.Index(
                fields=[
                    "journal",
                ]
            ),
            models.Index(
                fields=[
                    "language",
                ]
            ),
        ]

    @property
    def data(self):
        d = {}

        if self.journal:
            d.update(self.journal.data)

        return d

    @classmethod
    def get(
        cls,
        journal,
        language,
    ):
        if journal and language:
            return cls.objects.filter(journal=journal, language=language)
        raise MissionGetError("Mission.get requires journal and language parameters")

    @classmethod
    def create_or_update(
        cls,
        user,
        journal,
        language,
        mission_text,
    ):
        if not mission_text:
            raise MissionCreateOrUpdateError(
                "Mission.create_or_update requires mission_rich_text parameter"
            )
        try:
            obj = cls.get(journal, language)
            obj.updated_by = user
        except IndexError:
            obj = cls()
            obj.creator = user
        except (MissionGetError, cls.MultipleObjectsReturned) as e:
            raise MissionCreateOrUpdateError(
                _("Unable to create or update journal {}").format(e)
            )
        obj.text = mission_text or obj.text
        obj.language = language or obj.language
        obj.journal = journal or obj.journal
        obj.save()
        return obj
    

class JournalHistory(CommonControlField, Orderable):
    journal_proc = ParentalKey(
        JournalProc,
        on_delete=models.SET_NULL,
        related_name="journal_history",
        null=True,
    )

    year = models.CharField(_("Event year"), max_length=4, null=True, blank=True)
    month = models.CharField(
        _("Event month"),
        max_length=2,
        choices=MONTHS,
        null=True,
        blank=True,
    )
    day = models.CharField(_("Event day"), max_length=2, null=True, blank=True)

    event_type = models.CharField(
        _("Event type"),
        null=True,
        blank=True,
        max_length=16,
        choices=choices.JOURNAL_EVENT_TYPE,
    )
    interruption_reason = models.CharField(
        _("Indexing interruption reason"),
        null=True,
        blank=True,
        max_length=16,
        choices=choices.INDEXING_INTERRUPTION_REASON,
    )

    base_form_class = CoreAdminModelForm

    panels = [
        FieldPanel("year"),
        FieldPanel("month"),
        FieldPanel("day"),
        FieldPanel("event_type"),
        FieldPanel("interruption_reason"),
    ]

    class Meta:
        verbose_name = _("Event")
        verbose_name_plural = _("Events")
        indexes = [
            models.Index(
                fields=[
                    "event_type",
                ]
            ),
        ]

    @property
    def data(self):
        d = {
            "event_type": self.event_type,
            "interruption_reason": self.interruption_reason,
            "year": self.year,
            "month": self.month,
            "day": self.day,
        }

        return d

    @property
    def date(self):
        return f"{self.year}-{self.month}-{self.day}"

    def __str__(self):
        return f"{self.event_type} {self.interruption_reason} {self.year}/{self.month}/{self.day}"

    @classmethod
    def am_to_core(
        cls,
        scielo_journal,
        initial_year,
        initial_month,
        initial_day,
        final_year,
        final_month,
        final_day,
        event_type,
        interruption_reason,
    ):
        """
        Funcao para API article meta.
        Atualiza o Type Event de JournalHistory.
        """
        reasons = {
            None: "ceased",
            "not-open-access": "not-open-access",
            "suspended-by-committee": "by-committee",
            "suspended-by-editor": "by-editor",
        }
        try:
            obj = cls.objects.get(
                scielo_journal=scielo_journal,
                year=initial_year,
                month=initial_month,
                day=initial_day,
            )
        except cls.DoesNotExist:
            obj = cls()
            obj.scielo_journal = scielo_journal
            obj.year = initial_year
            obj.month = initial_month
            obj.day = initial_day
        obj.event_type = "ADMITTED"
        obj.save()

        if final_year and event_type:
            try:
                obj = cls.objects.get(
                    scielo_journal=scielo_journal,
                    year=final_year,
                    month=final_month,
                    day=final_day,
                )
            except cls.DoesNotExist:
                obj = cls()
                obj.scielo_journal = scielo_journal
                obj.year = final_year
                obj.month = final_month
                obj.day = final_day
            obj.event_type = "INTERRUPTED"
            obj.interruption_reason = reasons.get(interruption_reason)
            obj.save()


class Subject(CommonControlField):
    code = models.CharField(max_length=30, null=True, blank=True)
    value = models.CharField(max_length=100, null=True, blank=True)

    def __str__(self):
        return f"{self.value}"

    @classmethod
    def load(cls, user):
        if not cls.objects.exists():
            for item in choices.STUDY_AREA:
                code, _ = item
                cls.create_or_update(
                    code=code,
                    user=user,
                )

    @classmethod
    def get(cls, code):
        if not code:
            raise ValueError("Subject.get requires code parameter")
        return cls.objects.get(code=code)

    @classmethod
    def create_or_update(
        cls,
        code,
        user,
    ):
        try:
            obj = cls.get(code=code)
        except cls.DoesNotExist:
            obj = cls()
            obj.code = code
            obj.creator = user
        except SubjectCreationOrUpdateError as e:
            raise SubjectCreationOrUpdateError(code=code, message=e)

        obj.value = dict(choices.STUDY_AREA).get(code) or obj.value
        obj.updated = user
        obj.save()
        return obj