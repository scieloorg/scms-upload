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


def test_current_acron_file_still_returns_persisted_pending_issues(migration_data):
    user, journal, issues, _, acron_file = migration_data
    with patch.object(
        controller, "get_classic_website", return_value=MagicMock()
    ), patch.object(
        JournalAcronIdFile, "create_or_update", return_value=acron_file
    ), patch.object(
        controller, "get_bases_work_acron_id_file_records"
    ) as read:
        result = controller.import_journal_acron_id_records(
            user, ArticleProc, journal, False
        )

    read.assert_not_called()
    assert result["issue_proc_id_list"] == [issues[0].pk]
    assert acron_file.data["issue_pids"] == [issue.pid for issue in issues[:2]]


def test_journal_task_combines_imported_issues_without_losing_filters(migration_data):
    user, journal, issues, _, _ = migration_data
    with patch.object(tasks, "_get_user", return_value=user), patch.object(
        tasks, "fix_publication_status"
    ), patch.object(
        controller,
        "import_journal_acron_id_records",
        return_value={"issue_proc_id_list": [issues[1].pk, issues[2].pk]},
    ), patch.object(
        tasks, "get_api_data", return_value={}
    ), patch.object(
        tasks, "task_exclude_invalid_issue_articles"
    ), patch.object(
        tasks.task_migrate_and_publish_articles_by_issue, "delay"
    ) as schedule:
        tasks.task_migrate_and_publish_articles_by_journal.run(
            journal_proc_id=journal.pk,
            issue_proc_id_list=[issues[0].pk],
            publication_year="2024",
        )

    assert {call.kwargs["issue_proc_id"] for call in schedule.call_args_list} == {
        issue.pk for issue in issues[:2]
    }


def test_document_import_retries_all_only_when_needed(migration_data):
    user, _, issues, _, _ = migration_data
    with patch.object(
        IdFileRecord, "get_record_data", return_value={"data": {}}
    ), patch.object(ArticleProc, "create_or_update", return_value=object()) as create:
        for status, expected in (("DONE", 1), ("DONE", 0), ("TODO", 2)):
            issues[0].docs_status = status
            create.reset_mock()
            result = issues[0].migrate_document_records(user)
            assert result["exception"] is None
            assert create.call_count == expected, (status, expected)


def test_file_migration_does_not_mark_articles_for_reprocessing(migration_data):
    user, _, issues, article, _ = migration_data
    article.migration_status = "DONE"
    article.save()
    issues[0].migrate_document_files(
        user, True, MagicMock(return_value={"migrated": [], "exceptions": []})
    )
    article.refresh_from_db()
    assert article.migration_status == "DONE"
