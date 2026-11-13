from unittest.mock import Mock, patch

import pytest
from django.core.exceptions import ValidationError
from lxml import etree
from packtools.sps.pid_provider.xml_sps_lib import XMLWithPre

from article import choices as article_choices
from article.models import Article, RequestArticleChange
from issue.models import Issue
from package import choices as package_choices
from package.models import SPSPkg
from upload import choices
from upload.article_changes import prepare_change_requests
from upload.controller import _check_package_is_expected, receive_package
from upload.models import Package, PackageZip
from upload.querysets import get_scoped_package_queryset


@pytest.mark.django_db
def test_resubmission_selects_previous_record_and_archives_only_that_attempt(
    django_user_model,
    report_scope,
):
    user = django_user_model.objects.create(username="depositor")
    older = Package.objects.create(
        name="document",
        creator=user,
        journal=report_scope.package_1.journal,
        status=choices.PS_PENDING_CORRECTION,
    )
    previous = Package.objects.create(
        name="document",
        creator=user,
        journal=report_scope.package_1.journal,
        status=choices.PS_PENDING_CORRECTION,
    )
    current = Package.objects.create(
        name="document", creator=user, journal=report_scope.package_1.journal
    )
    response = {}

    _check_package_is_expected(response, current, "document", None)

    assert response["previous_package_id"] == previous.pk
    current.accept_document_version(response["previous_package_id"])
    older.refresh_from_db()
    previous.refresh_from_db()
    current.refresh_from_db()

    assert current.previous_package_id == previous.pk
    assert current.document_root_id == previous.pk
    assert previous.document_root_id == previous.pk
    assert previous.status == choices.PS_ARCHIVED
    assert older.status == choices.PS_PENDING_CORRECTION
    assert current.status == choices.PS_ENQUEUED_FOR_VALIDATION


@pytest.mark.django_db
def test_accepted_versions_keep_the_first_submission_as_their_root(report_scope):
    first = report_scope.package_1
    first.accept_document_version()
    second = Package.objects.create(creator=first.creator)
    second.accept_document_version(first.pk)
    third = Package.objects.create(creator=first.creator)
    third.accept_document_version(second.pk)

    first.refresh_from_db()
    second.refresh_from_db()
    third.refresh_from_db()

    assert (
        first.document_root_id
        == second.document_root_id
        == third.document_root_id
        == first.pk
    )
    assert first.previous_package_id is None
    assert second.previous_package_id == first.pk
    assert third.previous_package_id == second.pk
    assert first.status == second.status == choices.PS_ARCHIVED
    assert third.status != choices.PS_ARCHIVED
    assert first.has_newer_accepted_attempt()
    assert not third.has_newer_accepted_attempt()


@pytest.mark.django_db
def test_failed_version_link_preserves_the_previous_submission(
    report_scope, monkeypatch
):
    previous = report_scope.package_1
    current = Package.objects.create(creator=previous.creator)
    previous_status = previous.status
    save = Package.save

    def fail_current_save(package, *args, **kwargs):
        if package.pk == current.pk:
            raise RuntimeError("Version link unavailable")
        return save(package, *args, **kwargs)

    monkeypatch.setattr(Package, "save", fail_current_save)

    with pytest.raises(RuntimeError, match="Version link unavailable"):
        current.accept_document_version(previous.pk)

    previous.refresh_from_db()
    current.refresh_from_db()

    assert previous.status == previous_status
    assert previous.document_root_id is None
    assert current.document_root_id is None
    assert current.previous_package_id is None


def test_versions_preserve_published_original_within_scope(editorial_pair):
    case = editorial_pair
    scoped = get_scoped_package_queryset(case.user)
    current = set(Package.active_document_attempts(scoped).values_list("pk", flat=True))

    assert case.original.pk in current and case.old.pk not in current
    assert set(
        Package.document_versions(scoped, case.original).values_list("pk", flat=True)
    ) == {case.original.pk, case.old.pk}
    assert not Package.document_versions(
        get_scoped_package_queryset(case.outsider), case.original
    ).exists()


@pytest.mark.parametrize("previous_state", ["qa", "public", "failed"])
def test_received_replacement_keeps_identity_history_and_publication(
    report_scope, previous_state
):
    user = report_scope.superuser
    old = report_scope.package_1
    journal = old.journal
    issue = Issue.objects.create(journal=journal, publication_year="2026", creator=user)
    article = Article.objects.create(
        creator=user,
        journal=journal,
        issue=issue,
        pid_v3="A" * 23,
        pid_v2="S" + "1" * 22,
    )
    old.article, old.issue, old.name = article, issue, "original"
    old.qa_ws_status = choices.PUBLISHED
    old.public_ws_status = (
        choices.PUBLISHED if previous_state == "public" else choices.UNRELEASED
    )
    old.status = (
        choices.PS_UNEXPECTED if previous_state == "failed" else choices.PS_PREVIEW
    )
    old.document_root = old
    old.save()
    submission = PackageZip.objects.create(creator=user)
    current = Package.objects.create(
        creator=user,
        pkg_zip=submission,
        file=old.file.name,
        name="original",
        journal=journal,
    )

    def document(pid, doi, kind, relation, author):
        tree = etree.fromstring(
            (
                '<article xmlns:xlink="http://www.w3.org/1999/xlink" xml:lang="pt" '
                f'article-type="{kind}"><front><journal-meta><issn pub-type="epub">1111-1111</issn>'
                "</journal-meta><article-meta>"
                f'<article-id specific-use="scielo-v3" pub-id-type="publisher-id">{pid}</article-id>'
                f'<article-id pub-id-type="doi">{doi}</article-id>'
                f"<contrib-group><contrib><name><surname>{author}</surname></name></contrib></contrib-group>"
                f"{relation}</article-meta></front><body><p>Updated text.</p></body></article>"
            ).encode()
        )
        return XMLWithPre("", tree)

    original = document(
        article.pid_v3,
        "10.1234/original",
        "research-article",
        '<related-article related-article-type="correction-forward" ext-link-type="doi" xlink:href="10.1234/notice"/>',
        "Corrected author",
    )
    original.submitted_filename = "original.xml"
    documents = {
        current.pk: original,
        old.pk: document(
            article.pid_v3,
            "10.1234/original",
            "research-article",
            "",
            "Previous author",
        ),
    }
    packages = [current]
    if previous_state == "public":
        notice = Package.objects.create(
            creator=user,
            pkg_zip=submission,
            file=old.file.name,
            name="notice",
            journal=journal,
        )
        documents[notice.pk] = document(
            "B" * 23,
            "10.1234/notice",
            "correction",
            '<related-article related-article-type="corrected-article" ext-link-type="doi" xlink:href="10.1234/original"/>',
            "Notice author",
        )
        packages.append(notice)

    def checked(package, xml, user):
        response = {
            "v3": article.pid_v3,
            "v2": article.pid_v2,
            "journal": journal,
            "issue": issue,
            "package_status": choices.PS_ENQUEUED_FOR_VALIDATION,
        }
        _check_package_is_expected(response, package, "original", article, user)
        return response

    with patch.object(
        Package,
        "xml_with_pre",
        property(lambda package: XMLWithPre("", documents[package.pk].xmltree)),
    ), patch("upload.article_changes.require_document_pdfs"):
        if previous_state == "public":
            with pytest.raises(ValidationError):
                prepare_change_requests(user, packages)
            old.refresh_from_db()
            assert old.status == choices.PS_PREVIEW
            RequestArticleChange.objects.create(
                creator=user, article=article, change_type=article_choices.RCT_ERRATUM
            )
        prepare_change_requests(user, packages)
        current.refresh_from_db()
        with patch(
            "upload.controller.XMLWithPre.create", return_value=[original]
        ), patch(
            "upload.controller._check_article_and_journal", side_effect=checked
        ), patch(
            "upload.controller.update_zip_file"
        ), patch.object(
            Article, "update_status"
        ):
            response = receive_package(user, current)

    current.refresh_from_db()
    old.refresh_from_db()

    assert response["article"] == article
    assert current.previous_package_id == old.pk
    assert current.document_root_id == old.pk
    assert old.status == choices.PS_ARCHIVED
    assert old.public_ws_status == (
        choices.PUBLISHED if previous_state == "public" else choices.UNRELEASED
    )
    assert (
        current.validation_report.get(title="Document identity")
        .validation_results.filter(status=choices.VALIDATION_RESULT_INFO)
        .exists()
    )


def test_new_submission_preserves_objects_referenced_by_previous_publication(
    report_scope,
):
    user = report_scope.superuser
    package = SPSPkg.objects.create(
        creator=user, sps_pkg_name="1111-1111-journal-1-article", pid_v3="A" * 23
    )
    objects = {}

    def put(content, mimetype, object_name):
        objects[object_name] = content
        return "https://storage.invalid/" + object_name

    storage = Mock()
    storage.fput_content.side_effect = put

    def upload(user, components, process):
        document = XMLWithPre(
            "",
            etree.fromstring(
                f"<article><body><p>Submission {process.pk}</p></body></article>".encode()
            ),
        )
        return package.upload_xml_to_the_cloud(user, storage, document)

    with patch.object(SPSPkg, "add_pid_v3_to_zip", return_value=package), patch.object(
        package, "save_pkg_zip_file"
    ), patch.object(package, "validate"), patch.object(
        package, "upload_package_to_the_cloud", side_effect=upload
    ):
        for pk in (1, 2):
            process = Mock(pk=pk)
            SPSPkg.create_or_update(
                user,
                "article.zip",
                package_choices.PKG_ORIGIN_UPLOAD,
                True,
                {},
                {},
                process,
            )
            if pk == 1:
                published_uri = package.xml_uri

    assert len(objects) == 2
    assert package.xml_uri != published_uri
    assert (
        b"Submission 1"
        in objects[published_uri.removeprefix("https://storage.invalid/")]
    )
    assert (
        b"Submission 2"
        in objects[package.xml_uri.removeprefix("https://storage.invalid/")]
    )
