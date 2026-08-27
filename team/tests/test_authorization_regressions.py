import json
from datetime import timedelta

import pytest
from django.contrib.auth.models import Permission
from django.utils import timezone

from collection.models import Collection
from core.users.permission_policies import SuperuserOnlyModelPermissionPolicy
from journal.models import Journal, OfficialJournal
from team.models import (
    CollectionTeamMember,
    Company,
    JournalCompanyContract,
    TeamRole,
    active_contract_queryset,
)
from team.wagtail_hooks import CollectionTeamMemberViewSet

pytestmark = pytest.mark.django_db


def test_collection_team_form_rejects_collection_outside_manager_scope(
    django_user_model,
):
    user = django_user_model.objects.create_user(username="manager")
    managed = Collection.objects.create(acron="own", name="Owned", creator=user)
    outside = Collection.objects.create(acron="other", name="Other", creator=user)
    CollectionTeamMember.objects.create(
        user=user,
        collection=managed,
        role=TeamRole.MANAGER,
        creator=user,
    )

    form = CollectionTeamMemberViewSet().get_form_class()(
        data={
            "user": json.dumps({"pk": user.pk}),
            "collection": json.dumps({"pk": outside.pk}),
            "role": TeamRole.MEMBER,
            "is_active_member": True,
        },
        for_user=user,
    )

    assert not form.is_valid()
    assert "collection" in form.errors


def test_active_contract_queryset_honors_status_and_date_boundaries(
    django_user_model,
):
    user = django_user_model.objects.create_user(username="contracts")
    official_journal = OfficialJournal.objects.create(
        title="Journal",
        issn_electronic="1234-5678",
        creator=user,
    )
    journal = Journal.objects.create(
        official_journal=official_journal,
        journal_acron="journal",
        creator=user,
    )
    today = timezone.localdate()

    contracts = []
    for index, values in enumerate(
        (
            {"is_active": True},
            {"is_active": True, "start_date": today, "end_date": today},
            {"is_active": False},
            {"is_active": True, "start_date": today + timedelta(days=1)},
            {"is_active": True, "end_date": today - timedelta(days=1)},
        )
    ):
        company = Company.objects.create(name=f"Company {index}", creator=user)
        contracts.append(
            JournalCompanyContract.objects.create(
                journal=journal,
                company=company,
                creator=user,
                **values,
            )
        )

    active_ids = set(active_contract_queryset(today=today).values_list("pk", flat=True))

    assert active_ids == {contracts[0].pk, contracts[1].pk}


def test_superuser_only_policy_ignores_direct_model_permission(django_user_model):
    user = django_user_model.objects.create_user(username="direct-permission")
    superuser = django_user_model.objects.create_superuser(
        username="superuser",
        email="superuser@example.com",
        password="password",
    )
    permission = Permission.objects.get(
        content_type__app_label="collection",
        codename="view_collection",
    )
    user.user_permissions.add(permission)
    policy = SuperuserOnlyModelPermissionPolicy(Collection)

    assert not policy.user_has_permission(user, "view")
    assert policy.user_has_permission(superuser, "view")
