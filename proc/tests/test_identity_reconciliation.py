from unittest.mock import PropertyMock, patch

import pytest

from article.models import Article
from collection.models import Collection
from issue.models import Issue
from package.models import SPSPkg
from pid_provider.models import PidProviderXML
from proc import tasks
from proc.models import ArticleProc, IssueProc
from upload import tasks as upload_tasks
from upload.models import Package


@pytest.fixture
def data(db, django_user_model):
    user = django_user_model.objects.create_user(username="legacy-pid-links")
    collection = Collection.get_or_create(acron="scl", name="SciELO", user=user)
    issue = Issue.objects.create(creator=user)
    processor = IssueProc.objects.create(creator=user, collection=collection, issue=issue)
    ppx = PidProviderXML.objects.create(creator=user, v3="CANONICO")
    return user, collection, issue, processor, ppx


@pytest.mark.parametrize("entry", ["proc", "upload"])
def test_backfill_uses_legacy_link_and_xml_within_selected_issue(data, entry):
    user, collection, issue, processor, ppx = data
    legacy = SPSPkg.objects.create(creator=user)
    Article.objects.create(creator=user, issue=issue, sps_pkg=legacy, pp_xml=ppx)
    zipped = SPSPkg.objects.create(creator=user, file="package.zip")
    ArticleProc.objects.create(creator=user, collection=collection, issue_proc=processor, sps_pkg=zipped)
    Package.objects.create(creator=user, issue=issue, sps_pkg=zipped)
    outside = SPSPkg.objects.create(creator=user, file="outside.zip")
    foreign_issue = Issue.objects.create(creator=user)
    foreign = IssueProc.objects.create(creator=user, collection=collection, issue=foreign_issue)
    ArticleProc.objects.create(creator=user, collection=collection, issue_proc=foreign, sps_pkg=outside)
    Package.objects.create(creator=user, issue=foreign_issue, sps_pkg=outside)
    orphan = Article.objects.create(creator=user, issue=issue)
    original_updated = legacy.updated
    with patch.object(PidProviderXML, "xml_with_pre", new_callable=PropertyMock, return_value=True), patch(
        "package.models.pid_provider_app.is_registered_xml_zip", return_value=iter([{"ppx_id": ppx.pk}])
    ) as read:
        if entry == "proc":
            result = tasks.task_exclude_invalid_issue_articles.run(processor.pk, user_id=user.pk)
        else:
            result = upload_tasks.task_exclude_invalid_issue_articles.run(issue.pk, user_id=user.pk)

    assert all(not operation["response"]["failures"] for operation in result)
    legacy.refresh_from_db()
    zipped.refresh_from_db()
    outside.refresh_from_db()
    assert legacy.ppx_id == zipped.ppx_id == ppx.pk
    assert legacy.updated == original_updated
    assert outside.ppx_id is None
    read.assert_called_once_with(zipped.file.path)
    assert Article.exclude_invalid_records(user, issue)["total_deleted_items"] == 0
    assert ArticleProc.exclude_invalid_items(user, issue)["deleted"] == []
    assert Article.objects.filter(pk=orphan.pk).exists()


@pytest.mark.parametrize("response", [[], [{"error_type": "TemporaryError"}], [{"event_status": "multiple"}]])
def test_unidentified_package_reports_failure_without_blocking_or_deleting(data, response):
    user, collection, _, processor, _ = data
    package = SPSPkg.objects.create(creator=user, file="package.zip")
    item = ArticleProc.objects.create(creator=user, collection=collection, issue_proc=processor, sps_pkg=package)
    original_status = item.migration_status
    with patch("package.models.pid_provider_app.is_registered_xml_zip", return_value=iter(response)):
        result = tasks.task_exclude_invalid_issue_articles.run(processor.pk, user_id=user.pk)

    assert result[1]["response"]["failures"]
    package.refresh_from_db()
    item.refresh_from_db()
    assert package.ppx_id is None
    assert item.migration_status == original_status


def test_backfill_requires_explicit_scope(data):
    user = data[0]
    with pytest.raises(ValueError, match="explicit scope"):
        SPSPkg.complete_ppx(user)
    with pytest.raises(ValueError, match="explicit scope"):
        ArticleProc.complete_sps_pkg_ppx(user)
    assert ArticleProc.complete_sps_pkg_ppx(user, issue_proc_id_list=[]) == {"success": [], "failures": []}


def test_conflicting_legacy_links_are_reported_without_choosing_one(data):
    user, _, issue, _, ppx = data
    package = SPSPkg.objects.create(creator=user)
    other = PidProviderXML.objects.create(creator=user, v3="OUTRO")
    for record in (ppx, other):
        Article.objects.create(creator=user, issue=issue, sps_pkg=package, pp_xml=record)
    with patch.object(PidProviderXML, "xml_with_pre", new_callable=PropertyMock, return_value=True):
        result = Article.complete_sps_pkg_ppx(user, issue)

    package.refresh_from_db()
    assert result["failures"] and not result["success"]
    assert package.ppx_id is None
