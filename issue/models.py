from datetime import datetime

from django.db import models
from django.utils.translation import gettext_lazy as _
from wagtail.admin.edit_handlers import FieldPanel
from wagtailautocomplete.edit_handlers import AutocompletePanel

from core.models import CommonControlField, IssuePublicationDate
from journal.models import OfficialJournal, SciELOJournal

from .forms import IssueForm


class Issue(CommonControlField, IssuePublicationDate):
    """
    Class that represent Issue
    """

    def __unicode__(self):
        return "%s %s %s %s %s" % (
            self.official_journal,
            self.publication_year,
            self.volume or "",
            self.number or "",
            self.supplement or "",
        )

    def __str__(self):
        return "%s %s %s %s %s" % (
            self.official_journal,
            self.publication_year,
            self.volume or "",
            self.number or "",
            self.supplement or "",
        )

    official_journal = models.ForeignKey(
        OfficialJournal, on_delete=models.SET_NULL, null=True, blank=True
    )
    volume = models.TextField(_("Volume"), null=True, blank=True)
    number = models.TextField(_("Number"), null=True, blank=True)
    supplement = models.TextField(_("Supplement"), null=True, blank=True)
    publication_year = models.TextField(_("Year"), null=True, blank=True)

    autocomplete_search_field = "official_journal__title"

    def autocomplete_label(self):
        return self.__str__()

    panels = [
        AutocompletePanel("official_journal"),
        FieldPanel("publication_year"),
        FieldPanel("volume"),
        FieldPanel("number"),
        FieldPanel("supplement"),
    ]

    base_form_class = IssueForm

    class Meta:
        unique_together = [
            ["official_journal", "publication_year", "volume", "number", "supplement"],
            ["official_journal", "volume", "number", "supplement"],
        ]
        indexes = [
            models.Index(fields=["official_journal"]),
            models.Index(fields=["publication_year"]),
            models.Index(fields=["volume"]),
            models.Index(fields=["number"]),
            models.Index(fields=["supplement"]),
        ]

    @classmethod
    def get(cls, official_journal, volume, supplement, number):
        return cls.objects.get(
            official_journal=official_journal,
            volume=volume,
            supplement=supplement,
            number=number,
        )

    @classmethod
    def get_or_create(
        cls, official_journal, volume, supplement, number, publication_year, user
    ):
        try:
            return cls.get(
                official_journal=official_journal,
                volume=volume,
                supplement=supplement,
                number=number,
            )
        except cls.DoesNotExist:
            obj = cls()
            obj.official_journal = official_journal
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
        return "%s %s" % (self.scielo_journal, self.issue_pid)

    def __str__(self):
        return "%s %s" % (self.scielo_journal, self.issue_pid)

    scielo_journal = models.ForeignKey(
        SciELOJournal, on_delete=models.SET_NULL, null=True
    )
    official_issue = models.ForeignKey(Issue, on_delete=models.SET_NULL, null=True)
    issue_pid = models.CharField(_("Issue PID"), max_length=23, null=False, blank=False)
    # v30n1 ou 2019nahead
    issue_folder = models.CharField(
        _("Issue Folder"), max_length=23, null=False, blank=False
    )

    class Meta:
        unique_together = [
            ["scielo_journal", "issue_pid"],
            ["scielo_journal", "issue_folder"],
            ["issue_pid", "issue_folder"],
        ]
        indexes = [
            models.Index(fields=["scielo_journal"]),
            models.Index(fields=["issue_pid"]),
            models.Index(fields=["issue_folder"]),
            models.Index(fields=["official_issue"]),
        ]

    @classmethod
    def get(
        cls, scielo_journal, issue_folder=None, issue_pid=None, official_issue=None
    ):
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
        if official_issue:
            return cls.objects.get(
                official_issue=official_issue,
                scielo_journal=scielo_journal,
            )

    @classmethod
    def create_or_update(
        cls, scielo_journal, issue_pid, issue_folder, official_issue, user
    ):
        try:
            obj = cls.get(
                scielo_journal=scielo_journal,
                issue_pid=issue_pid,
                issue_folder=issue_folder,
                official_issue=official_issue,
            )
            obj.updated_by = user
            obj.updated = datetime.utcnow()
        except cls.DoesNotExist:
            obj = cls()
            obj.scielo_journal = scielo_journal
            obj.creator = user

        obj.issue_pid = issue_pid or obj.issue_pid
        obj.issue_folder = issue_folder or obj.issue_folder
        obj.official_issue = official_issue or obj.official_issue
        obj.save()
        return obj
