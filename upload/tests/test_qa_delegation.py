import json

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from collection.models import Collection
from team.models import CollectionTeamMember, TeamRole
from upload import choices
from upload.models import Package
from upload.wagtail_hooks import (
    QualityAnalysisPackageViewSet,
    ReadyToPublishPackageViewSet,
)


@pytest.fixture
def quality_review_context(django_user_model):
    admin = django_user_model.objects.create_superuser(
        username="admin",
        email="admin@example.com",
        password="password",
    )
    ana = django_user_model.objects.create_user(username="ana")
    bruno = django_user_model.objects.create_user(username="bruno")
    collection = Collection.objects.create(
        acron="scl",
        name="SciELO Brazil",
        creator=admin,
    )
    ana_membership = CollectionTeamMember.objects.create(
        user=ana,
        collection=collection,
        role=TeamRole.MEMBER,
        is_active_member=True,
        creator=admin,
    )
    bruno_membership = CollectionTeamMember.objects.create(
        user=bruno,
        collection=collection,
        role=TeamRole.MEMBER,
        is_active_member=True,
        creator=admin,
    )
    package = Package.objects.create(
        name="package",
        status=choices.PS_PREVIEW,
        creator=admin,
        analyst=ana_membership,
        assignee=ana,
        file=SimpleUploadedFile("package.zip", b"PK\x05\x06" + b"\x00" * 18),
    )

    return {
        "ana": ana,
        "bruno": bruno,
        "bruno_membership": bruno_membership,
        "package": package,
    }


@pytest.mark.parametrize(
    "viewset_class",
    [QualityAnalysisPackageViewSet, ReadyToPublishPackageViewSet],
)
@pytest.mark.django_db
def test_selecting_only_another_analyst_delegates_quality_review(
    quality_review_context,
    viewset_class,
):
    package = quality_review_context["package"]
    bruno = quality_review_context["bruno"]
    bruno_membership = quality_review_context["bruno_membership"]
    form_class = viewset_class().get_form_class()
    form = form_class(
        data={
            "analyst": json.dumps({"pk": bruno_membership.pk}),
            "qa_decision": "",
            "qa_comment": "",
            "order": package.order,
            "linked": [],
            "article": "",
            "upload_proc_result-TOTAL_FORMS": "0",
            "upload_proc_result-INITIAL_FORMS": "0",
            "upload_proc_result-MIN_NUM_FORMS": "0",
            "upload_proc_result-MAX_NUM_FORMS": "1000",
        },
        instance=package,
        for_user=quality_review_context["ana"],
    )

    assert form.is_valid(), form.errors.as_json()
    assert form.cleaned_data["qa_decision"] == choices.PS_PENDING_QA_DECISION

    saved_package = form.save_all(quality_review_context["ana"])
    saved_package.refresh_from_db()

    assert saved_package.qa_decision == choices.PS_PENDING_QA_DECISION
    assert saved_package.analyst == bruno_membership
    assert saved_package.assignee == bruno

    assert saved_package.process_qa_decision(quality_review_context["ana"])
    saved_package.refresh_from_db()

    assert saved_package.status == choices.PS_PENDING_QA_DECISION


@pytest.mark.django_db
def test_publication_form_rejects_empty_decision_without_analyst_change(
    quality_review_context,
):
    package = quality_review_context["package"]
    form_class = ReadyToPublishPackageViewSet().get_form_class()
    form = form_class(
        data={
            "analyst": json.dumps({"pk": package.analyst_id}),
            "qa_decision": "",
            "qa_comment": "",
            "order": package.order,
            "linked": [],
            "article": "",
            "upload_proc_result-TOTAL_FORMS": "0",
            "upload_proc_result-INITIAL_FORMS": "0",
            "upload_proc_result-MIN_NUM_FORMS": "0",
            "upload_proc_result-MAX_NUM_FORMS": "1000",
        },
        instance=package,
        for_user=quality_review_context["ana"],
    )

    assert not form.is_valid()
    assert "qa_decision" in form.errors
