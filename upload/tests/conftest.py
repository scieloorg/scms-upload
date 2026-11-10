from types import SimpleNamespace

import pytest
from django.contrib.auth.models import Permission

from article import choices as article_choices
from article.models import Article, RequestArticleChange
from team.signals import system_group_update
from upload import choices
from upload.models import (
    Package,
    PackageZip,
    UploadProcResult,
    PkgValidationResult,
    ValidationReport,
    XMLError,
    XMLErrorReport,
    XMLInfo,
    XMLInfoReport,
)
from upload.tests.factories import populate_package_scope


@pytest.fixture
def report_scope(db, client):
    scope = SimpleNamespace()
    populate_package_scope(scope)

    changes = Permission.objects.filter(
        content_type__app_label="upload",
        codename__in=[
            "change_validationreport",
            "change_xmlerrorreport",
            "change_xmlinforeport",
        ],
    )

    with system_group_update():
        for group in scope.analyst_user.groups.all():
            group.permissions.remove(*changes)

    scope.analyst_user = type(scope.analyst_user).objects.get(pk=scope.analyst_user.pk)
    client.force_login(scope.analyst_user)

    return scope


@pytest.fixture(
    params=[
        (ValidationReport, PkgValidationResult, "package_validation_report"),
        (XMLErrorReport, XMLError, "xml_error_report"),
        (XMLInfoReport, XMLInfo, "xml_info_report"),
    ],
    ids=["package-checks", "xml-errors", "xml-information"],
)
def report_case(request):
    return request.param


@pytest.fixture
def report_factory(report_scope):
    def create(model, package=None, creation=choices.REPORT_CREATION_DONE):
        return model.objects.create(
            package=package or report_scope.package_1,
            creator=report_scope.superuser,
            title=(
                "XML Info Report"
                if model is XMLInfoReport
                else "Report: original title"
            ),
            category=choices.VAL_CAT_XML_CONTENT,
            creation=creation,
        )

    return create


@pytest.fixture
def result_factory():
    def create(report, model, **kwargs):
        return model.objects.create(
            report=report, creator=report.creator, subject="Finding", **kwargs
        )

    return create


@pytest.fixture
def editorial_pair(report_scope):
    scope = report_scope
    user, old = scope.company_user, scope.package_1
    article = Article.objects.create(creator=user, journal=old.journal)
    old.article, old.name = article, "original"
    old.status, old.public_ws_status = choices.PS_PUBLISHED, choices.PUBLISHED
    old.document_root = old
    old.status = choices.PS_ARCHIVED
    old.save()
    submission = PackageZip.objects.create(creator=user, file=scope.pkg_zip_1.file.name)
    original, notice = [
        Package.objects.create(
            creator=user,
            journal=old.journal,
            pkg_zip=submission,
            article=article if role == choices.CPR_ORIGINAL else None,
            name=name,
            file=old.file.name,
            status=choices.PS_UNEXPECTED,
            category=choices.PC_ERRATUM,
            change_role=role,
            previous_package=old if role == choices.CPR_ORIGINAL else None,
            document_root=old if role == choices.CPR_ORIGINAL else None,
        )
        for name, role in [
            ("original", choices.CPR_ORIGINAL),
            ("notice", choices.CPR_NOTICE),
        ]
    ]
    change = RequestArticleChange.objects.create(
        creator=scope.superuser,
        article=article,
        submission=submission,
        change_type=article_choices.RCT_ERRATUM,
        status=article_choices.RCS_RECEIVED,
        was_public=True,
    )
    for member in (original, notice):
        member.change_requests.add(change)
    history = UploadProcResult.create(user, original, "Previous reception failure")

    return SimpleNamespace(
        user=user,
        outsider=scope.unrelated_user,
        old=old,
        original=original,
        notice=notice,
        history=history,
    )
