from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.utils.translation import gettext
from lxml import etree

from article.models import Article, ArticleDOIWithLang
from collection.models import Collection, Language
from issue.models import Issue
from journal.models import Journal, JournalCollection
from upload import choices
from upload.controller import _check_article_and_journal


def test_identifiers_resolve_existing_article_and_reject_conflicts(report_scope):
    article = Article.objects.create(
        creator=report_scope.superuser,
        journal=report_scope.package_1.journal,
        pid_v3="A" * 23,
        pid_v2="S" + "1" * 22,
    )
    other = Article.objects.create(
        creator=report_scope.superuser,
        journal=article.journal,
        pid_v3="B" * 23,
        pid_v2="S" + "2" * 22,
    )

    assert (
        Article.identify(pid_v3=article.pid_v3, doi="10.1234/corrected-doi") == article
    )
    with pytest.raises(ValidationError) as error:
        Article.identify(pid_v3=article.pid_v3, pid_v2=other.pid_v2)

    assert error.value.messages == [
        gettext("The submitted identifiers refer to different documents.")
    ]


@pytest.mark.parametrize("identity_source", ["xml", "pid_provider"])
def test_reception_keeps_the_registered_article_for_both_identity_sources(
    report_scope, identity_source
):
    scope = report_scope
    issue = Issue.objects.create(creator=scope.superuser, journal=scope.journal_1)
    article = Article.objects.create(
        creator=scope.superuser,
        journal=scope.journal_1,
        issue=issue,
        pid_v3="A" * 23,
    )
    document = SimpleNamespace(
        xmltree=etree.fromstring(b"<article/>"),
        v3=article.pid_v3 if identity_source == "xml" else None,
        v2=None,
        main_doi=None,
        collection=None,
        filename="original.xml",
    )
    journal_checker = SimpleNamespace(
        check=lambda result: result.update(journal=scope.journal_1)
    )
    issue_checker = SimpleNamespace(check=lambda result: result.update(issue=issue))

    with (
        patch(
            "upload.controller.UploadJournalDataChecker.from_xmltree",
            return_value=journal_checker,
        ),
        patch(
            "upload.controller.UploadIssueDataChecker.from_xmltree",
            return_value=issue_checker,
        ),
        patch(
            "upload.controller.pp.is_registered_xml_with_pre",
            return_value={"v3": article.pid_v3},
        ) as provider,
    ):
        response = _check_article_and_journal(
            scope.package_1, document, scope.superuser
        )

    assert response["article"] == article
    assert response["v3"] == article.pid_v3
    assert response["package_category"] == choices.PC_UPDATE
    assert response["package_status"] == choices.PS_ENQUEUED_FOR_VALIDATION
    assert provider.call_count == (0 if identity_source == "xml" else 1)


@pytest.fixture
def registered_article(db, django_user_model):
    user = django_user_model.objects.create_user(username="depositor")
    collection = Collection.objects.create(creator=user, acron="scl", name="Collection")
    journal = Journal.objects.create(creator=user)
    JournalCollection.objects.create(
        creator=user, journal=journal, collection=collection
    )
    article = Article.objects.create(
        creator=user, journal=journal, pid_v3="A" * 23, pid_v2="S" + "1" * 22
    )
    for code in ("en", "pt"):
        language, _ = Language.objects.get_or_create(
            code2=code, defaults={"creator": user}
        )
        ArticleDOIWithLang.objects.create(
            creator=user, article=article, doi="10.1234/identity", lang=language
        )

    return article


@pytest.mark.parametrize("identifier", ["pid_v3", "pid_v2", "doi"])
def test_each_identifier_resolves_the_document_in_its_collection(
    registered_article, identifier
):
    value = (
        "10.1234/IDENTITY"
        if identifier == "doi"
        else getattr(registered_article, identifier)
    )

    assert (
        Article.identify(**{identifier: value}, collection_acron="scl")
        == registered_article
    )


@pytest.mark.parametrize("identifier", ["pid_v3", "pid_v2", "doi"])
def test_identification_rejects_a_different_collection(registered_article, identifier):
    value = (
        "10.1234/identity"
        if identifier == "doi"
        else getattr(registered_article, identifier)
    )

    with pytest.raises(ValidationError) as error:
        Article.identify(**{identifier: value}, collection_acron="other")

    assert error.value.messages == [
        gettext("The submitted collection does not match the registered document.")
    ]


@pytest.mark.parametrize(
    "identifiers",
    [
        {},
        {"pid_v3": "Z" * 23},
        {"pid_v2": "S" + "9" * 22},
        {"doi": "10.1234/unregistered"},
    ],
)
def test_unknown_identifiers_do_not_select_an_existing_article(
    registered_article, identifiers
):
    assert Article.identify(**identifiers) is None


def test_an_unknown_pid_v3_cannot_override_a_registered_pid_v2(registered_article):
    with pytest.raises(ValidationError) as error:
        Article.identify(pid_v3="Z" * 23, pid_v2=registered_article.pid_v2)

    assert error.value.messages == [
        gettext("The submitted identifiers refer to different documents.")
    ]


def test_a_doi_for_another_article_cannot_override_the_pid_v3(registered_article):
    other = Article.objects.create(creator=registered_article.creator, pid_v3="B" * 23)
    ArticleDOIWithLang.objects.create(
        creator=other.creator, article=other, doi="10.1234/other"
    )

    with pytest.raises(ValidationError) as error:
        Article.identify(pid_v3=registered_article.pid_v3, doi="10.1234/other")

    assert error.value.messages == [
        gettext("The submitted identifiers refer to different documents.")
    ]
