import pytest

from upload import choices
from upload.controller import (
    _archive_pending_correction_package,
    _check_package_is_expected,
)
from upload.models import Package


@pytest.mark.django_db
def test_resubmission_selects_previous_record_and_archives_only_that_attempt(
    django_user_model,
):
    user = django_user_model.objects.create(username="depositor")
    older = Package.objects.create(
        name="document", creator=user, status=choices.PS_PENDING_CORRECTION
    )
    previous = Package.objects.create(
        name="document", creator=user, status=choices.PS_PENDING_CORRECTION
    )
    current = Package.objects.create(name="document", creator=user)
    response = {}

    _check_package_is_expected(response, current, "document")
    assert response["previous_package_id"] == previous.pk
    _archive_pending_correction_package(response)
    older.refresh_from_db()
    previous.refresh_from_db()
    current.refresh_from_db()
    assert previous.status == choices.PS_ARCHIVED
    assert older.status == choices.PS_PENDING_CORRECTION
    assert current.status == choices.PS_ENQUEUED_FOR_VALIDATION
