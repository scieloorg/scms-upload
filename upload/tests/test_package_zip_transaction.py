from unittest.mock import Mock, patch

import pytest
from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import RequestFactory

from upload.models import PackageZip
from upload.views import PackageZipCreateView


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("rollback", [False, True])
def test_package_processing_waits_for_deposit_commit(rollback):
    user = get_user_model().objects.create_user(username="depositor")
    request = RequestFactory().post("/admin/snippets/upload/packagezip/add/")
    request.user = user
    view = PackageZipCreateView()
    view.request = request
    view.permission_policy = Mock()
    view.get_success_url = Mock(return_value="/admin/")
    form = Mock()
    form.save_all.side_effect = lambda user: PackageZip.objects.create(
        name="deposit", creator=user
    )

    with patch("upload.views.task_receive_packages.apply_async") as enqueue:
        with transaction.atomic():
            response = view.form_valid(form)
            package = PackageZip.objects.get(name="deposit")
            assert response.status_code == 302
            enqueue.assert_not_called()
            transaction.set_rollback(rollback)

        if rollback:
            enqueue.assert_not_called()
            assert not PackageZip.objects.filter(pk=package.pk).exists()
        else:
            enqueue.assert_called_once_with(
                kwargs={"user_id": user.pk, "pkg_zip_id": package.pk}
            )
            assert PackageZip.objects.filter(pk=package.pk).exists()
