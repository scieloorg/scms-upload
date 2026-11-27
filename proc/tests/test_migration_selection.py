from unittest.mock import MagicMock, patch

import pytest

from collection.models import Collection
from issue.models import Issue
from migration import controller
from migration.models import (
    IdFileRecord,
    JournalAcronIdFile,
    MigratedIssue,
    MigratedJournal,
)
from proc import tasks
from proc.models import ArticleProc, IssueProc, JournalProc


@pytest.fixture
def migration_data(db, django_user_model):
    user = django_user_model.objects.create_user(username="selection-review")
    collection = Collection.get_or_create(acron="scl", name="SciELO Brasil", user=user)
    journal = JournalProc.objects.create(
        creator=user,
        collection=collection,
        acron="rbt",
        migrated_data=MigratedJournal.objects.create(creator=user, data={}),
    )
    issues = [
        IssueProc.objects.create(
            creator=user,
            collection=collection,
            journal_proc=journal,
            pid=f"1234-5678{year}{index:04d}",
            issue_folder=f"v10n{index}",
            issue=Issue.objects.create(creator=user, publication_year=year),
            migrated_data=MigratedIssue.objects.create(creator=user, data={}),
            docs_status="DONE",
            files_status="DONE",
        )
        for index, year in enumerate(("2024", "2024", "2023"), 1)
    ]
    article = ArticleProc.objects.create(
        creator=user, collection=collection, issue_proc=issues[0]
    )
    acron_file = JournalAcronIdFile.objects.create(
        creator=user, collection=collection, journal_acron="rbt"
    )
    for issue, suffix, todo in (
        (issues[0], 1, True),
        (issues[0], 2, False),
        (issues[1], 1, False),
    ):
        IdFileRecord.objects.create(
            creator=user,
            parent=acron_file,
            item_type="article",
            item_pid=f"S{issue.pid}{suffix:05d}",
            data={},
            todo=todo,
        )
    return user, journal, issues, article, acron_file


def test_grouping_includes_article_pending_then_falls_back_to_journal(migration_data):
    user, journal, issues, article, _ = migration_data
    grouped = ArticleProc.get_journal_and_issue_proc_ids(
        collection_acron_list=["scl"], journal_acron_list=["rbt"], status_list=["TODO"]
    )
    assert grouped[(journal.pk, "rbt")]["issue_proc_id_list"] == {issues[0].pk}
    article.delete()

    with patch.object(
        tasks.task_migrate_and_publish_articles_by_journal, "delay"
    ) as schedule:
        tasks.task_migrate_and_publish_articles.run(
            collection_acron="scl", journal_acron="rbt", publication_year="2024"
        )

    assert schedule.call_args.kwargs["journal_proc_id"] == journal.pk
    assert schedule.call_args.kwargs["issue_proc_id_list"] == []








def test_file_migration_does_not_mark_articles_for_reprocessing(migration_data):
    user, _, issues, article, _ = migration_data
    article.migration_status = "DONE"
    article.save()
    issues[0].migrate_document_files(
        user, True, MagicMock(return_value={"migrated": [], "exceptions": []})
    )
    article.refresh_from_db()
    assert article.migration_status == "DONE"
