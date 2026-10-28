from io import StringIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from collection.models import Collection
from journal.models import Journal, JournalCollection, OfficialJournal
from team.management.commands.create_user_groups import Command
from team.models import CollectionTeamMember, TeamRole
from upload import choices
from upload.delegation import DELEGATION_EVENT, can_delegate_review, delegate_review
from upload.models import Package, UploadProcResult, ValidationReport
from upload.wagtail_hooks import (
    QualityAnalysisPackageViewSet,
    ReadyToPublishPackageViewSet,
)


@pytest.fixture
def quality_review_context(django_user_model):
    Command().handle(stdout=StringIO(), sync_users=False)

    admin = django_user_model.objects.create_superuser(
        username="admin", email="admin@example.com", password="password"
    )
    ana = django_user_model.objects.create_user(username="ana")
    bruno = django_user_model.objects.create_user(username="bruno")

    collection = Collection.objects.create(
        acron="scl", name="SciELO Brazil", creator=admin
    )
    memberships = {}
    for user in (ana, bruno):
        memberships[user.pk] = CollectionTeamMember.objects.create(
            user=user,
            collection=collection,
            role=TeamRole.MEMBER,
            is_active_member=True,
            creator=admin,
        )

    official = OfficialJournal.objects.create(title="Journal", creator=admin)
    journal = Journal.objects.create(
        official_journal=official, journal_acron="test", creator=admin
    )
    JournalCollection.objects.create(
        journal=journal, collection=collection, creator=admin
    )

    package = Package.objects.create(
        journal=journal,
        name="package",
        status=choices.PS_PREVIEW,
        creator=admin,
        analyst=memberships[ana.pk],
        assignee=ana,
        file=SimpleUploadedFile("package.zip", b"PK\x05\x06" + b"\x00" * 18),
    )

    return {
        "ana": ana,
        "bruno": bruno,
        "bruno_membership": memberships[bruno.pk],
        "package": package,
    }


pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "status",
    [
        choices.PS_PREVIEW,
        choices.PS_PENDING_QA_DECISION,
        choices.PS_VALIDATED_WITH_ERRORS,
    ],
)
def test_assignment_preserves_workflow_and_history(quality_review_context, status):
    ctx = quality_review_context
    package = ctx["package"]

    package.status = status
    package.qa_decision = choices.PS_PENDING_CORRECTION
    package.qa_comment = "Existing correction instructions"
    package.qa_ws_status = package.public_ws_status = choices.PUBLISHED
    package.save()

    preserved = (
        "status",
        "qa_decision",
        "qa_comment",
        "analyst_id",
        "article_id",
        "qa_ws_status",
        "public_ws_status",
        "qa_ws_pubdate",
        "public_ws_pubdate",
    )
    before = [getattr(package, field) for field in preserved]
    original = UploadProcResult.objects.create(
        proc=package,
        name="process_qa_decision",
        creator=ctx["ana"],
        detail={"original": True},
    )

    assert can_delegate_review(ctx["ana"], package)

    delegate_review(ctx["ana"], package.pk, ctx["bruno"].pk, "Check references")
    package.refresh_from_db()

    assert [getattr(package, field) for field in preserved] == before
    assert package.assignee == ctx["bruno"]

    event = package.upload_proc_result.get(name=DELEGATION_EVENT)
    assert event.creator == ctx["ana"] and event.completed
    assert event.detail["previous_assignee_id"] == ctx["ana"].pk
    assert event.detail["assignee_id"] == ctx["bruno"].pk
    assert event.detail["comment"] == "Check references"

    original.refresh_from_db()

    assert original.detail == {"original": True}
    assert package.upload_proc_result.count() == 2


def test_assignment_rolls_back_with_event_failure(quality_review_context, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("Event storage unavailable")

    ctx = quality_review_context
    package = ctx["package"]
    monkeypatch.setattr(UploadProcResult, "finish", fail)

    with pytest.raises(RuntimeError):
        delegate_review(ctx["ana"], package.pk, ctx["bruno"].pk, "")

    package.refresh_from_db()

    assert package.assignee == ctx["ana"] and not package.upload_proc_result.exists()


def test_url_identity_assignment_and_history(client, quality_review_context):
    ctx = quality_review_context
    package = ctx["package"]
    client.force_login(ctx["ana"])
    url = reverse("upload:delegate_review", args=[package.pk])

    response = client.get(url)

    assert response.status_code == 200
    document_url = reverse("wagtailsnippets_upload_package:inspect", args=[package.pk])
    identity = response.context["document_identity"]
    assert identity["title"] == identity["identifier"] == package.name
    assert identity["journal"] == str(package.journal)
    assert f'href="{document_url}"'.encode() in response.content

    response = client.post(url, {"reviewer": package.creator_id})

    assert response.status_code == 200 and "reviewer" in response.context["form"].errors
    assert not package.upload_proc_result.exists()

    other = Package.objects.create(
        name="other", creator=package.creator, assignee=ctx["ana"]
    )

    response = client.post(
        url,
        {
            "package_id": other.pk,
            "reviewer": ctx["bruno"].pk,
            "instructions": "Check references",
        },
    )

    assert response.status_code == 302 and response.url == document_url

    history = client.get(response.url, {"tab": "history"})

    assert history.status_code == 200 and b"Check references" in history.content

    package.refresh_from_db()
    other.refresh_from_db()

    assert package.assignee == ctx["bruno"]
    assert other.assignee == ctx["ana"] and not other.upload_proc_result.exists()
    assert package.upload_proc_result.filter(name=DELEGATION_EVENT).count() == 1


@pytest.mark.parametrize("restriction", ["revoked", "validation_pending"])
def test_post_revalidates_availability_after_opening_form(
    client, quality_review_context, restriction
):
    ctx = quality_review_context
    package = ctx["package"]
    client.force_login(ctx["ana"])
    url = reverse("upload:delegate_review", args=[package.pk])

    assert client.get(url).status_code == 200
    if restriction == "revoked":
        CollectionTeamMember.objects.filter(user=ctx["ana"]).update(
            is_active_member=False
        )
    else:
        ValidationReport.objects.create(
            package=package,
            creator=ctx["ana"],
            creation=choices.REPORT_CREATION_WIP,
        )

    response = client.post(url, {"reviewer": ctx["bruno"].pk}, follow=True)
    package.refresh_from_db()

    assert response.status_code == (404 if restriction == "revoked" else 200)
    if restriction == "validation_pending":
        assert response.redirect_chain[-1] == (reverse("wagtailadmin_home"), 302)

    assert client.get(url, follow=True).status_code == response.status_code
    assert package.assignee == ctx["ana"] and not package.upload_proc_result.exists()


@pytest.mark.parametrize(
    "viewset_class",
    [QualityAnalysisPackageViewSet, ReadyToPublishPackageViewSet],
)
@pytest.mark.django_db
def test_explicit_action_delegates_quality_review(
    quality_review_context,
    viewset_class,
):
    package = quality_review_context["package"]
    bruno = quality_review_context["bruno"]
    bruno_membership = quality_review_context["bruno_membership"]
    form_class = viewset_class().get_form_class()
    form = form_class(
        data={
            "reviewer": bruno.pk,
            "qa_decision": choices.PS_PENDING_QA_DECISION,
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
            "reviewer": quality_review_context["bruno"].pk,
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
