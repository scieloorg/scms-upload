import json
from datetime import date
from io import StringIO

import pytest
from django.contrib.auth.models import AnonymousUser, Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction

from article import choices
from article.authorization import (
    allowed_article_change_types,
    can_request_article_change,
    is_public_article,
)
from article.models import Article, ArticleWebPage, RequestArticleChange
from article.wagtail_hooks import RequestArticleChangeSnippetViewSet
from collection.models import Collection
from journal.models import Journal, JournalCollection, OfficialJournal
from package.choices import PKG_ORIGIN_MIGRATION, PKG_ORIGIN_UPLOAD
from package.models import SPSPkg
from team.management.commands.create_user_groups import Command
from team.models import (
    CollectionTeamMember,
    Company,
    CompanyTeamMember,
    JournalCompanyContract,
    JournalTeamMember,
    TeamRole,
)
from upload.models import Package, PackageZip

pytestmark = pytest.mark.django_db


@pytest.fixture
def context(django_user_model):
    Command().handle(stdout=StringIO(), sync_users=False)
    admin = django_user_model.objects.create_superuser(
        username="admin", email="admin@example.com", password="password"
    )
    user = django_user_model.objects.create_user(username="member")
    collection = Collection.objects.create(acron="own", name="Owned", creator=admin)
    other_collection = Collection.objects.create(
        acron="other", name="Other", creator=admin
    )
    articles = []
    for index, current_collection in enumerate((collection, other_collection)):
        official = OfficialJournal.objects.create(
            title=f"Journal {index}", creator=admin
        )
        journal = Journal.objects.create(
            official_journal=official, journal_acron=f"j{index}", creator=admin
        )
        JournalCollection.objects.create(
            journal=journal, collection=current_collection, creator=admin
        )
        articles.append(
            Article.objects.create(
                journal=journal,
                creator=admin,
                first_pubdate_iso="2000-01-01",
                status=choices.AS_PUBLISHED,
            )
        )
        Package.objects.create(
            article=articles[-1], creator=admin, public_ws_status="published"
        )
    return admin, user, collection, articles[0], articles[1]


@pytest.mark.parametrize("scope", ("collection", "journal"))
@pytest.mark.parametrize("role", (TeamRole.MANAGER, TeamRole.MEMBER))
def test_active_editorial_roles_are_scoped_and_update_remains_collection_only(
    context, scope, role
):
    admin, user, collection, article, outside = context
    if scope == "collection":
        membership = CollectionTeamMember.objects.create(
            user=user, collection=collection, role=role, creator=admin
        )
    else:
        membership = JournalTeamMember.objects.create(
            user=user, journal=article.journal, role=role, creator=admin
        )
    expected = tuple(
        value
        for value, label in choices.REQUEST_CHANGE_TYPE
        if scope == "collection" or value != choices.RCT_UPDATE
    )
    assert allowed_article_change_types(user, article) == expected
    assert not can_request_article_change(user, outside)
    if scope == "journal":
        assert not user.has_perm("article.add_requestarticlechange")
        assert not user.has_perm("article.change_article")
    membership.is_active_member = False
    membership.save()
    assert not can_request_article_change(user, article)


def test_company_contract_does_not_authorize_changes(context):
    admin, user, collection, article, outside = context
    company = Company.objects.create(name="Company", creator=admin)
    CompanyTeamMember.objects.create(user=user, company=company, creator=admin)
    JournalCompanyContract.objects.create(
        journal=article.journal, company=company, creator=admin
    )
    # Even directly granted permissions do not turn company scope into editorial scope.
    user.user_permissions.add(
        *Permission.objects.filter(
            content_type__app_label="article",
            codename__in=("request_article_change", "add_requestarticlechange"),
        )
    )
    assert not can_request_article_change(user, article)


def test_collection_role_elsewhere_does_not_grant_update_to_journal_role(context):
    admin, user, collection, article, outside = context
    CollectionTeamMember.objects.create(user=user, collection=collection, creator=admin)
    JournalTeamMember.objects.create(user=user, journal=outside.journal, creator=admin)
    assert can_request_article_change(user, outside, choices.RCT_ERRATUM)
    assert not can_request_article_change(user, outside, choices.RCT_UPDATE)


def test_inactive_anonymous_and_missing_article_are_denied(context):
    admin, user, collection, article, outside = context
    assert not can_request_article_change(AnonymousUser(), article)
    assert not can_request_article_change(admin, None)
    admin.is_active = False
    assert not can_request_article_change(admin, article)


@pytest.mark.parametrize("change_type", ("", "unknown", None))
def test_request_requires_valid_type(context, change_type):
    admin, user, collection, article, outside = context
    with pytest.raises(ValidationError):
        RequestArticleChange.request(admin, article, change_type, "Reason")


@pytest.mark.parametrize("comment", (None, "", " \n\t"))
def test_request_requires_justification(context, comment):
    admin, user, collection, article, outside = context
    with pytest.raises(ValidationError):
        RequestArticleChange.request(admin, article, choices.RCT_UPDATE, comment)


def test_article_required_in_domain_but_legacy_database_field_remains_nullable(context):
    admin, user, collection, article, outside = context
    assert RequestArticleChange._meta.get_field("article").null
    with pytest.raises(ValidationError):
        RequestArticleChange.request(admin, None, choices.RCT_UPDATE, "Reason")
    with pytest.raises(ValidationError):
        RequestArticleChange(
            creator=admin, change_type=choices.RCT_UPDATE, comment="Reason"
        ).clean()


def test_request_default_duplicate_guard_and_original_state(context):
    admin, user, collection, article, outside = context
    previous = Package.objects.create(
        article=article, creator=admin, public_ws_status="published", name="previous"
    )
    original_package = Package.objects.filter(pk=previous.pk).values().get()
    request = RequestArticleChange.request(admin, article, choices.RCT_UPDATE, "Reason")
    assert request.status == choices.RCS_PENDING
    assert request.was_public
    with pytest.raises(ValidationError):
        RequestArticleChange.request(admin, article, choices.RCT_ERRATUM, "Reason")
    request.status = choices.RCS_RECEIVED
    request.save()
    with pytest.raises(ValidationError):
        RequestArticleChange.request(admin, article, choices.RCT_UPDATE, "Reason")
    article.refresh_from_db()
    assert article.status == choices.AS_PUBLISHED
    assert Package.objects.filter(pk=previous.pk).values().get() == original_package


@pytest.mark.parametrize("status", (choices.RCS_PENDING, choices.RCS_RECEIVED))
def test_database_constraint_blocks_active_duplicate_but_excludes_legacy_nulls(
    context, status
):
    admin, user, collection, article, outside = context
    RequestArticleChange.request(admin, article, choices.RCT_UPDATE, "Reason")
    with pytest.raises(IntegrityError), transaction.atomic():
        RequestArticleChange.objects.create(
            creator=admin,
            article=article,
            change_type=choices.RCT_UPDATE,
            comment="Duplicate",
            status=status,
        )
    for index in range(2):
        RequestArticleChange.objects.create(
            creator=admin,
            article=None,
            change_type=choices.RCT_UPDATE,
            comment="Legacy",
            status=status,
        )


def test_unauthorized_request_fails_without_creating_history(context):
    admin, user, collection, article, outside = context
    with pytest.raises(PermissionDenied):
        RequestArticleChange.request(user, article, choices.RCT_UPDATE, "Reason")
    assert not RequestArticleChange.objects.exists()


def test_qa_only_past_xml_date_is_not_public_but_public_and_qa_is(context):
    admin, user, collection, article, outside = context
    assert article.is_public
    article.package_set.update(public_ws_status="")
    package = Package.objects.create(
        article=article, creator=admin, qa_ws_status="published"
    )
    assert not is_public_article(article)
    assert not can_request_article_change(admin, article)
    package.public_ws_status = "published"
    package.save()
    assert is_public_article(article)
    assert can_request_article_change(admin, article)


@pytest.mark.parametrize(
    "purpose,status,url,expected",
    (
        (
            choices.ARTICLE_WEBPAGE_PURPOSE_PUBLIC,
            choices.ARTICLE_WEBPAGE_STATUS_AVAILABLE,
            "",
            True,
        ),
        (
            choices.ARTICLE_WEBPAGE_PURPOSE_PUBLIC,
            choices.ARTICLE_WEBPAGE_STATUS_VALID_CONTENT,
            "",
            True,
        ),
        (
            choices.ARTICLE_WEBPAGE_PURPOSE_PUBLIC,
            choices.ARTICLE_WEBPAGE_STATUS_CONTENT_MISMATCH,
            "",
            True,
        ),
        (
            choices.ARTICLE_WEBPAGE_PURPOSE_CLASSIC,
            choices.ARTICLE_WEBPAGE_STATUS_NOT_CHECKED,
            "https://classic.example/a",
            False,
        ),
        (
            choices.ARTICLE_WEBPAGE_PURPOSE_CLASSIC,
            choices.ARTICLE_WEBPAGE_STATUS_AVAILABLE,
            "https://classic.example/a",
            True,
        ),
    ),
)
def test_public_page_requires_verified_evidence(
    context, purpose, status, url, expected
):
    admin, user, collection, article, outside = context
    article.package_set.update(public_ws_status="", qa_ws_status="published")
    ArticleWebPage.objects.create(
        article=article, creator=admin, purpose=purpose, status=status, url=url
    )
    assert is_public_article(article) is expected
    assert can_request_article_change(admin, article) is expected


@pytest.mark.parametrize("origin", (None, PKG_ORIGIN_UPLOAD))
def test_new_article_with_past_date_and_placeholder_urls_is_not_public(context, origin):
    admin, user, collection, article, outside = context
    article.package_set.update(public_ws_status="", qa_ws_status="published")
    article.sps_pkg = SPSPkg.objects.create(creator=admin, origin=origin)
    article.save()
    for purpose in (
        choices.ARTICLE_WEBPAGE_PURPOSE_QA,
        choices.ARTICLE_WEBPAGE_PURPOSE_CLASSIC,
    ):
        ArticleWebPage.objects.create(
            article=article,
            creator=admin,
            purpose=purpose,
            status=choices.ARTICLE_WEBPAGE_STATUS_NOT_CHECKED,
            url="https://placeholder.example/a",
        )
    assert article.is_public  # The past XML date alone is not publication evidence.
    assert not RequestArticleChange.objects.filter(article=article).exists()
    assert not is_public_article(article)
    with pytest.raises(PermissionDenied):
        RequestArticleChange.request(admin, article, choices.RCT_UPDATE, "Reason")
    assert not RequestArticleChange.objects.filter(article=article).exists()


def test_migrated_public_article_remains_public_during_qa_and_after_safe_request(
    context,
):
    admin, user, collection, article, outside = context
    article.package_set.update(public_ws_status="", qa_ws_status="published")
    article.sps_pkg = SPSPkg.objects.create(creator=admin, origin=PKG_ORIGIN_MIGRATION)
    article.first_pubdate_iso = None
    article.first_publication_date = date(2000, 1, 1)
    article.save()
    original = Article.objects.filter(pk=article.pk).values().get()
    assert is_public_article(article)
    assert Article.objects.filter(pk=article.pk).values().get() == original
    request = RequestArticleChange.request(admin, article, choices.RCT_UPDATE, "Reason")
    assert request.was_public
    assert Article.objects.filter(pk=article.pk).values().get() == original

    # QA can replace the migrated package without erasing the eligibility snapshot.
    article.sps_pkg = SPSPkg.objects.create(creator=admin, origin=PKG_ORIGIN_UPLOAD)
    article.first_pubdate_iso = None
    article.save()
    ArticleWebPage.objects.create(
        article=article,
        creator=admin,
        purpose=choices.ARTICLE_WEBPAGE_PURPOSE_CLASSIC,
        status=choices.ARTICLE_WEBPAGE_STATUS_NOT_CHECKED,
        url="https://placeholder.example/replacement",
    )
    article.refresh_from_db()
    request.refresh_from_db()
    assert request.was_public
    assert is_public_article(article)
    assert can_request_article_change(admin, article)


def test_public_snapshot_fields_are_not_editable_and_default_is_not_evidence(context):
    admin, user, collection, article, outside = context
    article.package_set.update(public_ws_status="", qa_ws_status="published")
    request = RequestArticleChange.objects.create(
        creator=admin,
        article=article,
        change_type=choices.RCT_UPDATE,
        comment="Legacy request without a publication snapshot",
    )
    assert not request.was_public
    assert not RequestArticleChange._meta.get_field("was_public").editable
    assert not RequestArticleChange._meta.get_field("original_xml").editable
    assert not is_public_article(article)


def test_legacy_form_creates_safely_and_cannot_rewrite_history(context):
    admin, user, collection, article, outside = context
    form_class = RequestArticleChangeSnippetViewSet().get_form_class()
    data = {
        "article": json.dumps({"pk": article.pk}),
        "change_type": choices.RCT_UPDATE,
        "comment": "Original reason",
    }
    form = form_class(data=data, for_user=admin)
    assert form.is_valid(), form.errors
    request = form.save_all(admin)
    original = RequestArticleChange.objects.filter(pk=request.pk).values().get()
    article.refresh_from_db()
    assert article.status == choices.AS_PUBLISHED
    duplicate = form_class(data=data, for_user=admin)
    if duplicate.is_valid():
        with pytest.raises(ValidationError):
            duplicate.save_all(admin)
    edit = form_class(
        data={
            "article": json.dumps({"pk": outside.pk}),
            "change_type": choices.RCT_RETRACTION,
            "comment": "Rewritten reason",
        },
        instance=request,
        for_user=admin,
    )
    assert all(
        edit.fields[name].disabled for name in ("article", "change_type", "comment")
    )
    assert edit.is_valid(), edit.errors
    edit.save_all(admin)
    assert RequestArticleChange.objects.filter(pk=request.pk).values().get() == original


def test_legacy_form_save_cannot_bypass_authorization(context):
    admin, user, collection, article, outside = context
    JournalTeamMember.objects.create(user=user, journal=article.journal, creator=admin)
    form = RequestArticleChangeSnippetViewSet().get_form_class()(
        data={
            "article": json.dumps({"pk": article.pk}),
            "change_type": choices.RCT_UPDATE,
            "comment": "Reason",
        },
        for_user=user,
    )
    assert form.is_valid(), form.errors
    with pytest.raises(PermissionDenied):
        form.save_all(user)
    assert not RequestArticleChange.objects.exists()


def test_cancel_authorization_and_state(context):
    admin, user, collection, article, outside = context
    request = RequestArticleChange.request(admin, article, choices.RCT_UPDATE, "Reason")
    with pytest.raises(PermissionDenied):
        request.cancel(user)
    request.cancel(admin)
    assert request.status == choices.RCS_CANCELLED
    assert request.updated_by == admin
    with pytest.raises(ValidationError):
        request.cancel(admin)
    replacement = RequestArticleChange.request(
        admin, article, choices.RCT_UPDATE, "Again"
    )
    replacement.status = choices.RCS_RECEIVED
    replacement.save()
    with pytest.raises(ValidationError):
        replacement.cancel(admin)
    article.refresh_from_db()
    assert article.status == choices.AS_PUBLISHED


@pytest.mark.parametrize(
    "change_type,required",
    (
        (choices.RCT_UPDATE, 1),
        (choices.RCT_ERRATUM, 2),
        (choices.RCT_ADDENDUM, 2),
        (choices.RCT_RETRACTION, 2),
        (choices.RCT_PARTIAL_RETRACTION, 2),
    ),
)
def test_completion_requires_all_packages_from_the_linked_submission(
    context, change_type, required
):
    admin, user, collection, article, outside = context
    request = RequestArticleChange.request(admin, article, change_type, "Reason")
    assert not request.complete_if_published(admin)
    request.status = choices.RCS_RECEIVED
    request.save()
    assert not request.complete_if_published(admin)
    submission = PackageZip.objects.create(name="submission", creator=admin)
    other = PackageZip.objects.create(name="other", creator=admin)
    request.submission = submission
    request.save()
    unrelated = Package.objects.create(
        pkg_zip=other, creator=admin, public_ws_status="published"
    )
    unrelated.change_requests.add(request)
    assert not request.complete_if_published(admin)
    packages = []
    for index in range(required):
        package = Package.objects.create(pkg_zip=submission, creator=admin)
        package.change_requests.add(request)
        packages.append(package)
    assert not request.complete_if_published(admin)
    for package in packages[:-1]:
        package.public_ws_status = "published"
        package.save()
    assert not request.complete_if_published(admin)
    packages[-1].public_ws_status = "published"
    packages[-1].save()
    assert request.complete_if_published(admin)
    assert request.status == choices.RCS_COMPLETED
    assert request.updated_by == admin
    assert not request.complete_if_published(admin)
    article.refresh_from_db()
    assert article.status == choices.AS_PUBLISHED
