import logging
from datetime import datetime

from django.db import models
from django.utils.translation import gettext_lazy as _
from modelcluster.fields import ParentalKey
from modelcluster.models import ClusterableModel
from wagtail.admin.edit_handlers import (
    FieldPanel,
    InlinePanel,
    ObjectList,
    TabbedInterface,
)
from wagtail.images.edit_handlers import ImageChooserPanel
from wagtail.models import Orderable

from collection.models import Collection
from core.models import CommonControlField, RichTextWithLang
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
        return "%s - %s" % (self.issnl, self.title) or ""

    def __str__(self):
        return "%s - %s" % (self.issnl, self.title) or ""

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
        issn_print=None,
        issn_electronic=None,
        issnl=None,
        title=None,
        title_iso=None,
        foundation_year=None,
        user=None,
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

    base_form_class = OfficialJournalForm


class NonOfficialJournalTitle(ClusterableModel, CommonControlField):
    official_journal = models.ForeignKey(
        "OfficialJournal",
        null=True,
        blank=True,
        related_name="OfficialJournal",
        on_delete=models.CASCADE,
    )

    def __unicode__(self):
        return "%s" % (self.official_journal.title)

    def __str__(self):
        return "%s" % (self.official_journal.title)

    panels = [
        FieldPanel("official_journal"),
        InlinePanel("page_non_official_title", label=_("Non Official Journal Title")),
    ]

    base_form_class = OfficialJournalForm


class NonOfficialTitle(Orderable):
    page = ParentalKey(NonOfficialJournalTitle, related_name="page_non_official_title")
    non_official_journal_title = models.TextField(
        _("Non Official Journal Title"), null=False, blank=False
    )


class JournalMission(ClusterableModel):
    official_journal = models.ForeignKey(
        "OfficialJournal",
        null=True,
        blank=True,
        related_name="JournalMission_OfficialJournal",
        on_delete=models.CASCADE,
    )

    panels = [
        FieldPanel("official_journal"),
        InlinePanel("mission", label=_("Mission"), classname="collapsed"),
    ]


class FieldMission(Orderable, RichTextWithLang):
    page = ParentalKey(JournalMission, on_delete=models.CASCADE, related_name="mission")

    def __unicode__(self):
        return "%s %s" % (self.text, self.language)

    def __str__(self):
        return "%s %s" % (self.text, self.language)


class SocialNetwork(models.Model):
    name = models.CharField(
        _("Name"),
        max_length=255,
        choices=choices.SOCIAL_NETWORK_NAMES,
        null=False,
        blank=False,
    )
    url = models.URLField(_("URL"), max_length=255, null=True, blank=False)

    panels = [FieldPanel("name"), FieldPanel("url")]

    class Meta:
        abstract = True


class Journal(ClusterableModel, SocialNetwork):
    """
    Journal para site novo
    """

    short_title = models.CharField(
        _("Short Title"), max_length=100, null=True, blank=True
    )
    official_journal = models.ForeignKey(
        "OfficialJournal",
        null=True,
        blank=True,
        related_name="+",
        on_delete=models.CASCADE,
    )
    logo = models.ForeignKey(
        "wagtailimages.Image",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    submission_online_url = models.URLField(
        _("Submission online URL"), max_length=255, null=True, blank=True
    )

    def __unicode__(self):
        return str(self.official_journal)

    def __str__(self):
        return str(self.official_journal)

    panels_identification = [
        FieldPanel("official_journal"),
        FieldPanel("short_title"),
    ]

    panels_mission = [
        InlinePanel("mission", label=_("Mission"), classname="collapsed"),
    ]

    panels_owner = [
        InlinePanel("owner", label=_("Owner"), classname="collapsed"),
    ]

    panels_editorial_manager = [
        InlinePanel(
            "editorialmanager", label=_("Editorial Manager"), classname="collapsed"
        ),
    ]

    panels_publisher = [
        InlinePanel("publisher", label=_("Publisher"), classname="collapsed"),
    ]

    panels_sponsor = [
        InlinePanel("sponsor", label=_("Sponsor"), classname="collapsed"),
    ]

    panels_website = [
        ImageChooserPanel("logo", heading=_("Logo")),
        FieldPanel("submission_online_url"),
        InlinePanel("journalsocialnetwork", label=_("Social Network")),
    ]

    edit_handler = TabbedInterface(
        [
            ObjectList(panels_identification, heading=_("Identification")),
            ObjectList(panels_mission, heading=_("Missions")),
            ObjectList(panels_owner, heading=_("Owners")),
            ObjectList(panels_editorial_manager, heading=_("Editorial Manager")),
            ObjectList(panels_publisher, heading=_("Publisher")),
            ObjectList(panels_sponsor, heading=_("Sponsor")),
            ObjectList(panels_website, heading=_("Website")),
        ]
    )

    @classmethod
    def get(cls, official_journal):
        logging.info(f"Journal.get({official_journal}")
        if official_journal:
            return cls.objects.get(official_journal=official_journal)

    @classmethod
    def create_or_update(
        cls,
        creator=None,
        official_journal=None,
    ):
        logging.info(f"Journal.create_or_update({official_journal}")
        try:
            obj = cls.get(official_journal=official_journal)
            logging.info("update {}".format(obj))
            obj.updated_by = creator
            obj.updated = datetime.utcnow()
        except cls.DoesNotExist:
            obj = cls()
            obj.official_journal = official_journal
            obj.creator = creator
            logging.info("create {}".format(obj))

        obj.official_journal = official_journal or obj.official_journal
        obj.save()
        logging.info(f"return {obj}")
        return obj


class Mission(Orderable, RichTextWithLang):
    page = ParentalKey(Journal, on_delete=models.CASCADE, related_name="mission")


class Owner(Orderable, InstitutionHistory):
    page = ParentalKey(Journal, on_delete=models.CASCADE, related_name="owner")


class EditorialManager(Orderable, InstitutionHistory):
    page = ParentalKey(
        Journal, on_delete=models.CASCADE, related_name="editorialmanager"
    )


class Publisher(Orderable, InstitutionHistory):
    page = ParentalKey(Journal, on_delete=models.CASCADE, related_name="publisher")


class Sponsor(Orderable, InstitutionHistory):
    page = ParentalKey(Journal, on_delete=models.CASCADE, related_name="sponsor")


class JournalSocialNetwork(Orderable, SocialNetwork):
    page = ParentalKey(
        Journal, on_delete=models.CASCADE, related_name="journalsocialnetwork"
    )


class SciELOJournal(CommonControlField):
    """
    Class that represents journals data in a SciELO Collection context
    Its attributes are related to the journal in collection
    For official data, use Journal model

    SciELO tem particularidades, como scielo_issn é um ISSN adotado como ID
    na coleção e este dado dentre as coleções podem divergir
    """

    collection = models.ForeignKey(
        Collection, null=True, blank=True, on_delete=models.SET_NULL
    )
    scielo_issn = models.CharField(
        _("SciELO ISSN"), max_length=9, null=False, blank=False
    )
    acron = models.CharField(_("Acronym"), max_length=25, null=True, blank=True)
    title = models.TextField(_("Title"), null=True, blank=True)
    availability_status = models.CharField(
        _("Availability Status"),
        max_length=10,
        null=True,
        blank=True,
        choices=choices.JOURNAL_AVAILABILTY_STATUS,
    )
    official_journal = models.ForeignKey(
        OfficialJournal, on_delete=models.SET_NULL, null=True
    )

    class Meta:
        unique_together = [
            ["collection", "scielo_issn"],
            ["collection", "acron"],
        ]
        indexes = [
            models.Index(fields=["acron"]),
            models.Index(fields=["collection"]),
            models.Index(fields=["scielo_issn"]),
            models.Index(fields=["availability_status"]),
            models.Index(fields=["official_journal"]),
        ]

    def __unicode__(self):
        return "%s %s" % (self.collection, self.scielo_issn)

    def __str__(self):
        return "%s %s" % (self.collection, self.scielo_issn)

    @classmethod
    def get(cls, collection, official_journal=None, scielo_issn=None, acron=None):
        logging.info(
            f"SciELOJournal.get({collection}, {official_journal}, {scielo_issn}, {acron})"
        )
        if not collection:
            raise ValueError("SciELOJournal.get requires collection")
        if official_journal:
            return cls.objects.get(
                collection=collection, official_journal=official_journal
            )
        if acron:
            return cls.objects.get(collection=collection, acron=acron)
        if scielo_issn:
            return cls.objects.get(collection=collection, scielo_issn=scielo_issn)

    @classmethod
    def create_or_update(
        cls,
        collection,
        scielo_issn=None,
        creator=None,
        official_journal=None,
        acron=None,
        title=None,
        availability_status=None,
    ):
        if not collection:
            raise ValueError("SciELOJournal.create_or_update requires collection")
        if not scielo_issn and not official_journal:
            raise ValueError(
                "SciELOJournal.create_or_update requires scielo_issn or official_journal"
            )
        logging.info(
            f"SciELOJournal.create_or_update {collection} {official_journal} {scielo_issn}"
        )
        try:
            obj = cls.get(
                collection=collection,
                acron=acron,
                scielo_issn=scielo_issn,
                official_journal=official_journal,
            )
            logging.info("update {}".format(obj))
            obj.updated_by = creator
            obj.updated = datetime.utcnow()
        except cls.DoesNotExist:
            obj = cls()
            obj.creator = creator
            logging.info("create {}".format(obj))

        obj.collection = collection or obj.collection
        obj.official_journal = official_journal or obj.official_journal
        obj.scielo_issn = scielo_issn or obj.scielo_issn
        obj.acron = acron or obj.acron
        obj.title = title or obj.title
        obj.availability_status = availability_status or obj.availability_status
        obj.save()
        logging.info(f"return {obj}")
        return obj
