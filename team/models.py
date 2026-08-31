import logging

from django.contrib.auth import get_user_model
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from wagtail.admin.panels import FieldPanel
from wagtailautocomplete.edit_handlers import AutocompletePanel

from collection.models import Collection
from core.models import CommonControlField, VisualIdentityMixin
from core.forms import CoreAdminModelForm
User = get_user_model()


ALLOWED_COLLECTIONS = ["dom", "spa", "scl", "pan"]

# Django group names for team-based access control.
# COLLECTION_TEAM_ADMIN: collection managers — can CRUD Company, JournalTeamMember,
#   CompanyTeamMember, and members of their own collections.
COLLECTION_TEAM_ADMIN = "COLLECTION_TEAM_ADMIN"
# COLLECTION_TEAM_MEMBER: regular collection members — read-only access to own record.
COLLECTION_TEAM_MEMBER = "COLLECTION_TEAM_MEMBER"
# JOURNAL_TEAM_ADMIN: journal managers — can CRUD JournalTeamMember and JournalCompanyContract
#   for their managed journals.
JOURNAL_TEAM_ADMIN = "JOURNAL_TEAM_ADMIN"
# JOURNAL_TEAM_MEMBER: regular journal members — read-only access to own record.
JOURNAL_TEAM_MEMBER = "JOURNAL_TEAM_MEMBER"
# COMPANY_TEAM_ADMIN: company managers — can CRUD CompanyTeamMember for their companies.
COMPANY_TEAM_ADMIN = "COMPANY_TEAM_ADMIN"
# COMPANY_MEMBER: regular company members — read-only access to own record.
COMPANY_MEMBER = "COMPANY_MEMBER"

GROUP_NAMES = [
    COLLECTION_TEAM_ADMIN,
    COLLECTION_TEAM_MEMBER,
    JOURNAL_TEAM_ADMIN,
    JOURNAL_TEAM_MEMBER,
    COMPANY_TEAM_ADMIN,
    COMPANY_MEMBER,
]


class TeamRole(models.TextChoices):
    """Role types for team members."""
    MANAGER = "manager", _("Manager")
    MEMBER = "member", _("Member")


def get_user_membership_ids(user):
    """
    Returns a dict with the list IDs of collections, journals or companies
    that the user is actively associated with, depending on team membership type.
    Priority order: collection > journal > company.

    For collection team members, journal_list_ids is also populated with the journals
    that belong to the user's collections.
    For company team members, journal_list_ids is also populated with the journals
    that have active contracts with the user's companies.
    """
    from journal.models import JournalCollection

    result = {"collection_list_ids": [], "journal_list_ids": [], "company_list_ids": []}

    collection_ids = list(
        CollectionTeamMember.objects.filter(user=user, is_active_member=True)
        .values_list("collection", flat=True)
    )
    if collection_ids:
        result["collection_list_ids"] = collection_ids
        result["journal_list_ids"] = list(
            JournalCollection.objects.filter(
                collection__in=collection_ids
            ).values_list("journal", flat=True)
        )
        return result

    journal_ids = list(
        JournalTeamMember.objects.filter(user=user, is_active_member=True)
        .values_list("journal", flat=True)
    )
    if journal_ids:
        result["journal_list_ids"] = journal_ids
        return result

    company_ids = list(
        CompanyTeamMember.objects.filter(user=user, is_active_member=True)
        .values_list("company", flat=True)
    )
    if company_ids:
        result["company_list_ids"] = company_ids
        result["journal_list_ids"] = list(
            JournalCompanyContract.objects.filter(
                company__in=company_ids, is_active=True
            ).values_list("journal", flat=True)
        )
    return result


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

    base_form_class = CoreAdminModelForm
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
    role = models.CharField(
        _("Role"),
        max_length=20,
        choices=TeamRole.choices,
        default=TeamRole.MEMBER
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

    def is_manager(self):
        """Check if this member is a manager."""
        return self.role == TeamRole.MANAGER

    @classmethod
    def user_is_manager(cls, user, collection):
        """Check if a user is a manager for a specific collection."""
        return cls.objects.filter(
            user=user,
            collection=collection,
            role=TeamRole.MANAGER,
            is_active_member=True
        ).exists()

    @classmethod
    def get_user_collections(cls, user, role=None, is_active=True):
        """Get all collections a user is associated with."""
        filters = {"user": user}
        if role:
            filters["role"] = role
        if is_active is not None:
            filters["is_active_member"] = is_active
        return cls.objects.filter(**filters).select_related("collection")

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

    @classmethod
    def get_queryset_for_user(cls, user, qs):
        """Return the queryset of CollectionTeamMember records visible to the user.

        - Managers see all members of their own collection(s).
        - Regular members see only their own record.
        """
        managed_collection_ids = cls.objects.filter(
            user=user, role=TeamRole.MANAGER, is_active_member=True
        ).values_list("collection", flat=True)
        if managed_collection_ids:
            return qs.filter(collection__in=managed_collection_ids)
        return qs.filter(user=user)


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
    base_form_class = CoreAdminModelForm
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

    @classmethod
    def get_queryset_for_user(cls, user, qs):
        """Return the queryset of Company records visible to the user.

        - COLLECTION_TEAM_ADMIN (collection managers) can see all companies.
        - Company members see only the companies they belong to.
        """
        is_collection_manager = CollectionTeamMember.objects.filter(
            user=user, role=TeamRole.MANAGER, is_active_member=True
        ).exists()
        if is_collection_manager:
            return qs
        company_ids = CompanyTeamMember.objects.filter(
            user=user, is_active_member=True
        ).values_list("company", flat=True)
        return qs.filter(id__in=company_ids)


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

    @classmethod
    def get_queryset_for_user(cls, user, qs):
        """Return the queryset of JournalTeamMember records visible to the user.

        - COLLECTION_TEAM_ADMIN sees all journal team members.
        - JOURNAL_TEAM_ADMIN sees members of their managed journals.
        - Regular members see only their own record.
        """
        is_collection_manager = CollectionTeamMember.objects.filter(
            user=user, role=TeamRole.MANAGER, is_active_member=True
        ).exists()
        if is_collection_manager:
            return qs
        managed_journal_ids = cls.objects.filter(
            user=user, role=TeamRole.MANAGER, is_active_member=True
        ).values_list("journal", flat=True)
        if managed_journal_ids:
            return qs.filter(journal__in=managed_journal_ids)
        return qs.filter(user=user)


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

    @classmethod
    def get_queryset_for_user(cls, user, qs):
        """Return the queryset of CompanyTeamMember records visible to the user.

        - COLLECTION_TEAM_ADMIN sees all company team members.
        - COMPANY_TEAM_ADMIN sees members of their managed companies.
        - Regular members see only their own record.
        """
        is_collection_manager = CollectionTeamMember.objects.filter(
            user=user, role=TeamRole.MANAGER, is_active_member=True
        ).exists()
        if is_collection_manager:
            return qs
        managed_company_ids = cls.objects.filter(
            user=user, role=TeamRole.MANAGER, is_active_member=True
        ).values_list("company", flat=True)
        if managed_company_ids:
            return qs.filter(company__in=managed_company_ids)
        return qs.filter(user=user)


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
    base_form_class = CoreAdminModelForm
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

    @classmethod
    def get_queryset_for_user(cls, user, qs):
        """Return the queryset of JournalCompanyContract records visible to the user.

        - COLLECTION_TEAM_ADMIN sees all contracts.
        - JOURNAL_TEAM_ADMIN sees contracts for their managed journals.
        - All others see no contracts.
        """
        is_collection_manager = CollectionTeamMember.objects.filter(
            user=user, role=TeamRole.MANAGER, is_active_member=True
        ).exists()
        if is_collection_manager:
            return qs
        managed_journal_ids = JournalTeamMember.objects.filter(
            user=user, role=TeamRole.MANAGER, is_active_member=True
        ).values_list("journal", flat=True)
        if managed_journal_ids:
            return qs.filter(journal__in=managed_journal_ids)
        return qs.none()
