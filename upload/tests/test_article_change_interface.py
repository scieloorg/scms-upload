import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.urls import reverse
from django.utils.translation import override

from article import choices as article_choices
from article.authorization import allowed_article_change_types
from article.models import Article, RequestArticleChange
from upload import choices
from upload.forms import RequestDocumentChangeForm
from upload.models import Package, UploadProcResult
from upload.change_views import RequestArticleChangeView

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def default_language(settings):
    # Client requests use the default language unless a language cookie is set.
    # Keep reverse() in the same language, including after LocaleMiddleware runs.
    with override(settings.LANGUAGE_CODE):
        yield


@pytest.fixture
def change_document(report_scope):
    package = report_scope.package_1
    article = Article.objects.create(
        journal=package.journal,
        creator=report_scope.superuser,
        first_pubdate_iso="2000-01-01",
        status=article_choices.AS_PUBLISHED,
    )
    package.article = article
    package.public_ws_status = choices.PUBLISHED
    package.save(update_fields=["article", "public_ws_status"])
    return package


def request_url(package):
    return reverse("upload:request_article_change", args=[package.pk])


def inspect_url(package):
    return reverse("wagtailsnippets_upload_package:inspect", args=[package.pk])


def test_get_and_cancel_return_without_creating_request(
    client, report_scope, change_document
):
    response = client.get(request_url(change_document))
    assert response.status_code == 200
    assert response.context["document_url"] == inspect_url(change_document)
    assert response.context["document_identity"] == change_document.document_identity
    assert "article" not in response.context["form"].fields
    assert f'href="{inspect_url(change_document)}"' in response.content.decode()
    assert client.get(response.context["document_url"]).status_code == 200
    assert not RequestArticleChange.objects.exists()


@pytest.mark.parametrize("data", ({}, {"change_type": "erratum", "comment": " \n\t"}))
def test_required_fields(client, change_document, data):
    response = client.post(request_url(change_document), data)
    assert response.status_code == 200
    assert response.context["form"].errors
    assert not RequestArticleChange.objects.exists()


def test_post_ignores_tampered_article_and_preserves_existing_states(
    client, report_scope, change_document
):
    package = change_document
    outside = Article.objects.create(
        journal=report_scope.journal_2, creator=report_scope.superuser
    )
    old = Package.objects.create(
        article=package.article,
        journal=package.journal,
        creator=report_scope.superuser,
        status=choices.PS_PUBLISHED,
    )
    package_before = Package.objects.filter(pk=package.pk).values().get()
    old_before = Package.objects.filter(pk=old.pk).values().get()
    article_before = Article.objects.filter(pk=package.article_id).values().get()
    response = client.post(
        request_url(package),
        {
            "change_type": article_choices.RCT_ERRATUM,
            "comment": "  Correct the title  ",
            "article": outside.pk,
            "status": article_choices.RCS_COMPLETED,
            "public_ws_status": choices.DEPUBLISHED,
        },
    )
    assert response.status_code == 302
    assert response.url == inspect_url(package)
    change = RequestArticleChange.objects.get()
    assert change.article_id == package.article_id
    assert change.status == article_choices.RCS_PENDING
    assert change.comment == "Correct the title"
    assert change.creator == report_scope.analyst_user
    assert Package.objects.filter(pk=package.pk).values().get() == package_before
    assert Package.objects.filter(pk=old.pk).values().get() == old_before
    assert (
        Article.objects.filter(pk=package.article_id).values().get() == article_before
    )
    event = UploadProcResult.objects.get(proc=package, name="request_article_change")
    assert event.completed
    assert event.detail == {
        "request_id": change.pk,
        "change_type": change.change_type,
        "comment": change.comment,
        "status": change.status,
    }
    response = client.get(inspect_url(package) + "?tab=history")
    assert response.context["timeline_events"][0]["comment"] == change.comment
    assert (
        str(response.context["timeline_events"][0]["label"])
        == "Request document change"
    )
    assert not any(
        button.url == request_url(package)
        for button in response.context["document_actions"]
    )
    repeated = client.post(
        request_url(package),
        {"change_type": article_choices.RCT_ERRATUM, "comment": "Again"},
    )
    assert repeated.context["form"].non_field_errors()
    assert RequestArticleChange.objects.count() == 1


@pytest.mark.parametrize("method", ("get", "post"))
def test_cross_scope_is_not_exposed(client, rf, report_scope, change_document, method):
    outside = report_scope.package_2
    outside.article = Article.objects.create(
        journal=outside.journal,
        creator=report_scope.superuser,
        status=article_choices.AS_PUBLISHED,
        first_pubdate_iso="2000-01-01",
    )
    outside.public_ws_status = choices.PUBLISHED
    outside.name = "OUTSIDE-EDITORIAL-SCOPE-SECRET"
    outside.save(update_fields=["article", "public_ws_status", "name"])
    report_scope.analyst_user.user_permissions.add(
        *Permission.objects.filter(
            content_type__app_label="article",
            codename__in=("request_article_change", "add_requestarticlechange"),
        )
    )
    data = {
        "change_type": article_choices.RCT_ERRATUM,
        "comment": "Attempt outside editorial scope",
        "article": change_document.article_id,
    }
    request = getattr(rf, method)(request_url(outside), data)
    request.user = report_scope.analyst_user
    with pytest.raises(Http404):
        RequestArticleChangeView.as_view()(request, pk=outside.pk)

    # Follow LocaleMiddleware's possible localized-404 redirect, not just a 302.
    response = getattr(client, method)(request_url(outside), data, follow=True)
    assert response.status_code == 404
    assert outside.name not in response.content.decode()
    assert not RequestArticleChange.objects.exists()


@pytest.mark.parametrize("method", ("get", "post"))
def test_qa_only_document_is_denied(client, rf, report_scope, change_document, method):
    change_document.public_ws_status = choices.DEPUBLISHED
    change_document.qa_ws_status = choices.PUBLISHED
    change_document.save(update_fields=["public_ws_status", "qa_ws_status"])
    data = {"change_type": article_choices.RCT_ERRATUM, "comment": "QA only"}
    request = getattr(rf, method)(request_url(change_document), data)
    request.user = report_scope.analyst_user
    with pytest.raises(PermissionDenied):
        RequestArticleChangeView.as_view()(request, pk=change_document.pk)

    response = getattr(client, method)(request_url(change_document), data)
    assert response.status_code == 302
    assert response.url == reverse("wagtailadmin_home")
    assert not RequestArticleChange.objects.exists()
    response = client.get(inspect_url(change_document))
    assert not any(
        button.url == request_url(change_document)
        for button in response.context["document_actions"]
    )


@pytest.mark.parametrize("method", ("get", "post"))
def test_company_permissions_do_not_grant_editorial_scope(
    client, rf, report_scope, change_document, method
):
    user = report_scope.company_user
    user.user_permissions.add(
        *Permission.objects.filter(
            content_type__app_label="article",
            codename__in=("request_article_change", "add_requestarticlechange"),
        )
    )
    client.force_login(user)
    data = {
        "change_type": article_choices.RCT_ERRATUM,
        "comment": "No editorial scope",
    }
    request = getattr(rf, method)(request_url(change_document), data)
    request.user = user
    with pytest.raises(PermissionDenied):
        RequestArticleChangeView.as_view()(request, pk=change_document.pk)

    response = getattr(client, method)(request_url(change_document), data)
    assert response.status_code == 302
    assert response.url == reverse("wagtailadmin_home")
    assert not RequestArticleChange.objects.exists()


def test_form_filters_choices_and_rejects_unknown_type(report_scope, change_document):
    user = report_scope.analyst_user
    form = RequestDocumentChangeForm(user=user, article=change_document.article)
    assert tuple(value for value, label in form.fields["change_type"].choices) == (
        allowed_article_change_types(user, change_document.article)
    )
    form = RequestDocumentChangeForm(
        {"change_type": "invalid", "comment": "Reason"},
        user=user,
        article=change_document.article,
    )
    assert not form.is_valid()
    assert "change_type" in form.errors


def test_validation_error_is_nonfield_and_rolls_back(
    client, change_document, monkeypatch
):
    def fail_event(*args, **kwargs):
        raise ValidationError({"comment": "Cannot record this request"})

    monkeypatch.setattr(UploadProcResult, "create", fail_event)
    response = client.post(
        request_url(change_document),
        {"change_type": article_choices.RCT_ERRATUM, "comment": "Correct title"},
    )
    assert response.context["form"].non_field_errors() == ["Cannot record this request"]
    assert not RequestArticleChange.objects.exists()


def test_history_visible_and_escaped_on_readonly_reports(
    client, report_scope, change_document, report_case, report_factory
):
    model, result_model, route_name = report_case
    old = RequestArticleChange.objects.create(
        article=change_document.article,
        creator=report_scope.superuser,
        change_type=article_choices.RCT_ADDENDUM,
        status=article_choices.RCS_COMPLETED,
        comment="Previous request",
    )
    active = RequestArticleChange.request(
        report_scope.analyst_user,
        change_document.article,
        article_choices.RCT_ERRATUM,
        '<script>alert("unsafe")</script>',
    )
    report = report_factory(model)
    for url in (
        inspect_url(change_document),
        reverse(f"upload:{route_name}", args=[report.pk]),
    ):
        response = client.get(url)
        assert response.status_code == 200
        assert list(response.context["article_change_requests"]) == [active, old]
        html = response.content.decode()
        assert "Previous request" in html
        assert "&lt;script&gt;" in html
        assert '<script>alert("unsafe")</script>' not in html
        assert "<details>" in html
        assert not any(
            button.url == request_url(change_document)
            for button in response.context["document_actions"]
        )
    assert not response.context["can_respond"]
