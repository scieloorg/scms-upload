from datetime import timedelta

import pytest
from django.utils import timezone

from article.models import Article
from issue.models import Issue
from team.models import Company, CompanyTeamMember, JournalCompanyContract
from upload import choices
from upload.authorization import user_can_act_on_package
from upload.models import Package
from upload.permissions import PUBLISH_PACKAGE
from upload.querysets import (
    correction_assignee_queryset,
    get_scoped_package_queryset,
    package_journal_filter,
    review_assignee_queryset,
)


@pytest.mark.parametrize(
    "source,expected_scope",
    [
        ("package", True),
        ("issue", False),
        ("article", True),
        ("issue_without_journal", True),
    ],
)
def test_permissions_and_reception_follow_the_same_journal(
    report_scope, source, expected_scope
):
    scope = report_scope
    issue = Issue.objects.create(
        creator=scope.superuser,
        journal=scope.journal_2 if source != "issue_without_journal" else None,
    )
    article = Article.objects.create(creator=scope.superuser, journal=scope.journal_1)
    package = Package.objects.create(
        creator=scope.company_user,
        journal=scope.journal_1 if source == "package" else None,
        issue=issue if source != "article" else None,
        article=article,
        status=choices.PS_SUBMITTED,
    )
    expected_journal = scope.journal_1 if expected_scope else scope.journal_2

    assert package.effective_journal == expected_journal
    assert package.can_receive_package(scope.company_user) is expected_scope
    assert (
        user_can_act_on_package(scope.analyst_user, PUBLISH_PACKAGE, package)
        is expected_scope
    )
    assert (
        Package.objects.filter(
            package_journal_filter([scope.journal_1.pk]), pk=package.pk
        ).exists()
        is expected_scope
    )
    assert (
        correction_assignee_queryset(package).filter(pk=scope.company_user.pk).exists()
        is expected_scope
    )
    assert (
        review_assignee_queryset(package).filter(pk=scope.analyst_user.pk).exists()
        is expected_scope
    )


def test_company_scope_keeps_colleague_and_journal_in_the_same_company(
    report_scope, django_user_model
):
    scope = report_scope
    colleague_a = django_user_model.objects.create_user(username="company-a-colleague")
    colleague_b = django_user_model.objects.create_user(username="company-b-colleague")
    second_company = Company.objects.create(
        creator=scope.superuser, name="Second company"
    )
    for company, member in (
        (scope.company, colleague_a),
        (second_company, scope.company_user),
        (second_company, colleague_b),
    ):
        CompanyTeamMember.objects.create(
            company=company, user=member, is_active_member=True, creator=scope.superuser
        )
    JournalCompanyContract.objects.create(
        company=second_company,
        journal=scope.journal_2,
        is_active=True,
        creator=scope.superuser,
    )
    packages = [
        Package.objects.create(creator=creator, journal=journal)
        for creator, journal in (
            (colleague_a, scope.journal_1),
            (colleague_b, scope.journal_2),
            (colleague_a, scope.journal_2),
            (colleague_b, scope.journal_1),
        )
    ]

    visible = get_scoped_package_queryset(scope.company_user).filter(
        pk__in=[p.pk for p in packages]
    )

    assert set(visible.values_list("pk", flat=True)) == {packages[0].pk, packages[1].pk}


@pytest.mark.parametrize(
    "restriction",
    ["inactive_member", "inactive_user", "inactive_contract", "expired", "future"],
)
def test_company_scope_requires_active_colleagues_and_current_contracts(
    report_scope, django_user_model, restriction
):
    scope = report_scope
    colleague = django_user_model.objects.create_user(username="company-colleague")
    member = CompanyTeamMember.objects.create(
        company=scope.company,
        user=colleague,
        is_active_member=True,
        creator=scope.superuser,
    )
    contract = JournalCompanyContract.objects.get(
        company=scope.company, journal=scope.journal_1
    )
    package = Package.objects.create(creator=colleague, journal=scope.journal_1)

    assert (
        get_scoped_package_queryset(scope.company_user).filter(pk=package.pk).exists()
    )

    if restriction == "inactive_member":
        member.is_active_member = False
        member.save(update_fields=["is_active_member"])
    elif restriction == "inactive_user":
        colleague.is_active = False
        colleague.save(update_fields=["is_active"])
    else:
        if restriction == "inactive_contract":
            contract.is_active = False
        elif restriction == "expired":
            contract.end_date = timezone.localdate() - timedelta(days=1)
        else:
            contract.start_date = timezone.localdate() + timedelta(days=1)
        contract.save()

    assert (
        not get_scoped_package_queryset(scope.company_user)
        .filter(pk=package.pk)
        .exists()
    )


@pytest.mark.parametrize("source", ["issue", "article", "issue_without_journal"])
def test_company_scope_resolves_missing_package_journal(
    report_scope, django_user_model, source
):
    scope = report_scope
    colleague = django_user_model.objects.create_user(username="company-colleague")
    CompanyTeamMember.objects.create(
        company=scope.company,
        user=colleague,
        is_active_member=True,
        creator=scope.superuser,
    )
    issue = Issue.objects.create(
        creator=scope.superuser,
        journal=scope.journal_1 if source == "issue" else None,
    )
    article = Article.objects.create(
        creator=scope.superuser,
        journal=scope.journal_2 if source == "issue" else scope.journal_1,
    )
    package = Package.objects.create(
        creator=colleague,
        issue=issue if source != "article" else None,
        article=article,
    )

    assert (
        get_scoped_package_queryset(scope.company_user).filter(pk=package.pk).exists()
    )
