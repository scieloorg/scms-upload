import pytest
from django.contrib.auth.models import Permission

from team.signals import system_group_update
from upload import choices
from upload.models import (
    PkgValidationResult,
    ValidationReport,
    XMLError,
    XMLErrorReport,
    XMLInfo,
    XMLInfoReport,
)
from upload.tests.test_package_scoping import PackageScopingTest


@pytest.fixture
def report_scope(db, client):
    scope = PackageScopingTest(methodName="runTest")
    scope.setUp()

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
            title="XML Info Report" if model is XMLInfoReport else "Report: original title",
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
