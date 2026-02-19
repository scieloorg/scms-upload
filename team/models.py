import logging

from django.contrib.auth import get_user_model
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from wagtail.admin.panels import FieldPanel
from wagtailautocomplete.edit_handlers import AutocompletePanel

from collection.models import Collection
from core.models import CommonControlField, VisualIdentityMixin
from team.forms import CollectionTeamMemberModelForm

User = get_user_model()


ALLOWED_COLLECTIONS = ["dom", "spa", "scl", "pan"]


class TeamRole(models.TextChoices):
    """Role types for team members."""
    MANAGER = "manager", _("Manager")
    MEMBER = "member", _("Member")


def has_permission(user=None):
    try:
        if not user:
            logging.info("has_permission: collection")
            return Collection.objects.filter(acron__in=ALLOWED_COLLECTIONS).exists()
        logging.info("has_permission: user")
        return CollectionTeamMember.has_upload_permission(user)
    except Exception:
        return False


class TeamMember(CommonControlField):
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    is_active_member = models.BooleanField(null=True, blank=True, default=True)

    panels = [
        FieldPanel("user"),
        FieldPanel("is_active_member"),
    ]

    @staticmethod
    def autocomplete_custom_queryset_filter(text):
        return TeamMember.objects.filter(
            Q(user__username__icontains=text)
            | Q(user__email__icontains=text)
            | Q(user__name__icontains=text)
        )

    def autocomplete_label(self):
        return str(self.user)

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

    base_form_class = CollectionTeamMemberModelForm
    panels = [
        AutocompletePanel("collection"),
        AutocompletePanel("user"),
        FieldPanel("is_active_member"),
    ]

    class Meta:
        verbose_name = _("Team member")
        verbose_name_plural = _("Team members")
        unique_together = ("user", "collection")

    @staticmethod
    def autocomplete_custom_queryset_filter(text):
        return CollectionTeamMember.objects.filter(
            Q(user__username__icontains=text)
            | Q(user__email__icontains=text)
            | Q(user__name__icontains=text)
        )

    def autocomplete_label(self):
        return str(self.user)

    def __str__(self):
        return f"{self.user} ({self.collection})"

    @staticmethod
    def collections(user, is_active_member=None):
        try:
            if is_active_member:
                for member in CollectionTeamMember.objects.filter(
                    user=user, is_active_member=is_active_member
                ):
                    yield member.collection
            else:
                for member in CollectionTeamMember.objects.filter(user=user):
                    yield member.collection
        except Exception:
            return Collection.objects.all()

    @staticmethod
    def members(user, is_active_member=None):
        for collection in CollectionTeamMember.collections(user, is_active_member):
            return CollectionTeamMember.objects.filter(collection=collection)

    @classmethod
    def has_upload_permission(cls, user):
        return cls.objects.filter(user=user, collection__acron__in=ALLOWED_COLLECTIONS).exists()


class Company(VisualIdentityMixin, CommonControlField):
    """
    Company represents an editorial services provider that can be contracted
    by journals to produce XML files.
    """
    name = models.CharField(_("Company Name"), max_length=255, unique=True)
    description = models.TextField(_("Description"), blank=True, null=True)
    personal_contact = models.CharField(_("Personal Contact"), max_length=30, blank=True, null=True)
    contact_email = models.EmailField(_("Contact Email"), blank=True, null=True)
    contact_phone = models.CharField(_("Contact Phone"), max_length=50, blank=True, null=True)
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

    @classmethod
    def get_managers(cls, company_id):
        """Get all managers for this company."""
        return CompanyTeamMember.objects.filter(
            company_id=company_id,
            role=TeamRole.MANAGER,
            is_active_member=True
        )

    @classmethod
    def get_members(cls, company_id):
        """Get all active members (including managers) for this company."""
        return CompanyTeamMember.objects.filter(
            company_id=company_id,
            is_active_member=True
        )


class JournalTeamMember(TeamMember):
    """
    Editorial team members associated with a specific journal.
    Can be either managers or regular members.
    """
    journal = models.ForeignKey(
        "journal.Journal",
        on_delete=models.CASCADE,
        related_name="team_members",
        verbose_name=_("Journal")
    )
    role = models.CharField(
        _("Role"),
        max_length=20,
        choices=TeamRole.choices,
        default=TeamRole.MEMBER
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

    def is_manager(self):
        """Check if this member is a manager."""
        return self.role == TeamRole.MANAGER

    @classmethod
    def user_is_manager(cls, user, journal):
        """Check if a user is a manager for a specific journal."""
        return cls.objects.filter(
            user=user,
            journal=journal,
            role=TeamRole.MANAGER,
            is_active_member=True
        ).exists()

    @classmethod
    def get_user_journals(cls, user, role=None, is_active=True):
        """Get all journals a user is associated with."""
        filters = {"user": user}
        if role:
            filters["role"] = role
        if is_active is not None:
            filters["is_active_member"] = is_active
        return cls.objects.filter(**filters).select_related("journal")


class CompanyTeamMember(TeamMember):
    """
    Company team members (XML providers) associated with an editorial services company.
    Can be either managers or regular members.
    """
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="team_members",
        verbose_name=_("Company")
    )
    role = models.CharField(
        _("Role"),
        max_length=20,
        choices=TeamRole.choices,
        default=TeamRole.MEMBER
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

    def is_manager(self):
        """Check if this member is a manager."""
        return self.role == TeamRole.MANAGER

    @classmethod
    def user_is_manager(cls, user, company):
        """Check if a user is a manager for a specific company."""
        return cls.objects.filter(
            user=user,
            company=company,
            role=TeamRole.MANAGER,
            is_active_member=True
        ).exists()

    @classmethod
    def get_user_companies(cls, user, role=None, is_active=True):
        """Get all companies a user is associated with."""
        filters = {"user": user}
        if role:
            filters["role"] = role
        if is_active is not None:
            filters["is_active_member"] = is_active
        return cls.objects.filter(**filters).select_related("company")


class JournalCompanyContract(CommonControlField):
    """
    Represents a contract between a journal and a company for XML production services.
    Journal managers can manage these contracts.
    """
    journal = models.ForeignKey(
        "journal.Journal",
        on_delete=models.CASCADE,
        related_name="company_contracts",
        verbose_name=_("Journal")
    )
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="journal_contracts",
        verbose_name=_("Company")
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

    @classmethod
    def get_journal_companies(cls, journal, is_active=True):
        """Get all companies contracted by a journal."""
        filters = {"journal": journal}
        if is_active is not None:
            filters["is_active"] = is_active
        return cls.objects.filter(**filters).select_related("company")

    @classmethod
    def get_company_journals(cls, company, is_active=True):
        """Get all journals that contracted a company."""
        filters = {"company": company}
        if is_active is not None:
            filters["is_active"] = is_active
        return cls.objects.filter(**filters).select_related("journal")

    @classmethod
    def can_manage_contract(cls, user, journal):
        """Check if a user can manage contracts for a journal (must be a journal manager)."""
        return JournalTeamMember.user_is_manager(user, journal)
