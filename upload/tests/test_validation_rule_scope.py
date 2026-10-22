from io import StringIO
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.test import RequestFactory
from django.urls import reverse

from collection.models import Collection
from journal.models import Journal, JournalCollection, OfficialJournal
from team.management.commands.create_user_groups import Command
from team.models import (
    CollectionTeamMember,
    Company,
    CompanyTeamMember,
    JournalCompanyContract,
    TeamRole,
)
from upload import choices
from upload.models import Package, UploadValidator
from upload.tasks import task_validate_xml_content
from upload.wagtail_hooks import UploadValidatorViewSet

pytestmark = pytest.mark.django_db


@pytest.fixture
def rule_context(django_user_model):
    Command().handle(stdout=StringIO(), sync_users=False)
    user = django_user_model.objects.create_user(username="coordinator", is_staff=True)
    collection = Collection.objects.create(acron="own", name="Owned", creator=user)
    outside = Collection.objects.create(acron="other", name="Other", creator=user)
    CollectionTeamMember.objects.create(
        user=user,
        collection=collection,
        role=TeamRole.MANAGER,
        creator=user,
    )
    official = OfficialJournal.objects.create(title="Journal", creator=user)
    journal = Journal.objects.create(official_journal=official, creator=user)
    JournalCollection.objects.create(
        journal=journal, collection=collection, creator=user
    )
    return user, collection, outside, journal


def rule_data(collection):
    return {
        "collection": collection.pk,
        "max_xml_warnings_percentage": 5,
        "max_xml_errors_percentage": 5,
        "max_impossible_to_fix_percentage": 5,
        "decision_for_critical_errors": choices.PS_VALIDATED_WITH_ERRORS,
        "publication_rule": choices.FLEXIBLE_AUTO_PUBLICATION,
        "validation_params": "{}",
    }


def test_coordinator_rule_is_saved_listed_and_cannot_target_other_collection(
    client, rule_context
):
    user, collection, outside, journal = rule_context
    client.force_login(user)
    add_url = reverse("wagtailsnippets_upload_uploadvalidator:add")
    form = client.get(add_url).context["form"]
    assert form.initial["collection"] == collection.pk
    assert list(form.fields["collection"].queryset) == [collection]

    response = client.post(add_url, rule_data(collection))
    assert response.status_code == 302
    rule = UploadValidator.objects.get(collection=collection)
    assert rule.creator == user
    assert rule.max_xml_errors_percentage == 5
    response = client.get(reverse("wagtailsnippets_upload_uploadvalidator:list"))
    assert list(response.context["object_list"]) == [rule]
    assert (
        client.get(
            reverse("wagtailsnippets_upload_uploadvalidator:edit", args=[rule.pk])
        ).status_code
        == 200
    )

    for data in (
        rule_data(collection),
        rule_data(outside),
        dict(rule_data(collection), collection=""),
    ):
        response = client.post(add_url, data)
        assert response.status_code == 200
        assert "collection" in response.context["form"].errors
    outside_rule = UploadValidator.objects.create(collection=outside, creator=user)
    CollectionTeamMember.objects.create(
        user=user,
        collection=outside,
        role=TeamRole.MEMBER,
        creator=user,
    )
    assert (
        client.get(
            reverse(
                "wagtailsnippets_upload_uploadvalidator:edit", args=[outside_rule.pk]
            ),
            follow=True,
        ).status_code
        == 404
    )
    assert UploadValidator.objects.count() == 2


def test_processing_uses_the_journal_collection_rule_and_ignores_global_rows(
    rule_context,
):
    user, collection, outside, journal = rule_context
    UploadValidator.objects.create(
        creator=user, publication_rule=choices.STRICT_AUTO_PUBLICATION
    )
    UploadValidator.objects.create(
        creator=user, publication_rule=choices.MANUAL_PUBLICATION
    )
    UploadValidator.objects.create(
        collection=outside, creator=user, publication_rule=choices.MANUAL_PUBLICATION
    )
    rule = UploadValidator.objects.create(
        collection=collection,
        creator=user,
        publication_rule=choices.FLEXIBLE_AUTO_PUBLICATION,
        validation_params={"test_parameter": "configured"},
    )
    package = Package.objects.create(journal=journal, creator=user)
    assert package.upload_validator == rule
    assert package.is_ready_to_publish
    with patch("upload.tasks.XMLDataChecker") as checker:
        task_validate_xml_content.run(
            "unused.zip", "unused.xml", package.pk, journal.pk, None, None
        )
    assert checker.call_args.args[-1] == rule.validation_params

    rule.publication_rule = choices.MANUAL_PUBLICATION
    rule.save()
    assert not package.is_ready_to_publish


def test_missing_rule_uses_manual_policy_without_creating_global_configuration(
    rule_context,
):
    user, collection, outside, journal = rule_context
    package = Package.objects.create(journal=journal, creator=user)
    rule = package.upload_validator
    assert rule.collection == collection
    assert rule.pk is None
    assert rule.publication_rule == choices.MANUAL_PUBLICATION
    assert not package.is_ready_to_publish
    assert UploadValidator.objects.count() == 0

    JournalCollection.objects.create(journal=journal, collection=outside, creator=user)
    with pytest.raises(ValidationError):
        package.upload_validator


def test_rules_menu_and_direct_access_require_collection_management(
    client, rule_context, django_user_model
):
    coordinator, collection, outside, journal = rule_context
    depositor = django_user_model.objects.create_user(
        username="depositor", is_staff=True
    )
    company = Company.objects.create(name="Company", creator=coordinator)
    CompanyTeamMember.objects.create(
        user=depositor, company=company, creator=coordinator
    )
    JournalCompanyContract.objects.create(
        company=company, journal=journal, is_active=True, creator=coordinator
    )
    viewset = UploadValidatorViewSet()
    request = RequestFactory().get("/")
    for user, shown in ((coordinator, True), (depositor, False)):
        request.user = user
        assert viewset.get_menu_item().is_shown(request) is shown
    client.force_login(depositor)
    response = client.get(
        reverse("wagtailsnippets_upload_uploadvalidator:list"), follow=True
    )
    assert response.redirect_chain[-1] == (reverse("wagtailadmin_home"), 302)
    assert response.template_name == ["wagtailadmin/home.html"]
