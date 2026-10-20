import pytest
from django.apps import apps
from django.contrib.auth import get_user_model
from django.urls import reverse

from upload import choices
from upload.models import Package

UPLOAD_ROUTES = (
    ("packagezip", "submissions"),
    ("package", "documents"),
    ("qapackage", "quality-review"),
    ("readytopublishpackage", "decisions"),
    ("archivedpackage", "archive"),
    ("xmlerrorreport", "validation/reports/xml-errors"),
    ("xmlinforeport", "validation/reports/xml-information"),
    ("validationreport", "validation/reports/package-checks"),
    ("xmlerror", "validation/results/xml-errors"),
    ("pkgvalidationresult", "validation/results/package-checks"),
    ("uploadvalidator", "validation/rules"),
)


@pytest.fixture
def admin_client(client, settings):
    settings.LANGUAGE_CODE = "en"
    user = get_user_model().objects.create_superuser(
        username="reviewer", email="reviewer@example.com", password="password"
    )
    client.force_login(user)
    return client


@pytest.mark.django_db
@pytest.mark.parametrize("model_name, path", UPLOAD_ROUTES)
def test_upload_urls_preserve_names_and_legacy_requests(admin_client, model_name, path):
    url = reverse(f"wagtailsnippets_upload_{model_name}:edit", args=[1])
    assert url == f"/admin/upload/{path}/edit/1/"
    old_url = f"/admin/snippets/upload/{model_name}/edit/1/"
    response = admin_client.get(old_url + "?q=journal&page=2")
    assert response.status_code == 302
    assert response.url == url + "?q=journal&page=2"
    response = admin_client.post(old_url, {"title": "review"})
    assert response.status_code == 307
    assert response.url == url


@pytest.mark.django_db
@pytest.mark.parametrize(
    "model_name", ["xmlerrorreport", "xmlinforeport", "validationreport"]
)
def test_report_generation_filter_handles_empty_status(admin_client, model_name):
    report_model = apps.get_model("upload", model_name)
    user = get_user_model().objects.get(username="reviewer")
    package = Package.objects.create(name="document", creator=user)
    reports = {
        value: report_model.objects.create(
            package=package,
            creator=user,
            category=choices.VAL_CAT_XML_FORMAT,
            title=value or "unspecified",
            creation=value,
        )
        for value in ("", "doing", "done")
    }
    url = reverse(f"wagtailsnippets_upload_{model_name}:list")
    for value, report in reports.items():
        response = admin_client.get(url, {"creation": value or "unspecified"})
        assert response.status_code == 200
        assert list(response.context["object_list"]) == [report]
    response = admin_client.get(url)
    assert set(response.context["object_list"]) == set(reports.values())
