from datetime import datetime

from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from wagtail.admin.panels import FieldPanel
from wagtailautocomplete.edit_handlers import AutocompletePanel

from collection import choices as collection_choices
from core.models import CommonControlField, IssuePublicationDate
from journal.models import Journal, SciELOJournal

from .forms import IssueForm


class Issue(CommonControlField, IssuePublicationDate):
    """
    Class that represent Issue
    """

    def __unicode__(self):
        return "%s %s %s %s %s" % (
            self.journal,
            self.publication_year,
            self.volume or "",
            self.number or "",
            self.supplement or "",
        )

    def __str__(self):
        return "%s %s %s %s %s" % (
            self.journal,
            self.publication_year,
            self.volume or "",
            self.number or "",
            self.supplement or "",
        )

    journal = models.ForeignKey(
        Journal, on_delete=models.SET_NULL, null=True, blank=True
    )
    volume = models.TextField(_("Volume"), null=True, blank=True)
    number = models.TextField(_("Number"), null=True, blank=True)
    supplement = models.TextField(_("Supplement"), null=True, blank=True)
    publication_year = models.TextField(_("Year"), null=True, blank=True)

    autocomplete_search_field = "journal__title"

    def autocomplete_label(self):
        return self.__str__()

    panels = [
        AutocompletePanel("journal"),
        FieldPanel("publication_year"),
        FieldPanel("volume"),
        FieldPanel("number"),
        FieldPanel("supplement"),
    ]

    base_form_class = IssueForm

    class Meta:
        unique_together = [
            ["journal", "publication_year", "volume", "number", "supplement"],
            ["journal", "volume", "number", "supplement"],
        ]
        indexes = [
            models.Index(fields=["journal"]),
            models.Index(fields=["publication_year"]),
            models.Index(fields=["volume"]),
            models.Index(fields=["number"]),
            models.Index(fields=["supplement"]),
        ]

    @classmethod
    def get(cls, journal, volume, supplement, number):
        return cls.objects.get(
            journal=journal,
            volume=volume,
            supplement=supplement,
            number=number,
        )

    @classmethod
    def get_or_create(cls, journal, volume, supplement, number, publication_year, user):
        try:
            return cls.get(
                journal=journal,
                volume=volume,
                supplement=supplement,
                number=number,
            )
        except cls.DoesNotExist:
            obj = cls()
            obj.journal = journal
            obj.volume = volume
            obj.supplement = supplement
            obj.number = number
            obj.publication_year = publication_year
            obj.creator = user
            obj.save()
            return obj


class SciELOIssue(CommonControlField):
    """
    Class that represents an issue in a SciELO Collection
    Its attributes are related to the issue in collection
    For official data, use Issue model

    SciELO tem particularidades como issue_pid, issue_folder etc
    E dentre as coleções o valor de issue_pid pode divergir
    """

    def __unicode__(self):
        return f"{self.scielo_journal.acron} {self.issue_folder}"

    def __str__(self):
        return f"{self.scielo_journal.acron} {self.issue_folder}"

    scielo_journal = models.ForeignKey(
        SciELOJournal, on_delete=models.SET_NULL, null=True
    )
    issue = models.ForeignKey(Issue, on_delete=models.SET_NULL, null=True)
    issue_pid = models.CharField(_("Issue PID"), max_length=23, null=False, blank=False)
    # v30n1 ou 2019nahead
    issue_folder = models.CharField(
        _("Issue Folder"), max_length=23, null=False, blank=False
    )
    publication_stage = models.CharField(
        _("Publication stage"),
        max_length=16,
        null=True,
        blank=True,
        choices=collection_choices.WS_PUBLICATION_STAGE,
    )

    class Meta:
        unique_together = [
            ["scielo_journal", "issue_pid"],
            ["scielo_journal", "issue_folder"],
            ["issue_pid", "issue_folder"],
        ]
        indexes = [
            models.Index(fields=["issue_pid"]),
            models.Index(fields=["issue_folder"]),
        ]

    @classmethod
    def get(cls, scielo_journal, issue_folder=None, issue_pid=None, issue=None):
        if not scielo_journal:
            raise ValueError("SciELOIssue.get requires scielo_journal")
        if issue_folder:
            return cls.objects.get(
                issue_folder=issue_folder,
                scielo_journal=scielo_journal,
            )
        if issue_pid:
            return cls.objects.get(
                issue_pid=issue_pid,
                scielo_journal=scielo_journal,
            )
        if issue:
            return cls.objects.get(
                issue=issue,
                scielo_journal=scielo_journal,
            )

    @classmethod
    def create_or_update(cls, scielo_journal, issue_pid, issue_folder, issue, user):
        try:
            obj = cls.get(
                scielo_journal=scielo_journal,
                issue_pid=issue_pid,
                issue_folder=issue_folder,
                issue=issue,
            )
            obj.updated_by = user
            obj.updated = datetime.utcnow()
        except cls.DoesNotExist:
            obj = cls()
            obj.scielo_journal = scielo_journal
            obj.creator = user

        obj.issue_pid = issue_pid or obj.issue_pid
        obj.issue_folder = issue_folder or obj.issue_folder
        obj.issue = issue or obj.issue
        obj.save()
        return obj

    @classmethod
    def items_to_publish(cls, website_kind, collection=None):
        params = {}
        if collection:
            params["collection"] = collection
        if website_kind == collection_choices.QA:
            # seleciona journals para publicar em QA
            return cls.objects.filter(
                publication_stage__isnull=True,
                **params,
            ).iterator()

        # seleciona journals para publicar em produção
        return cls.objects.filter(
            publication_stage=collection_choices.WS_APPROVED,
            **params,
        ).iterator()

    def update_publication_stage(self):
        if self.publication_stage == collection_choices.WS_APPROVED:
            self.publication_stage = collection_choices.WS_PUBLISHED
        elif self.publication_stage is None:
            self.publication_stage = collection_choices.WS_QA
        self.save()
