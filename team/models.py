from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from wagtail.admin.panels import FieldPanel
from wagtailautocomplete.edit_handlers import AutocompletePanel

from collection.models import Collection
from core.models import CommonControlField, VisualIdentityMixin
from journal.models import JournalCollection

User = get_user_model()


class TeamRole(models.TextChoices):
    MANAGER = "manager", _("Manager")
    MEMBER = "member", _("Member")


def active_contract_queryset(queryset=None, today=None):
    if queryset is None:
        queryset = JournalCompanyContract.objects.all()
    today = today or timezone.localdate()
    return queryset.filter(is_active=True).filter(
        Q(start_date__isnull=True) | Q(start_date__lte=today),
        Q(end_date__isnull=True) | Q(end_date__gte=today),
    )


def get_user_membership_ids(user):
    result = {
        "collection_list_ids": set(),
        "journal_list_ids": set(),
        "company_list_ids": set(),
    }

    if not user or not getattr(user, "is_authenticated", False):
        return {key: [] for key in result}

    collection_ids = set(
        CollectionTeamMember.objects.filter(
            user=user,
            is_active_member=True,
            collection__isnull=False,
        ).values_list("collection", flat=True)
    )

    if collection_ids:
        result["collection_list_ids"] = collection_ids
        result["journal_list_ids"].update(
            JournalCollection.objects.filter(collection__in=collection_ids).values_list(
                "journal", flat=True
            )
        )

    journal_ids = set(
        JournalTeamMember.objects.filter(
            user=user,
            is_active_member=True,
        ).values_list("journal", flat=True)
    )

    if journal_ids:
        result["journal_list_ids"].update(journal_ids)

    company_ids = set(
        CompanyTeamMember.objects.filter(
            user=user,
            is_active_member=True,
        ).values_list("company", flat=True)
    )

    if company_ids:
        result["company_list_ids"] = company_ids
        contracts = active_contract_queryset(
            JournalCompanyContract.objects.filter(company__in=company_ids)
        )
        result["journal_list_ids"].update(contracts.values_list("journal", flat=True))

    return {k: list(v) for k, v in result.items()}


class TeamMember(CommonControlField):
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    is_active_member = models.BooleanField(default=True)

    panels = [
        FieldPanel("user"),
        FieldPanel("is_active_member"),
    ]

    class Meta:
        abstract = True
        verbose_name = _("Team")
        verbose_name_plural = _("Teams")
        indexes = [
            models.Index(
                fields=[
                    "is_active_member",
                ]
            ),
        ]


class CollectionTeamMember(TeamMember):
    collection = models.ForeignKey(
        Collection, null=True, blank=True, on_delete=models.SET_NULL
    )
    role = models.CharField(
        _("Role"), max_length=20, choices=TeamRole.choices, default=TeamRole.MEMBER
    )

    panels = [
        AutocompletePanel("collection"),
        AutocompletePanel("user"),
        FieldPanel("role"),
        FieldPanel("is_active_member"),
    ]

    class Meta:
        verbose_name = _("Team member")
        verbose_name_plural = _("Team members")
        unique_together = ("user", "collection")
        indexes = [
            models.Index(fields=["collection", "role"]),
            models.Index(fields=["user", "is_active_member"]),
        ]

    @staticmethod
    def autocomplete_custom_queryset_filter(text):
        return CollectionTeamMember.objects.filter(
            Q(user__username__icontains=text)
            | Q(user__email__icontains=text)
            | Q(user__name__icontains=text)
        )

    def autocomplete_label(self):
        return f"{self.user} - {self.collection} ({self.get_role_display()})"

    def __str__(self):
        return f"{self.user} - {self.collection} ({self.get_role_display()})"


class Company(VisualIdentityMixin, CommonControlField):
    name = models.CharField(_("Company Name"), max_length=255, unique=True)
    description = models.TextField(_("Description"), blank=True, null=True)
    personal_contact = models.CharField(
        _("Personal Contact"), max_length=30, blank=True, null=True
    )
    contact_email = models.EmailField(_("Contact Email"), blank=True, null=True)
    contact_phone = models.CharField(
        _("Contact Phone"), max_length=50, blank=True, null=True
    )
    certified_since = models.DateField(_("Certified Since"), blank=True, null=True)
    is_active = models.BooleanField(_("Active"), default=True)

    class Meta:
        verbose_name = _("Company")
        verbose_name_plural = _("Companies")
        indexes = [
            models.Index(fields=["name"]),
            models.Index(fields=["is_active"]),
        ]

    panels = [
        FieldPanel("name"),
        FieldPanel("description"),
        FieldPanel("url"),
        FieldPanel("logo"),
        FieldPanel("personal_contact"),
        FieldPanel("contact_email"),
        FieldPanel("contact_phone"),
        FieldPanel("certified_since"),
        FieldPanel("is_active"),
    ]

    def __str__(self):
        return self.name

    autocomplete_search_field = "name"

    def autocomplete_label(self):
        return self.name


class JournalTeamMember(TeamMember):
    journal = models.ForeignKey(
        "journal.Journal",
        on_delete=models.CASCADE,
        related_name="team_members",
        verbose_name=_("Journal"),
    )
    role = models.CharField(
        _("Role"), max_length=20, choices=TeamRole.choices, default=TeamRole.MEMBER
    )

    class Meta:
        verbose_name = _("Journal Team Member")
        verbose_name_plural = _("Journal Team Members")
        unique_together = ("user", "journal")
        indexes = [
            models.Index(fields=["journal", "role"]),
            models.Index(fields=["user", "is_active_member"]),
        ]

    panels = [
        AutocompletePanel("journal"),
        AutocompletePanel("user"),
        FieldPanel("role"),
        FieldPanel("is_active_member"),
    ]

    def __str__(self):
        return f"{self.user} - {self.journal} ({self.get_role_display()})"

    @staticmethod
    def autocomplete_custom_queryset_filter(text):
        return JournalTeamMember.objects.filter(
            Q(user__username__icontains=text)
            | Q(user__email__icontains=text)
            | Q(user__name__icontains=text)
            | Q(journal__title__icontains=text)
        )

    def autocomplete_label(self):
        return f"{self.user} - {self.journal} ({self.get_role_display()})"


class CompanyTeamMember(TeamMember):
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="team_members",
        verbose_name=_("Company"),
    )
    role = models.CharField(
        _("Role"), max_length=20, choices=TeamRole.choices, default=TeamRole.MEMBER
    )

    class Meta:
        verbose_name = _("Company Team Member")
        verbose_name_plural = _("Company Team Members")
        unique_together = ("user", "company")
        indexes = [
            models.Index(fields=["company", "role"]),
            models.Index(fields=["user", "is_active_member"]),
        ]

    panels = [
        AutocompletePanel("company"),
        AutocompletePanel("user"),
        FieldPanel("role"),
        FieldPanel("is_active_member"),
    ]

    def __str__(self):
        return f"{self.user} - {self.company} ({self.get_role_display()})"

    @staticmethod
    def autocomplete_custom_queryset_filter(text):
        return CompanyTeamMember.objects.filter(
            Q(user__username__icontains=text)
            | Q(user__email__icontains=text)
            | Q(user__name__icontains=text)
            | Q(company__name__icontains=text)
        )

    def autocomplete_label(self):
        return f"{self.user} - {self.company} ({self.get_role_display()})"


class JournalCompanyContract(CommonControlField):
    journal = models.ForeignKey(
        "journal.Journal",
        on_delete=models.CASCADE,
        related_name="company_contracts",
        verbose_name=_("Journal"),
    )
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="journal_contracts",
        verbose_name=_("Company"),
    )
    is_active = models.BooleanField(_("Active"), default=True)
    start_date = models.DateField(_("Start Date"), null=True, blank=True)
    end_date = models.DateField(_("End Date"), null=True, blank=True)
    notes = models.TextField(_("Notes"), blank=True, null=True)

    class Meta:
        verbose_name = _("Journal-Company Contract")
        verbose_name_plural = _("Journal-Company Contracts")
        unique_together = ("journal", "company")
        indexes = [
            models.Index(fields=["journal", "is_active"]),
            models.Index(fields=["company", "is_active"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(start_date__isnull=True)
                    | Q(end_date__isnull=True)
                    | Q(start_date__lte=models.F("end_date"))
                ),
                name="team_contract_valid_date_range",
            )
        ]

    panels = [
        AutocompletePanel("journal"),
        AutocompletePanel("company"),
        FieldPanel("is_active"),
        FieldPanel("start_date"),
        FieldPanel("end_date"),
        FieldPanel("notes"),
    ]

    def __str__(self):
        status = "Active" if self.is_active else "Inactive"
        return f"{self.journal} - {self.company} ({status})"

    def clean(self):
        super().clean()
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValidationError(
                {"end_date": _("End date must be on or after start date.")}
            )
