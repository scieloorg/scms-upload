import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils.translation import gettext, override

from upload import choices
from upload.models import Package, XMLInfoReport


@pytest.mark.django_db
def test_generated_report_can_be_downloaded_but_not_changed(client, settings):
    user = get_user_model().objects.create_superuser(
        username="reviewer", email="reviewer@example.com", password="password"
    )
    package = Package.objects.create(name="document", creator=user)
    report = XMLInfoReport.objects.create(
        package=package,
        creator=user,
        title="XML Info Report",
        category=choices.VAL_CAT_XML_CONTENT,
        file="reports/information.csv",
    )
    client.force_login(user)
    url = reverse("wagtailsnippets_upload_xmlinforeport:edit", args=[report.pk])
    for language in ("en", "pt-br", "es"):
        client.cookies[settings.LANGUAGE_COOKIE_NAME] = language
        response = client.get(url)
        assert response.status_code == 200
        with override(language):
            assert gettext("XML Info Report") in response.content.decode()
    assert 'name="file-clear"' not in response.content.decode()
    assert 'type="file"' not in response.content.decode()
    assert report.file.url in response.content.decode()
    document_url = (
        reverse("wagtailsnippets_upload_package:inspect", args=[package.pk])
        + "?tab=validations#xi"
    )
    assert response.context["breadcrumbs_items"][-2]["url"] == document_url
    assert response.context["view"].get_success_url() == document_url

    data = {
        "file-clear": "on",
        "file": SimpleUploadedFile("replacement.csv", b"replacement"),
    }
    response = client.post(url, data)
    assert response.status_code == 302
    report.refresh_from_db()
    assert report.file.name == "reports/information.csv"
