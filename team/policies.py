from django.db.models import Q

from .constants import TeamGroups
from .models import (
    CollectionTeamMember,
    CompanyTeamMember,
    JournalTeamMember,
    TeamRole,
    active_contract_queryset,
)


class CollectionTeamMemberPolicy:
    @staticmethod
    def scope_queryset(user, queryset):
        if user and user.is_superuser:
            return queryset
        if not user or not user.is_authenticated:
            return queryset.none()

        group_names = set(user.groups.values_list("name", flat=True))
        scope = Q()
        if TeamGroups.COLLECTION_ADMIN in group_names:
            managed_collection_ids = CollectionTeamMember.objects.filter(
                user=user,
                role=TeamRole.MANAGER,
                is_active_member=True,
                collection__isnull=False,
            ).values_list("collection", flat=True)
            scope |= Q(collection__in=managed_collection_ids)

        if TeamGroups.COLLECTION_MEMBER in group_names:
            scope |= Q(
                user=user,
                is_active_member=True,
                collection__isnull=False,
            )

        return queryset.filter(scope).distinct() if scope else queryset.none()


class CompanyPolicy:
    @staticmethod
    def scope_queryset(user, queryset):
        if user and user.is_superuser:
            return queryset
        if not user or not user.is_authenticated:
            return queryset.none()

        group_names = set(user.groups.values_list("name", flat=True))
        if TeamGroups.COLLECTION_ADMIN in group_names and (
            CollectionTeamMember.objects.filter(
                user=user,
                role=TeamRole.MANAGER,
                is_active_member=True,
                collection__isnull=False,
            ).exists()
        ):
            return queryset

        if group_names.intersection(
            (TeamGroups.COMPANY_ADMIN, TeamGroups.COMPANY_MEMBER)
        ):
            company_ids = CompanyTeamMember.objects.filter(
                user=user,
                is_active_member=True,
            ).values_list("company", flat=True)
            return queryset.filter(pk__in=company_ids).distinct()

        return queryset.none()


class JournalTeamMemberPolicy:
    @staticmethod
    def scope_queryset(user, queryset):
        if user and user.is_superuser:
            return queryset
        if not user or not user.is_authenticated:
            return queryset.none()

        group_names = set(user.groups.values_list("name", flat=True))
        scope = Q()
        if TeamGroups.JOURNAL_ADMIN in group_names:
            managed_journal_ids = JournalTeamMember.objects.filter(
                user=user,
                role=TeamRole.MANAGER,
                is_active_member=True,
            ).values_list("journal", flat=True)
            scope |= Q(journal__in=managed_journal_ids)

        if TeamGroups.JOURNAL_MEMBER in group_names:
            scope |= Q(user=user, is_active_member=True)

        return queryset.filter(scope).distinct() if scope else queryset.none()


class CompanyTeamMemberPolicy:
    @staticmethod
    def scope_queryset(user, queryset):
        if user and user.is_superuser:
            return queryset
        if not user or not user.is_authenticated:
            return queryset.none()

        group_names = set(user.groups.values_list("name", flat=True))
        scope = Q()
        if TeamGroups.COMPANY_ADMIN in group_names:
            managed_company_ids = CompanyTeamMember.objects.filter(
                user=user,
                role=TeamRole.MANAGER,
                is_active_member=True,
            ).values_list("company", flat=True)
            scope |= Q(company__in=managed_company_ids)

        if TeamGroups.COMPANY_MEMBER in group_names:
            scope |= Q(user=user, is_active_member=True)

        return queryset.filter(scope).distinct() if scope else queryset.none()


class JournalCompanyContractPolicy:
    @staticmethod
    def scope_queryset(user, queryset):
        if user and user.is_superuser:
            return queryset
        if not user or not user.is_authenticated:
            return queryset.none()

        group_names = set(user.groups.values_list("name", flat=True))
        unrestricted_scope = Q()
        active_scope = Q()

        if TeamGroups.JOURNAL_ADMIN in group_names:
            managed_journal_ids = JournalTeamMember.objects.filter(
                user=user,
                role=TeamRole.MANAGER,
                is_active_member=True,
            ).values_list("journal", flat=True)
            unrestricted_scope |= Q(journal__in=managed_journal_ids)

        if TeamGroups.JOURNAL_MEMBER in group_names:
            journal_ids = JournalTeamMember.objects.filter(
                user=user,
                is_active_member=True,
            ).values_list("journal", flat=True)
            active_scope |= Q(journal__in=journal_ids)

        if group_names.intersection(
            (TeamGroups.COMPANY_ADMIN, TeamGroups.COMPANY_MEMBER)
        ):
            company_ids = CompanyTeamMember.objects.filter(
                user=user,
                is_active_member=True,
            ).values_list("company", flat=True)
            active_scope |= Q(company__in=company_ids)

        unrestricted = (
            queryset.filter(unrestricted_scope)
            if unrestricted_scope
            else queryset.none()
        )
        active = (
            active_contract_queryset(queryset.filter(active_scope))
            if active_scope
            else queryset.none()
        )
        return (unrestricted | active).distinct()
