from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import CommonControlField, IssuePublicationDate
from journal.models import OfficialJournal

from wagtailautocomplete.edit_handlers import AutocompletePanel
from wagtail.admin.edit_handlers import FieldPanel

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

    official_journal = models.ForeignKey(OfficialJournal, on_delete=models.CASCADE)
    volume = models.CharField(_("Volume"), max_length=255, null=True, blank=True)
    number = models.CharField(_("Number"), max_length=255, null=True, blank=True)
    supplement = models.CharField(
        _("Supplement"), max_length=255, null=True, blank=True
    )

    autocomplete_search_field = "official_journal__title"

    def autocomplete_label(self):
        return self.__str__()

    panels = [
        AutocompletePanel("official_journal"),
        FieldPanel("publication_date_text"),
        FieldPanel("publication_year"),
        FieldPanel("publication_initial_month_number"),
        FieldPanel("publication_initial_month_name"),
        FieldPanel("publication_final_month_number"),
        FieldPanel("publication_final_month_name"),
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
