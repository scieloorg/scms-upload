import logging
from datetime import datetime

from django.db import IntegrityError, models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from modelcluster.fields import ParentalKey
from modelcluster.models import ClusterableModel
from wagtail.admin.panels import FieldPanel, InlinePanel, ObjectList, TabbedInterface
from wagtail.models import Orderable
from wagtailautocomplete.edit_handlers import AutocompletePanel

from collection.models import Collection
from core.choices import MONTHS
from core.forms import CoreAdminModelForm
from core.models import CommonControlField, HTMLTextModel, TextModel
from institution.models import Institution, InstitutionHistory
from journal import choices
from journal.exceptions import (
    MissionCreateOrUpdateError,
    MissionGetError,
    SubjectCreationOrUpdateError,
)
from journal.forms import OfficialJournalForm
from location.models import Location


class JournalSection(TextModel, CommonControlField):
    parent = models.ForeignKey(
        "Journal",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="j_sections",
    )
    code = models.CharField(max_length=16, null=True, blank=True)

    class Meta:
        unique_together = [("parent", "language", "code", "text")]
        indexes = [
            models.Index(
                fields=[
                    "text",
                ]
            ),
            models.Index(
                fields=[
                    "code",
                ]
            ),
        ]

    autocomplete_search_field = "text"

    def autocomplete_label(self):
        if self.code:
            return f"{self.code} {self.language} {self.text}"
        return f"{self.parent.title} {self.language} {self.text}"

    @classmethod
    def get(cls, parent, language, code, text):
        try:
            if code:
                return cls.objects.get(parent=parent, language=language, code=code)
            else:
                return cls.objects.get(parent=parent, language=language, text=text)
        except cls.MultipleObjectsReturned:
            if code:
                return cls.objects.filter(
                    parent=parent, language=language, code=code
                ).first()
            else:
                return cls.objects.filter(
                    parent=parent, language=language, text=text
                ).first()

    @classmethod
    def create(cls, user, parent, language, code, text):
        try:
            obj = cls(
                creator=user, parent=parent, language=language, code=code, text=text
            )
            obj.save()
            return obj
        except IntegrityError as e:
            return cls.get(parent=parent, language=language, code=code, text=text)

    @classmethod
    def create_or_update(cls, user, parent, language=None, code=None, text=None):
        if not language:
            data = {
                "parent": str(parent),
                "code": code,
                "text": text,
            }
        try:
            obj = cls.get(parent=parent, language=language, code=code, text=text)
            obj.save()
            return obj
        except cls.DoesNotExist:
            return cls.create(user, parent, language, code=code, text=text)

    @property
    def data(self):
        return {"language": self.language.code2, "code": self.code, "text": self.text}

    @staticmethod
    def sections(journal):
        for item in JournalSection.objects.filter(parent=journal):
            yield item.data

    @staticmethod
    def sections_by_code(journal):
        items = {}
        if JournalSection.objects.filter(parent=journal, code__isnull=False).exists():
            for item in JournalSection.objects.filter(parent=journal):
                items.setdefault(item.code, [])
                items[item.code].append(item.data)
        return items

    @staticmethod
    def section_titles_by_language(journal):
        # expected_toc_sections : dict, such as:
        #     {
        #         "en": ["Health Sciences"],
        #         "pt": ["Ciências da Saúde"]
        #     }
        d = {}
        for item in JournalSection.objects.filter(parent=journal).iterator():
            language = item.language.code2
            d.setdefault(language, [])
            d[language].append(item.text)
        return d


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
    title = models.CharField(_("Title"), max_length=265, null=True, blank=True)
    acron = models.CharField(_("Journal Acronym"), max_length=8, null=True, blank=True)
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
    license_code = models.CharField(max_length=16, null=True, blank=True)
    nlm_title = models.CharField(max_length=265, null=True, blank=True)
    doi_prefix = models.CharField(max_length=16, null=True, blank=True)
    logo_url = models.URLField(null=True, blank=True)
    contact_name = models.TextField(null=True, blank=True)
    contact_address = models.TextField(_("Address"), null=True, blank=True)
    contact_location = models.ForeignKey(
        Location, on_delete=models.SET_NULL, null=True, blank=True
    )

    def __unicode__(self):
        return self.title or self.short_title or str(self.official_journal)

    def __str__(self):
        return self.title or self.short_title or str(self.official_journal)

    base_form_class = OfficialJournalForm

    panels_identification = [
        AutocompletePanel("official_journal"),
        FieldPanel("short_title"),
        FieldPanel("acron")
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
    def first_letters(self):
        return "".join(
            word[0]
            for word in (self.short_title or self.official_journal.title_iso).split()
        ).upper()

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

    @staticmethod
    def get_registered(journal_title, issn_electronic, issn_print):
        q = Q()
        if journal_title:
            q |= Q(title=journal_title)
        if issn_electronic:
            q |= Q(issn_electronic=issn_electronic)
        if issn_print:
            q |= Q(issn_print=issn_print)

        try:
            j = OfficialJournal.objects.get(q)
            return Journal.objects.get(official_journal=j)
        except OfficialJournal.DoesNotExist:
            raise Journal.DoesNotExist(
                f"{journal_title} {issn_electronic} {issn_print}"
            )

    @classmethod
    def create(
        cls,
        user,
        official_journal=None,
        title=None,
        short_title=None,
        acron=None,
    ):
        try:
            obj = cls()
            obj.creator = user
            obj.official_journal = official_journal
            obj.title = title or obj.title
            obj.short_title = short_title or obj.short_title
            obj.acron = acron
            obj.save()
            return obj
        except IntegrityError:
            return cls.get(official_journal)

    @classmethod
    def get(cls, official_journal):
        if official_journal:
            return cls.objects.get(official_journal=official_journal)
        raise ValueError("Journal.get requires official_journal")

    @classmethod
    def create_or_update(
        cls,
        user,
        official_journal=None,
        title=None,
        short_title=None,
        acron=None,
    ):
        logging.info(f"Journal.create_or_update({official_journal}")
        try:
            obj = cls.get(official_journal=official_journal)
            logging.info("update {}".format(obj))
            obj.updated_by = user
            obj.updated = datetime.utcnow()
            obj.official_journal = official_journal or obj.official_journal
            obj.title = title or obj.title
            obj.short_title = short_title or obj.short_title
            obj.acron = acron
            obj.save()
            return obj
        except cls.DoesNotExist:
            return cls.create(user, official_journal, title, short_title, acron)

    @property
    def any_issn(self):
        return self.official_journal and (
            self.official_journal.issn_electronic or self.official_journal.issn_print
        )

    @property
    def is_multilingual(self):
        try:
            return len(self.j_sections.all().values("language__code2")) > 1
        except AttributeError:
            # na dúvida, retorna True
            return True

    @property
    def toc_sections(self):
        return JournalSection.section_titles_by_language(self)

    def is_indexed_at(self, database):
        # TODO
        return True

    @property
    def publisher_names(self):
        # TODO verificar se é owner ou publisher ou ambos
        names = []
        for item in self.owner.all():
            names.append(item.institution.name)
        for item in self.publisher.all():
            if item.institution.name not in names:
                names.append(item.institution.name)
        return names

    def add_email(self, email):
        if email:
            return JournalEmail.create_or_update(self, email)

    @property
    def contact_email(self):
        email = []
        for item in self.journal_email.all():
            email.append(item.email)
        return ", ".join(email)

    @property
    def contact(self):
        contact = dict(
            name=self.contact_name,
            address=self.contact_address,
            city=None,
            state=None,
            country=None,
            email=self.contact_email,
        )
        if self.contact_location:
            cl = self.contact_location
            contact.update(
                dict(
                    city=cl.city and cl.city.name,
                    state=cl.state and cl.state.name,
                    country=cl.country and cl.country.name,
                )
            )
        return contact

    @property
    def subject_areas(self):
        return [item.value for item in self.subject.all()]


class JournalEmail(Orderable):
    journal = ParentalKey(
        Journal, on_delete=models.SET_NULL, related_name="journal_email", null=True
    )
    email = models.EmailField()

    class Meta:
        unique_together = [("journal", "email")]

    @classmethod
    def create(
        cls,
        journal=None,
        email=None,
    ):
        try:
            obj = cls()
            obj.journal = journal
            obj.email = email
            obj.save()
            return obj
        except IntegrityError:
            return cls.get(journal, email)

    @classmethod
    def get(cls, journal, email):
        if journal and email:
            return cls.objects.get(journal=journal, email=email)
        raise ValueError(f"Journal.get requires email and journal ({dict(journal=journal, email=email)})")

    @classmethod
    def create_or_update(
        cls,
        journal=None,
        email=None,
    ):
        logging.info(f"Journal.create_or_update({journal})")
        try:
            obj = cls.get(journal, email)
            obj.journal = journal
            obj.email = email
            obj.save()
            return obj
        except cls.DoesNotExist:
            return cls.create(journal, email)


class BaseInstitutionHistory(InstitutionHistory):
    class Meta:
        abstract = True
        unique_together = [("journal", "institution", "initial_date", "final_date")]

    @classmethod
    def get(cls, journal, institution, initial_date=None, final_date=None):
        return cls.objects.get(
            journal=journal,
            institution=institution,
            initial_date=initial_date,
            final_date=final_date,
        )

    @classmethod
    def create(
        cls,
        user,
        journal,
        institution,
        initial_date=None,
        final_date=None,
    ):
        # Institution
        # check if exists the institution
        try:
            obj = cls()
            obj.journal = journal
            obj.institution = institution
            obj.initial_date = initial_date
            obj.final_date = final_date
            obj.creator = user
            obj.save()
            return obj
        except IntegrityError:
            return cls.get(
                journal, institution, initial_date, final_date
            )

    @classmethod
    def create_or_update(
        cls,
        user,
        journal,
        institution,
        initial_date=None,
        final_date=None,
    ):
        # Institution
        # check if exists the institution
        try:
            return cls.get(
                journal, institution, initial_date, final_date
            )
        except cls.MultipleObjectsReturned:
            cls.objects.filter(
                journal=journal,
                institution=institution,
                initial_date=initial_date,
                final_date=final_date
            ).delete()
            return cls.create(
                user,
                journal,
                institution,
                initial_date,
                final_date,
            )
        except cls.DoesNotExist:
            return cls.create(
                user,
                journal,
                institution,
                initial_date,
                final_date,
            )


class Owner(Orderable, BaseInstitutionHistory):
    journal = ParentalKey(
        Journal, related_name="owner", null=True, blank=True, on_delete=models.SET_NULL
    )


class Publisher(Orderable, BaseInstitutionHistory):
    journal = ParentalKey(
        Journal,
        related_name="publisher",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )


class Sponsor(Orderable, BaseInstitutionHistory):
    journal = ParentalKey(
        Journal,
        related_name="sponsor",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )


class Mission(CommonControlField, HTMLTextModel):
    journal = ParentalKey(
        Journal, on_delete=models.SET_NULL, related_name="mission", null=True
    )

    class Meta:
        unique_together = [("journal", "language")]
        indexes = [
            models.Index(
                fields=[
                    "journal",
                ]
            ),
        ]

    @classmethod
    def get(
        cls,
        journal,
        language,
    ):
        if journal and language:
            return cls.objects.get(journal=journal, language=language)
        raise MissionGetError("Mission.get requires journal and language parameters")

    @classmethod
    def create(
        cls,
        user,
        journal,
        language,
        mission_text,
    ):
        if user and journal and language and mission_text:
            try:
                obj = cls()
                obj.creator = user
                obj.text = mission_text or obj.text
                obj.language = language or obj.language
                obj.journal = journal or obj.journal
                obj.save()
                return obj
            except IntegrityError:
                return cls.get(journal, language)
        raise MissionCreateOrUpdateError(
            f"Mission.create requires parameters {dict(user=user, journal=journal, language=language, mission_text=mission_text)}"
        )

    @classmethod
    def create_or_update(
        cls,
        user,
        journal,
        language,
        mission_text,
    ):
        try:
            obj = cls.get(journal, language)
            obj.updated_by = user
            obj.text = mission_text or obj.text
            obj.language = language or obj.language
            obj.journal = journal or obj.journal
            obj.save()
            return obj
        except cls.MultipleObjectsReturned:
            cls.objects.filter(journal=journal, language=language).delete()
            return cls.create(user, journal, language, mission_text)
        except cls.DoesNotExist:
            return cls.create(user, journal, language, mission_text)


class JournalCollection(CommonControlField, ClusterableModel):
    journal = ParentalKey(
        Journal,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="journal_collections",
    )
    collection = models.ForeignKey(
        Collection,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    base_form_class = CoreAdminModelForm

    panels = [
        AutocompletePanel("journal"),
        AutocompletePanel("collection"),
    ]

    class Meta:
        verbose_name = _("Journal collection")
        verbose_name_plural = _("Journal collections")
        unique_together = [
            (
                "journal",
                "collection",
            )
        ]

    @classmethod
    def get(cls, collection, journal):
        return cls.objects.get(
            journal=journal,
            collection=collection,
        )

    @classmethod
    def create(cls, user, collection, journal):
        try:
            obj = cls()
            obj.journal = journal
            obj.collection = collection
            obj.creator = user
            obj.save()
            return obj
        except IntegrityError:
            return cls.get(collection, journal)

    @classmethod
    def create_or_update(cls, user, collection, journal):
        try:
            obj = cls.get(collection, journal)
            obj.updated_by = obj.updated_by or user
            obj.save()
        except cls.DoesNotExist:
            return cls.create(user, collection, journal)

    def __str__(self):
        return f"{self.collection} {self.journal}"


class JournalHistory(CommonControlField):
    journal_collection = ParentalKey(
        JournalCollection,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="journal_history",
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
        max_length=24,
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
        verbose_name = _("Collection journal event")
        verbose_name_plural = _("Collection journal events")
        unique_together = ("journal_collection", "event_type", "year", "month", "day")
        ordering = ("journal_collection", "-year", "-month", "-day")
        indexes = [
            models.Index(
                fields=[
                    "event_type",
                ]
            ),
        ]

    @classmethod
    def get(
        cls, journal_collection, event_type, year, month, day, interruption_reason=None
    ):
        return cls.objects.get(
            journal_collection=journal_collection,
            event_type=event_type,
            year=year,
            month=month,
            day=day,
        )

    @classmethod
    def create(
        cls,
        user,
        journal_collection,
        event_type,
        year,
        month,
        day,
        interruption_reason=None,
    ):
        try:
            obj = cls()
            obj.journal_collection = journal_collection
            obj.event_type = event_type
            obj.year = year
            obj.month = month
            obj.day = day
            obj.interruption_reason = interruption_reason
            obj.creator = user
            obj.save()
            return obj
        except IntegrityError:
            return cls.get(journal_collection, event_type, year, month, day)

    @classmethod
    def create_or_update(
        cls,
        user,
        journal_collection,
        event_type,
        year,
        month,
        day,
        interruption_reason=None,
    ):
        try:
            obj = cls.get(journal_collection, event_type, year, month, day)
            obj.interruption_reason = interruption_reason
            obj.updated_by = obj.updated_by or user
            obj.save()
        except cls.DoesNotExist:
            return cls.create(
                user,
                journal_collection,
                event_type,
                year,
                month,
                day,
                interruption_reason,
            )

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
        return f"{self.year}-{str(self.month).zfill(2)}-{str(self.day).zfill(2)}"

    @property
    def opac_event_type(self):
        if self.event_type == "ADMITTED":
            return "current"
        if "suspended" in self.interruption_reason:
            return "suspended"
        return "inprogress"

    def __str__(self):
        return f"{self.event_type} {self.interruption_reason} {self.year}/{self.month}/{self.day}"


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
        user,
        code,
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
