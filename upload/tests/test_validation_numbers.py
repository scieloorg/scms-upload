import pytest
from django.contrib.auth import get_user_model

from upload import choices
from upload.models import (
    Package,
    PkgValidationResult,
    UploadValidator,
    ValidationReport,
    XMLError,
    XMLErrorReport,
)
from upload.wagtail_hooks import UploadValidatorViewSet


@pytest.mark.django_db
@pytest.mark.parametrize(
    "statuses, expected_issues, expected_status",
    [
        ([choices.VALIDATION_RESULT_SUCCESS] * 4, 0, choices.PS_READY_TO_PREVIEW),
        (
            [choices.VALIDATION_RESULT_SUCCESS, choices.VALIDATION_RESULT_FAILURE],
            1,
            choices.PS_PENDING_CORRECTION,
        ),
        (
            [choices.VALIDATION_RESULT_SUCCESS, choices.VALIDATION_RESULT_WARNING],
            1,
            choices.PS_PENDING_CORRECTION,
        ),
        (
            [choices.VALIDATION_RESULT_SUCCESS, choices.VALIDATION_RESULT_UNKNOWN],
            1,
            choices.PS_PENDING_CORRECTION,
        ),
        (
            [choices.VALIDATION_RESULT_SUCCESS, choices.VALIDATION_RESULT_BLOCKING],
            1,
            choices.PS_PENDING_CORRECTION,
        ),
        ([], 0, choices.PS_ENQUEUED_FOR_VALIDATION),
    ],
)
def test_only_unsuccessful_package_validations_count_as_issues(
    statuses, expected_issues, expected_status
):
    user = get_user_model().objects.create_user(username="depositor")
    package = Package.objects.create(creator=user)
    report = ValidationReport.objects.create(
        package=package, creator=user, category=choices.VAL_CAT_PACKAGE_FILE
    )
    for status in statuses:
        PkgValidationResult(report=report, creator=user, status=status).save()

    package.calculate_validation_numbers()
    package.refresh_from_db()
    validator = UploadValidator(publication_rule=choices.STRICT_AUTO_PUBLICATION)

    assert package.numbers["total_validations"] == len(statuses)
    assert package.numbers["total_pkg_issues"] == expected_issues
    assert bool(package.has_errors) == bool(expected_issues)
    assert validator.get_pos_validation_status(package) == expected_status


@pytest.mark.django_db
@pytest.mark.parametrize("legacy_numbers", [False, True])
def test_completed_review_summary_preserves_reaction_totals(legacy_numbers):
    user = get_user_model().objects.create_user(username="reviewer")
    package = Package.objects.create(creator=user, status=choices.PS_PREVIEW)
    UploadValidator.objects.create(creator=user)
    report = XMLErrorReport.objects.create(
        package=package,
        creator=user,
        category=choices.VAL_CAT_XML_CONTENT,
        xml_producer_ack=True,
    )
    for reaction in (
        choices.ER_REACTION_NOT_TO_FIX,
        choices.ER_REACTION_NOT_TO_FIX,
        choices.ER_REACTION_IMPOSSIBLE_TO_FIX,
        choices.ER_REACTION_FIX,
    ):
        XMLError(
            report=report,
            creator=user,
            status=choices.VALIDATION_RESULT_FAILURE,
            reaction=reaction,
        ).save()
    package.calculate_validation_numbers()
    if legacy_numbers:
        package.numbers.pop("total_contested_xml_errors")
        package.numbers.pop("total_declared_impossible_to_fix")
        package.save()
    package.refresh_from_db()

    summary = package.summary
    assert summary["is_error_review_finished"] is True
    assert summary["total_contested_xml_errors"] == 2
    assert summary["total_declared_impossible_to_fix"] == 1
    assert summary["conclusion"]


@pytest.mark.django_db
def test_validation_limits_accept_zero_and_reject_out_of_range(django_user_model):
    user = django_user_model.objects.create_user(username="coordinator")
    form_class = UploadValidatorViewSet().get_form_class()
    data = {
        "max_xml_warnings_percentage": 0,
        "max_xml_errors_percentage": 0,
        "max_impossible_to_fix_percentage": 0,
        "decision_for_critical_errors": choices.PS_VALIDATED_WITH_ERRORS,
        "publication_rule": choices.MANUAL_PUBLICATION,
        "validation_params": "{}",
    }
    form = form_class(data=data, for_user=user)
    assert form.is_valid(), form.errors
    invalid = dict(
        data,
        max_xml_warnings_percentage=101,
        max_xml_errors_percentage=-1,
        max_impossible_to_fix_percentage=101,
    )
    form = form_class(data=invalid, for_user=user)
    assert set(form.errors) == {
        "max_xml_warnings_percentage",
        "max_xml_errors_percentage",
        "max_impossible_to_fix_percentage",
    }
