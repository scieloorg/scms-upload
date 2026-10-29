"""Reception contracts; PDF fixtures assert ZIP presence, not visual compliance."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from lxml import etree

from article import choices as ac
from article.models import Article, RequestArticleChange
from journal.models import Journal, OfficialJournal
from package.models import SPSPkg
from upload import choices, controller, tasks
from upload.article_changes import prepare_change_requests
from upload.models import Package, PackageZip, PkgValidationResult, ValidationReport

pytestmark = pytest.mark.django_db

XLINK = "{http://www.w3.org/1999/xlink}href"
KINDS = {
    ac.RCT_ERRATUM: (
        "correction",
        "corrected-article",
        "correction-forward",
        "corrected",
    ),
    ac.RCT_ADDENDUM: ("addendum", "addended-article", "addendum", "corrected"),
    ac.RCT_RETRACTION: (
        "retraction",
        "retracted-article",
        "retraction-forward",
        "retracted",
    ),
    ac.RCT_PARTIAL_RETRACTION: (
        "partial-retraction",
        "retracted-article",
        "partial-retraction",
        "retracted",
    ),
}


def document(doi, article_type="research-article"):
    root = etree.fromstring(
        b'<article xmlns:xlink="http://www.w3.org/1999/xlink" xml:lang="pt">'
        b'<front><journal-meta><issn pub-type="epub">1111-1111</issn></journal-meta>'
        b'<article-meta><article-id pub-id-type="doi"/>'
        b"<title-group><article-title>Published title.</article-title></title-group>"
        b'<pub-date publication-format="electronic" date-type="pub">'
        b"<day>1</day><month>1</month><year>2000</year></pub-date>"
        b"</article-meta></front><body><p>Published scientific content.</p>"
        b"<p>Additional preserved content.</p></body>"
        b'<back><ref-list><ref id="r1"><mixed-citation>Reference.</mixed-citation>'
        b"</ref></ref-list></back></article>"
    )
    root.set("article-type", article_type)
    root.find("front/article-meta/article-id").text = doi
    return root


@pytest.fixture
def reception(django_user_model, monkeypatch):
    user = django_user_model.objects.create(username="reception", is_superuser=True)
    official = OfficialJournal.objects.create(
        title="Reception Journal", issn_electronic="1111-1111", creator=user
    )
    journal = Journal.objects.create(
        official_journal=official, journal_acron="REC", creator=user
    )
    documents, published = {}, {}
    monkeypatch.setattr(
        Package, "xml_with_pre", property(lambda obj: documents[obj.pk])
    )
    monkeypatch.setattr(SPSPkg, "xml_with_pre", property(lambda obj: published[obj.pk]))
    counter = 0

    def make(kind=ac.RCT_ERRATUM, submission=None, public=True, requested=True):
        nonlocal counter
        counter += 1
        prefix = "article-%s" % counter
        original_doi, notice_doi = "10.1234/" + prefix, "10.1234/notice-%s" % counter
        old_xml = document(original_doi)
        sps = SPSPkg.objects.create(creator=user, sps_pkg_name=prefix)
        published[sps.pk] = SimpleNamespace(xmltree=etree.ElementTree(old_xml))
        article = Article.objects.create(
            creator=user,
            journal=journal,
            sps_pkg=sps,
            pid_v3=prefix,
            status=ac.AS_PUBLISHED,
            first_pubdate_iso="2000-01-01",
        )
        old = Package.objects.create(
            creator=user,
            journal=journal,
            article=article,
            sps_pkg=sps,
            name=prefix,
            status=choices.PS_PUBLISHED if public else choices.PS_PENDING_CORRECTION,
            public_ws_status=choices.PUBLISHED if public else None,
            qa_ws_status=choices.PUBLISHED if not public else None,
        )
        submission = submission or PackageZip.objects.create(
            creator=user, file="batch.zip"
        )
        original_xml, notice_xml = deepcopy(old_xml), document(
            notice_doi, KINDS[kind][0]
        )
        _, reverse, forward, date_type = KINDS[kind]
        for root, relation, target in (
            (original_xml, forward, notice_doi),
            (notice_xml, reverse, original_doi),
        ):
            etree.SubElement(
                root.find("front/article-meta"),
                "related-article",
                {
                    "id": "change-link",
                    "ext-link-type": "doi",
                    "related-article-type": relation,
                    XLINK: target,
                },
            )
        history = etree.SubElement(original_xml.find("front/article-meta"), "history")
        date = etree.SubElement(history, "date", {"date-type": date_type})
        for field, value in (("day", "28"), ("month", "2"), ("year", "2025")):
            etree.SubElement(date, field).text = value
        notice_xml.find("body/p").text = "Editorial explanation."
        if kind in (ac.RCT_RETRACTION, ac.RCT_PARTIAL_RETRACTION):
            title = original_xml.find("front/article-meta/title-group/article-title")
            title_prefix = (
                "ARTIGO RETRATADO: "
                if kind == ac.RCT_RETRACTION
                else "ARTIGO PARCIALMENTE RETRATADO: "
            )
            title.text = title_prefix + title.text
        if kind == ac.RCT_RETRACTION:
            for root in (original_xml, notice_xml):
                root.find("body").clear()
                etree.SubElement(root.find("body"), "p").text = "Retraction notice."
            original_xml.remove(original_xml.find("back"))
        elif kind == ac.RCT_PARTIAL_RETRACTION:
            original_xml.find("body").remove(original_xml.find("body/p"))
        members = []
        for role, root, pid in (
            ("original", original_xml, article.pid_v3),
            ("notice", notice_xml, None),
        ):
            package = Package.objects.create(
                creator=user,
                journal=journal,
                pkg_zip=submission,
                name=prefix + "-" + role,
                file=prefix + "-" + role + ".zip",
            )
            filename = prefix if role == "original" else prefix + "-notice"
            documents[package.pk] = SimpleNamespace(
                xmltree=etree.ElementTree(root),
                v3=pid,
                filename=filename + ".xml",
                filenames=[
                    prefix + ".xml",
                    prefix + "-notice.xml",
                    prefix + ".pdf",
                    prefix + "-notice.pdf",
                ],
            )
            members.append(package)
        change = (
            RequestArticleChange.request(user, article, kind, "Editorial change")
            if requested
            else None
        )
        return SimpleNamespace(
            user=user,
            journal=journal,
            article=article,
            old=old,
            submission=submission,
            original=members[0],
            notice=members[1],
            packages=members,
            request=change,
            documents=documents,
        )

    return make


def preserved(case):
    return (
        Article.objects.filter(pk=case.article.pk).values().get(),
        Package.objects.filter(pk=case.old.pk).values().get(),
    )


def assert_unbound(case, request_before):
    assert not RequestArticleChange.objects.filter(packages__in=case.packages).exists()
    if case.request:
        assert (
            RequestArticleChange.objects.filter(pk=case.request.pk).values().get()
            == request_before
        )
    for package in case.packages:
        package.refresh_from_db()
        assert not package.change_role


@pytest.mark.parametrize("kind", KINDS)
def test_valid_sps_pair_binds_only_its_members_and_preserves_public_original(
    reception, kind
):
    case = reception(kind)
    unrelated = Package.objects.create(
        creator=case.user, pkg_zip=case.submission, name="unrelated"
    )
    case.documents[unrelated.pk] = SimpleNamespace(
        xmltree=etree.ElementTree(document("10.1234/unrelated")),
        v3=None,
        filename="unrelated.xml",
        filenames=["unrelated.xml"],
    )
    before = preserved(case)
    prepare_change_requests(case.user, [*case.packages, unrelated])
    case.request.refresh_from_db()
    assert case.request.status == ac.RCS_RECEIVED
    assert case.request.submission_id == case.submission.pk
    assert set(case.request.packages.values_list("pk", flat=True)) == {
        p.pk for p in case.packages
    }
    for package, role in (
        (case.original, choices.CPR_ORIGINAL),
        (case.notice, choices.CPR_NOTICE),
    ):
        package.refresh_from_db()
        assert package.change_role == role
        assert package.category == kind
    assert set(case.notice.linked.values_list("pk", flat=True)) == {case.original.pk}
    assert not unrelated.change_requests.exists()
    assert preserved(case) == before


@pytest.mark.parametrize(
    "fault",
    [
        "absent",
        "cancelled",
        "incompatible",
        "missing-original",
        "missing-notice",
        "original-pdf",
        "notice-pdf",
        "reciprocal-link",
    ],
)
def test_invalid_pair_does_not_consume_request_or_change_previous_records(
    reception, fault
):
    case = reception(requested=fault != "absent")
    if fault == "cancelled":
        case.request.cancel(case.user)
    elif fault == "incompatible":
        case.request.change_type = ac.RCT_ADDENDUM
        case.request.save(update_fields=["change_type"])
    packages = list(case.packages)
    if fault.startswith("missing-"):
        packages.remove(case.original if fault == "missing-original" else case.notice)
    elif fault.endswith("-pdf"):
        member = case.original if fault == "original-pdf" else case.notice
        doc = case.documents[member.pk]
        expected_pdf = doc.filename.removesuffix(".xml") + ".pdf"
        doc.filenames = [name for name in doc.filenames if name != expected_pdf]
    elif fault == "reciprocal-link":
        case.documents[case.original.pk].xmltree.find(
            "front/article-meta/related-article"
        ).set(XLINK, "10.1234/different-notice")
    before = preserved(case)
    request_before = (
        RequestArticleChange.objects.filter(pk=case.request.pk).values().get()
        if case.request
        else None
    )
    with pytest.raises(ValidationError):
        prepare_change_requests(case.user, packages)
    assert_unbound(case, request_before)
    assert preserved(case) == before


def test_same_submission_retry_is_idempotent(reception):
    case = reception()
    prepare_change_requests(case.user, case.packages)
    request_before = (
        RequestArticleChange.objects.filter(pk=case.request.pk).values().get()
    )
    before = preserved(case)
    prepare_change_requests(case.user, list(reversed(case.packages)))
    assert (
        RequestArticleChange.objects.filter(pk=case.request.pk).values().get()
        == request_before
    )
    assert case.request.packages.count() == 2
    assert case.notice.linked.count() == 1
    assert preserved(case) == before


def test_received_request_cannot_be_taken_from_another_submission_in_progress(
    reception,
):
    case = reception()
    prepare_change_requests(case.user, case.packages)
    assert case.original.status in choices.PS_WIP
    other = PackageZip.objects.create(creator=case.user, file="other.zip")
    replacements = []
    for member in case.packages:
        package = Package.objects.create(
            creator=case.user, pkg_zip=other, name=member.name
        )
        case.documents[package.pk] = case.documents[member.pk]
        replacements.append(package)
    with pytest.raises(ValidationError):
        prepare_change_requests(case.user, replacements)
    case.request.refresh_from_db()
    assert case.request.status == ac.RCS_RECEIVED
    assert case.request.submission_id == case.submission.pk
    assert set(case.request.packages.values_list("pk", flat=True)) == {
        p.pk for p in case.packages
    }
    assert not RequestArticleChange.objects.filter(packages__in=replacements).exists()


@pytest.mark.parametrize("already_bound", [False, True])
def test_completed_request_cannot_be_reused_even_by_same_submission(
    reception, already_bound
):
    case = reception()
    if already_bound:
        prepare_change_requests(case.user, case.packages)
    case.request.status = ac.RCS_COMPLETED
    case.request.save(update_fields=["status"])
    before = preserved(case)
    with pytest.raises(ValidationError):
        prepare_change_requests(case.user, case.packages)
    case.request.refresh_from_db()
    assert case.request.status == ac.RCS_COMPLETED
    assert preserved(case) == before


def assert_blocked(packages):
    for package in packages:
        package.refresh_from_db()
        assert package.status == choices.PS_UNEXPECTED
        assert ValidationReport.objects.filter(package=package).exists()
        assert PkgValidationResult.objects.filter(
            report__package=package, status=choices.VALIDATION_RESULT_BLOCKING
        ).exists()


def test_receive_rejects_public_original_without_request_before_pid_or_archive(
    reception,
):
    case = reception(requested=False)
    case.old.status = choices.PS_PENDING_CORRECTION
    case.old.save(update_fields=["status"])
    before = preserved(case)
    with patch.object(controller.pp, "is_registered_xml_with_pre") as pid, patch.object(
        controller, "_archive_pending_correction_package"
    ) as archive:
        response = controller.receive_package(case.user, case.original)
    pid.assert_not_called()
    archive.assert_not_called()
    assert response["error_level"] == choices.VALIDATION_RESULT_BLOCKING
    assert response["package_status"] == choices.PS_UNEXPECTED
    assert_blocked(case.packages)
    assert preserved(case) == before


def test_batch_with_valid_pair_then_invalid_pair_enqueues_nothing_and_rolls_back_binding(
    reception,
):
    valid = reception()
    invalid = reception(submission=valid.submission)
    notice = invalid.documents[invalid.notice.pk]
    notice.filenames = [notice.filename]
    packages = valid.packages + invalid.packages
    before = [preserved(valid), preserved(invalid)]
    # A generator models split(): the entire batch must be inspected before dispatch.
    with patch.object(
        PackageZip, "split", return_value=({"package": package} for package in packages)
    ), patch.object(tasks.task_receive_package, "apply_async") as enqueue:
        tasks.task_receive_packages.run(valid.user.pk, valid.submission.pk)
    enqueue.assert_not_called()
    assert_blocked(packages)
    for case, original_before in zip((valid, invalid), before):
        case.request.refresh_from_db()
        assert case.request.status == ac.RCS_PENDING
        assert case.request.submission_id is None
        assert not case.request.packages.exists()
        assert preserved(case) == original_before


def test_qa_only_correction_with_past_xml_date_needs_no_editorial_request(reception):
    case = reception(public=False, requested=False)
    before = preserved(case)
    # Only the original is being resubmitted, not a public change notice.
    prepare_change_requests(case.user, [case.original])
    response = {"v3": case.article.pid_v3, "journal": case.journal}
    controller._check_package_is_expected(response, case.original, case.original.name)
    assert response["article"] == case.article
    assert response["previous_package_id"] == case.old.pk
    assert response["package_category"] == choices.PC_UPDATE
    assert not RequestArticleChange.objects.exists()
    assert not case.original.change_requests.exists()
    assert preserved(case) == before


def test_bound_members_do_not_hide_an_unbound_invalid_pair(reception):
    valid = reception()
    prepare_change_requests(valid.user, valid.packages)
    invalid = reception(submission=valid.submission, requested=False)
    before = preserved(valid)
    with pytest.raises(ValidationError):
        prepare_change_requests(valid.user, valid.packages + invalid.packages)
    assert not invalid.original.change_requests.exists()
    assert not invalid.notice.change_requests.exists()
    assert preserved(valid) == before


def test_notice_in_translation_language_resolves_the_original_doi_alias(reception):
    case = reception()
    original = case.documents[case.original.pk]
    notice = case.documents[case.notice.pk]
    original_doi = original.xmltree.findtext("front/article-meta/article-id")
    notice_doi = notice.xmltree.findtext("front/article-meta/article-id")
    source = case.article.sps_pkg.xml_with_pre.xmltree.getroot()
    translation = etree.SubElement(
        source,
        "sub-article",
        {
            "article-type": "translation",
            "{http://www.w3.org/XML/1998/namespace}lang": "en",
        },
    )
    stub = etree.SubElement(translation, "front-stub")
    etree.SubElement(stub, "article-id", {"pub-id-type": "doi"}).text = (
        original_doi + ".en"
    )
    translation.append(deepcopy(source.find("body")))
    updated_translation = deepcopy(translation)
    etree.SubElement(
        updated_translation.find("front-stub"),
        "related-article",
        {
            "id": "change-link-en",
            "related-article-type": "correction-forward",
            "ext-link-type": "doi",
            XLINK: notice_doi,
        },
    )
    original.xmltree.getroot().append(updated_translation)
    original.filenames.append(original.filename.removesuffix(".xml") + "-en.pdf")
    notice.xmltree.getroot().set("{http://www.w3.org/XML/1998/namespace}lang", "en")
    notice.xmltree.find("front/article-meta/related-article").set(
        XLINK, original_doi + ".en"
    )
    prepare_change_requests(case.user, case.packages)
    case.request.refresh_from_db()
    assert case.request.status == ac.RCS_RECEIVED
    assert case.request.packages.count() == 2


def test_erratum_doi_correction_can_use_the_authorized_original_filename(reception):
    case = reception()
    original = case.documents[case.original.pk]
    original.v3 = None
    original.xmltree.find(
        "front/article-meta/article-id"
    ).text = "10.1234/corrected-original"
    case.documents[case.notice.pk].xmltree.find(
        "front/article-meta/related-article"
    ).set(XLINK, "10.1234/corrected-original")
    prepare_change_requests(case.user, case.packages)
    response = {"v3": "not-yet-associated", "journal": case.journal}
    controller._check_package_is_expected(response, case.original, case.old.name)
    assert response["article"].pk == case.article.pk
    assert response["preserve_previous_package"] is True


def test_retry_keeps_the_published_xml_snapshot_even_if_qa_replaces_the_sps_source(
    reception,
):
    case = reception()
    prepare_change_requests(case.user, case.packages)
    case.request.refresh_from_db()
    snapshot = case.request.original_xml
    assert "Published scientific content." in snapshot
    source = case.article.sps_pkg.xml_with_pre.xmltree
    source.find("body/p").text = "A later QA source, not the published original."
    retry = PackageZip.objects.create(creator=case.user, file="retry.zip")
    replacements = []
    for member in case.packages:
        member.status = choices.PS_PENDING_CORRECTION
        member.save(update_fields=["status", "updated"])
        replacement = Package.objects.create(
            creator=case.user, pkg_zip=retry, name=member.name
        )
        case.documents[replacement.pk] = case.documents[member.pk]
        replacements.append(replacement)
    prepare_change_requests(case.user, replacements)
    case.request.refresh_from_db()
    assert case.request.original_xml == snapshot
    assert case.request.submission_id == retry.pk
    # Historical attempts stay associated, but only the current batch can publish.
    assert set(case.request.packages.values_list("pk", flat=True)) == {
        p.pk for p in case.packages + replacements
    }
    assert set(
        replacements[0].change_publication_packages.values_list("pk", flat=True)
    ) == {p.pk for p in replacements}
    assert case.original.change_requests.filter(pk=case.request.pk).exists()


def test_changed_original_filename_is_rejected_without_replacing_the_previous_package(
    reception,
):
    case = reception()
    doc = case.documents[case.original.pk]
    doc.filename = "renamed-original.xml"
    before = preserved(case)
    with pytest.raises(ValidationError):
        prepare_change_requests(case.user, case.packages)
    assert not case.original.change_requests.exists()
    assert preserved(case) == before
