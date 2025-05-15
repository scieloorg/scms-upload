import logging
import random
from string import ascii_lowercase, digits

from django.conf import settings
from django.db import IntegrityError, models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from modelcluster.fields import ParentalKey
from modelcluster.models import ClusterableModel
from wagtail.admin.panels import FieldPanel, InlinePanel
from wagtail.models import Orderable
from wagtailautocomplete.edit_handlers import AutocompletePanel

from core.models import CommonControlField, IssuePublicationDate
from core.utils.requester import fetch_data
from issue.forms import IssueForm, TOCForm
from journal.models import Journal, JournalSection


def _get_digits(value):
    d = "".join([c for c in value if c.isdigit()])
    try:
        return int(d)
    except ValueError:
        return 0


class IssueGetOrCreateError(Exception): ...


class Issue(CommonControlField, IssuePublicationDate):
    """
    Class that represent Issue
    """

    journal = models.ForeignKey(
        Journal, on_delete=models.SET_NULL, null=True, blank=True
    )
    volume = models.CharField(_("Volume"), max_length=16, null=True, blank=True)
    number = models.CharField(_("Number"), max_length=16, null=True, blank=True)
    supplement = models.CharField(_("Supplement"), max_length=16, null=True, blank=True)
    publication_year = models.CharField(_("Year"), max_length=4, null=True, blank=True)
    total_documents = models.PositiveSmallIntegerField(null=True, blank=True)
    is_continuous_publishing_model = models.BooleanField(null=True, blank=True)
    order = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text=_(
            "This number controls the order issues appear for a specific year on the website grid"
        ),
    )
    issue_pid_suffix = models.CharField(max_length=4, null=True, blank=True)

    def __unicode__(self):
        return "%s %s" % (
            self.journal,
            self.issue_folder,
        )

    def __str__(self):
        return "%s %s" % (
            self.journal,
            self.issue_folder,
        )

    @property
    def issue_folder(self):
        labels = [(self.volume, "v"), (self.number, "n"), (self.supplement, "s")]
        return "".join([f"{prefix}{value}" for value, prefix in labels if value])

    @property
    def data(self):
        return dict(
            journal=self.journal.data,
            volume=self.volume,
            number=self.number,
            supplement=self.supplement,
            publication_year=self.publication_year,
            created=self.created.isoformat(),
            updated=self.updated.isoformat(),
        )

    @staticmethod
    def autocomplete_custom_queryset_filter(search_term):
        return Issue.objects.filter(
            Q(journal__title__icontains=search_term)
            | Q(publication_year__icontains=search_term)
            | Q(volume__icontains=search_term)
            | Q(number__icontains=search_term)
        )

    def autocomplete_label(self):
        return "%s %s" % (
            self.journal,
            self.issue_folder,
        )

    panels = [
        AutocompletePanel("journal"),
        FieldPanel("publication_year"),
        FieldPanel("volume"),
        FieldPanel("number"),
        FieldPanel("supplement"),
        FieldPanel("is_continuous_publishing_model"),
        FieldPanel("total_documents"),
        FieldPanel("order"),
        FieldPanel("issue_pid_suffix", read_only=True),
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
        try:
            return cls.objects.get(
                journal=journal,
                volume=volume,
                supplement=supplement,
                number=number,
            )
        except cls.MultipleObjectsReturned:
            return cls.objects.filter(
                journal=journal,
                volume=volume,
                supplement=supplement,
                number=number,
            ).first()

    @classmethod
    def create(
        cls,
        user,
        journal,
        volume,
        supplement,
        number,
        publication_year,
        is_continuous_publishing_model=None,
        total_documents=None,
        order=None,
        issue_pid_suffix=None,
    ):
        try:
            obj = cls()
            obj.journal = journal
            obj.volume = volume
            obj.supplement = supplement
            obj.number = number
            obj.publication_year = publication_year
            obj.order = order or obj.generate_order()
            obj.issue_pid_suffix = issue_pid_suffix or str(obj.generate_order()).zfill(
                4
            )
            obj.is_continuous_publishing_model = is_continuous_publishing_model
            obj.total_documents = total_documents
            obj.creator = user
            obj.save()
            return obj
        except IntegrityError:
            return cls.get(journal, volume, supplement, number)
        except Exception as e:
            data = dict(
                journal=journal,
                volume=volume,
                supplement=supplement,
                number=number,
                publication_year=publication_year,
                user=user,
            )
            raise IssueGetOrCreateError(f"Unable to get or create issue {e} {data}")

    @classmethod
    def get_or_create(
        cls,
        journal,
        volume,
        supplement,
        number,
        publication_year,
        user,
        is_continuous_publishing_model=None,
        total_documents=None,
        order=None,
        issue_pid_suffix=None,
    ):
        try:
            obj = cls.get(
                journal=journal,
                volume=volume,
                supplement=supplement,
                number=number,
            )
            obj.is_continuous_publishing_model = (
                is_continuous_publishing_model or obj.is_continuous_publishing_model
            )
            obj.total_documents = total_documents or obj.total_documents
            obj.publication_year = publication_year or obj.publication_year
            obj.order = order or obj.order or obj.generate_order()
            obj.issue_pid_suffix = issue_pid_suffix or obj.issue_pid_suffix
            if not obj.issue_pid_suffix and obj.order:
                obj.issue_pid_suffix = str(obj.order).zfill(4)
            obj.updated_by = user
            obj.save()
            return obj
        except cls.DoesNotExist:
            return cls.create(
                user,
                journal,
                volume,
                supplement,
                number,
                publication_year,
                is_continuous_publishing_model,
                total_documents,
                order,
                issue_pid_suffix,
            )

    def generate_order(self, suppl_start=1000, spe_start=2000):
        x = 0
        if self.supplement is not None:
            x = suppl_start
            try:
                suppl = int(self.supplement)
            except (ValueError, TypeError):
                suppl = _get_digits(self.supplement)
            return x + suppl

        number = self.number
        if not number:
            return 1

        spe = None
        if "spe" in number:
            x = spe_start
            parts = number.split("spe")
            spe = int(parts[-1] or 0)
            return x + spe
        elif number == "ahead":
            return 9999

        try:
            number = int(number)
        except (ValueError, TypeError):
            number = _get_digits(number)
        return number or 1


class TOC(CommonControlField, ClusterableModel):
    # Somente para issues cujos artigos não tem página numérica
    issue = models.ForeignKey(Issue, blank=True, null=True, on_delete=models.SET_NULL)
    ordered = models.BooleanField(default=False)

    panels = [
        InlinePanel("issue_sections", label=_("Sections")),
    ]

    base_form_class = TOCForm

    def __str__(self):
        return f"{self.issue}"

    @classmethod
    def create(cls, user, issue, ordered):
        try:
            obj = cls(creator=user, issue=issue, ordered=ordered)
            obj.save()
            return obj
        except IntegrityError as e:
            return cls.get(issue)

    @classmethod
    def create_or_update(cls, user, issue, ordered):
        try:
            obj = cls.get(issue)
            obj.ordered = ordered
            obj.save()
            return obj
        except cls.DoesNotExist:
            return cls.create(user, issue, ordered)

    @classmethod
    def get(cls, issue):
        return cls.objects.get(issue=issue)

    @property
    def ordered_sections(self):
        sections = {}
        for item in TocSection.objects.filter(toc=self).order_by("position"):
            key = (item.position, item.group)
            sections.setdefault(key, {})
            sections[key].update({item.section.language.code2: item.section.text})
        return sections


class TocSection(CommonControlField, Orderable):
    toc = ParentalKey(TOC, on_delete=models.CASCADE, related_name="issue_sections")
    group = models.CharField(max_length=16, null=True, blank=True)
    section = models.ForeignKey(
        JournalSection, null=True, blank=True, on_delete=models.CASCADE
    )
    position = models.PositiveSmallIntegerField(_("Position"), blank=True, null=True)

    panels = [
        FieldPanel("position"),
        FieldPanel("group"),
        AutocompletePanel("section"),
    ]

    class Meta:
        ordering = ["position", "group", "section__text"]
        unique_together = [("toc", "group", "section")]

    @classmethod
    def create(cls, user, toc, group, section):
        try:
            obj = cls(creator=user, toc=toc, group=group, section=section)
            obj.position = cls.objects.filter(toc=toc, group=group).count() + 1
            obj.save()
            return obj
        except IntegrityError as e:
            return cls.get(toc, group, section)

    @classmethod
    def create_or_update(cls, user, toc, group, section):
        try:
            return cls.get(toc, group, section)
        except cls.DoesNotExist:
            return cls.create(user, toc, group, section)

    @classmethod
    def get(cls, toc, group, section):
        return cls.objects.get(toc=toc, group=group, section=section)

    @staticmethod
    def get_section_position(issue, article_sections):
        codes = []
        sections = []
        for item in article_sections.all():
            if item.code:
                codes.append(item.code)
            sections.append(item.text)

        params = {}
        if sections:
            params["section__text__in"] = sections
        if codes:
            params["group"] = codes[0]
        try:
            if params:
                return (
                    TocSection.objects.filter(toc__issue=issue, **params)
                    .first()
                    .position
                    or 0
                )
        except AttributeError:
            return 0

    @staticmethod
    def multilingual_sections(issue, sections):
        items = {}

        issue_toc = TocSection.objects.filter(toc__issue=issue)

        codes = [item.code for item in sections.all() if item.code]
        if codes:
            for item in issue_toc.filter(group=codes[0]):
                items[item.section.language.code2] = item.section.text
            return items

        titles = [item.text for item in sections.all()]
        groups = set()
        if titles:
            for item in issue_toc.filter(section__text__in=titles):
                items[item.section.language.code2] = item.section.text
                if item.group:
                    groups.add(item.group)

            if groups:
                for item in issue_toc.filter(group__in=list(groups)):
                    items[item.section.language.code2] = item.section.text

            if not items:
                for item in JournalSection.objects.filter(
                    parent=issue.journal, text__in=titles
                ):
                    items[item.language.code2] = item.text

        return items

    @staticmethod
    def create_group(issue):
        prefix = issue.journal.first_letters
        while True:
            suffix = "".join(random.choices(ascii_lowercase, k=3))
            group = prefix + "-" + suffix
            if not TocSection.objects.filter(toc__issue=issue, group=group).exists():
                return group
