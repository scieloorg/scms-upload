import logging

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from modelcluster.models import ClusterableModel
from wagtail.admin.panels import FieldPanel

from core.models import CommonControlField
from location.models import Location

User = get_user_model()
logger = logging.getLogger(__name__)


class Company(CommonControlField, ClusterableModel):
    """
    Company that provides editorial services (e.g., XML production).
    """

    name = models.CharField(
        _("Company Name"), max_length=255, unique=True
    )
    acronym = models.CharField(
        _("Acronym"), max_length=50, null=True, blank=True
    )
    location = models.ForeignKey(
        Location,
        verbose_name=_("Location"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    description = models.TextField(
        _("Description"), null=True, blank=True
    )

    panels = [
        FieldPanel("name"),
        FieldPanel("acronym"),
        FieldPanel("location"),
        FieldPanel("description"),
    ]

    class Meta:
        verbose_name = _("Company")
        verbose_name_plural = _("Companies")
        indexes = [
            models.Index(fields=["name"]),
            models.Index(fields=["acronym"]),
        ]

    def __str__(self):
        return self.name

    autocomplete_search_field = "name"

    def autocomplete_label(self):
        labels = [self.name]
        if self.acronym:
            labels.append(self.acronym)
        return " | ".join(labels)

    @property
    def managers(self):
        """Return all managers of this company."""
        return CompanyMember.objects.filter(
            company=self, role=CompanyMember.MANAGER
        ).select_related("user")

    @property
    def members(self):
        """Return all members (including managers) of this company."""
        return CompanyMember.objects.filter(company=self).select_related("user")

    def has_manager(self, user):
        """Check if user is a manager of this company."""
        return CompanyMember.objects.filter(
            company=self, user=user, role=CompanyMember.MANAGER
        ).exists()

    def has_member(self, user):
        """Check if user is a member (any role) of this company."""
        return CompanyMember.objects.filter(company=self, user=user).exists()


class CompanyMember(CommonControlField):
    """
    Membership relationship between a User and a Company with a role.
    """

    MANAGER = "manager"
    MEMBER = "member"

    ROLE_CHOICES = [
        (MANAGER, _("Manager")),
        (MEMBER, _("Member")),
    ]

    company = models.ForeignKey(
        Company,
        verbose_name=_("Company"),
        on_delete=models.CASCADE,
        related_name="company_members",
    )
    user = models.ForeignKey(
        User,
        verbose_name=_("User"),
        on_delete=models.CASCADE,
        related_name="company_memberships",
    )
    role = models.CharField(
        _("Role"),
        max_length=20,
        choices=ROLE_CHOICES,
        default=MEMBER,
    )
    is_active_member = models.BooleanField(
        _("Active Member"), default=True
    )

    panels = [
        FieldPanel("company"),
        FieldPanel("user"),
        FieldPanel("role"),
        FieldPanel("is_active_member"),
    ]

    class Meta:
        verbose_name = _("Company Member")
        verbose_name_plural = _("Company Members")
        unique_together = [("user", "company")]
        indexes = [
            models.Index(fields=["role"]),
            models.Index(fields=["is_active_member"]),
        ]

    def __str__(self):
        return f"{self.user} ({self.get_role_display()}) - {self.company}"

    autocomplete_search_field = "user__username"

    def autocomplete_label(self):
        return f"{self.user} - {self.company} ({self.get_role_display()})"

    def clean(self):
        """Validate that we don't remove the last manager."""
        super().clean()
        
        # Check if this is the last manager being removed or demoted
        if self.pk:  # Only for existing records
            try:
                old_instance = CompanyMember.objects.get(pk=self.pk)
                
                # If changing from manager to member or deactivating a manager
                if (
                    old_instance.role == self.MANAGER
                    and (self.role != self.MANAGER or not self.is_active_member)
                ):
                    # Count active managers
                    active_managers = CompanyMember.objects.filter(
                        company=self.company,
                        role=self.MANAGER,
                        is_active_member=True,
                    ).exclude(pk=self.pk).count()
                    
                    if active_managers == 0:
                        raise ValidationError(
                            _("Cannot remove or demote the last manager of the company.")
                        )
            except CompanyMember.DoesNotExist:
                pass

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Prevent deletion of the last manager."""
        if self.role == self.MANAGER and self.is_active_member:
            active_managers = CompanyMember.objects.filter(
                company=self.company,
                role=self.MANAGER,
                is_active_member=True,
            ).exclude(pk=self.pk).count()
            
            if active_managers == 0:
                raise ValidationError(
                    _("Cannot delete the last manager of the company.")
                )
        
        super().delete(*args, **kwargs)

    @staticmethod
    def autocomplete_custom_queryset_filter(text):
        return CompanyMember.objects.filter(
            Q(user__username__icontains=text)
            | Q(user__email__icontains=text)
            | Q(user__name__icontains=text)
            | Q(company__name__icontains=text)
        )
