import pytest
from django.contrib.auth import get_user_model

from upload import choices
from upload.models import Package, PkgValidationResult, UploadValidator, ValidationReport


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




