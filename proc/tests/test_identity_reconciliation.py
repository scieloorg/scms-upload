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
