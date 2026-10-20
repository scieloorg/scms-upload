from unittest.mock import Mock, patch

import pytest
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.db import transaction
from django.test import RequestFactory

from upload.models import Package, PackageZip, choices
from upload.views import PackageZipCreateView


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("rollback", [False, True])
def test_package_processing_waits_for_deposit_commit(rollback):
    user = get_user_model().objects.create_user(username="depositor")
    request = RequestFactory().post("/admin/upload/submissions/add/")
    request.user = user
    request.session = {}
    request._messages = FallbackStorage(request)
    view = PackageZipCreateView()
    view.request = request
    view.permission_policy = Mock()
    view.get_success_url = Mock(return_value="/admin/")
    form = Mock()
    form.save_all.side_effect = lambda user: PackageZip.objects.create(
        name="deposit", creator=user, show_package_validations=True
    )

    with patch("upload.views.task_receive_packages.apply_async") as enqueue:
        with transaction.atomic():
            response = view.form_valid(form)
            package = PackageZip.objects.get(name="deposit")
            assert response.status_code == 302
            assert response.url == "/admin/"
            confirmation = str(list(get_messages(request))[0])
            assert f"?pkg_zip_id={package.pk}" in confirmation
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


@pytest.mark.django_db
def test_document_tracking_explains_pending_zip_extraction(client, settings):
    settings.LANGUAGE_CODE = "en"
    user = get_user_model().objects.create_superuser(
        username="depositor", email="depositor@example.com", password="password"
    )
    pkg_zip = PackageZip.objects.create(name="deposit", creator=user)
    client.force_login(user)
    url = f"/admin/upload/documents/?pkg_zip_id={pkg_zip.pk}"
    response = client.get(url)
    pending_message = response.context["no_results_message"]
    assert "Processing runs in the background" in str(pending_message)
    assert (
        "show_package_validations"
        not in client.get("/admin/upload/submissions/add/").context["form"].fields
    )

    Package.objects.create(
        name="document",
        pkg_zip=pkg_zip,
        creator=user,
        status=choices.PS_ENQUEUED_FOR_VALIDATION,
    )
    response = client.get(url)
    assert list(response.context["object_list"].values_list("name", flat=True)) == [
        "document"
    ]
    assert response.context["no_results_message"] != pending_message
    assert client.get("/admin/upload/documents/add/").status_code in (302, 403)
