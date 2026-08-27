"""
Testes unitários das tasks Celery de migração e publicação de artigos
(seção ARTICLES de proc.tasks e a publicação avulsa de artigos).
"""
from unittest.mock import MagicMock, call, patch

from django.test import TestCase

from proc.tasks import (
    task_migrate_and_publish_articles,
    task_migrate_and_publish_articles_by_journal,
    task_migrate_and_publish_articles_by_issue,
    task_publish_issue_articles,
    task_sync_issue,
    task_publish_articles,
    task_publish_article,
)


def make_id_queryset(items):
    """Cria um MagicMock que se comporta como um QuerySet de ids (values_list)."""
    qs = MagicMock()
    qs.count.return_value = len(items)
    qs.__iter__.return_value = iter(items)
    return qs


class TaskMigrateAndPublishArticlesTest(TestCase):
    """Testes para task_migrate_and_publish_articles."""

    @patch("proc.tasks.task_migrate_and_publish_articles_by_journal")
    @patch("proc.tasks.ArticleProc")
    @patch("proc.tasks.TaskTracker")
    def test_schedules_task_by_journal_for_each_journal_group(
        self, mock_task_tracker, mock_article_proc, mock_by_journal
    ):
        mock_tracker_instance = MagicMock()
        mock_task_tracker.create.return_value = mock_tracker_instance
        mock_article_proc.get_journal_and_issue_proc_ids.return_value = {
            (1, "abc"): {10, 11},
        }

        task_migrate_and_publish_articles(
            journal_acron="abc",
            collection_acron="scl",
        )

        mock_by_journal.delay.assert_called_once()
        kwargs = mock_by_journal.delay.call_args.kwargs
        self.assertEqual(kwargs["journal_proc_id"], 1)
        self.assertEqual(kwargs["journal_acron"], "abc")
        self.assertEqual(kwargs["collection_acron"], "scl")
        self.assertIsInstance(kwargs["issue_proc_id_list"], list)
        self.assertEqual(sorted(kwargs["issue_proc_id_list"]), [10, 11])
        self.assertEqual(mock_tracker_instance.total_to_process, 1)
        mock_tracker_instance.finish.assert_called_once()

    @patch("proc.tasks.task_migrate_and_publish_articles_by_journal")
    @patch("proc.tasks.ArticleProc")
    @patch("proc.tasks.TaskTracker")
    def test_nothing_to_process_does_not_schedule_and_finishes(
        self, mock_task_tracker, mock_article_proc, mock_by_journal
    ):
        mock_tracker_instance = MagicMock()
        mock_task_tracker.create.return_value = mock_tracker_instance
        mock_article_proc.get_journal_and_issue_proc_ids.return_value = {}

        task_migrate_and_publish_articles()

        mock_by_journal.delay.assert_not_called()
        self.assertEqual(mock_tracker_instance.total_to_process, 0)
        mock_tracker_instance.finish.assert_called_once()

    @patch("proc.tasks.task_migrate_and_publish_articles_by_journal")
    @patch("proc.tasks.ArticleProc")
    @patch("proc.tasks.TaskTracker")
    def test_exception_path_calls_finish_with_exception(
        self, mock_task_tracker, mock_article_proc, mock_by_journal
    ):
        mock_tracker_instance = MagicMock()
        mock_task_tracker.create.return_value = mock_tracker_instance
        mock_article_proc.get_journal_and_issue_proc_ids.side_effect = RuntimeError(
            "boom"
        )

        task_migrate_and_publish_articles()

        mock_by_journal.delay.assert_not_called()
        finish_kwargs = mock_tracker_instance.finish.call_args.kwargs
        self.assertIsInstance(finish_kwargs["exception"], RuntimeError)

    @patch("proc.tasks.task_migrate_and_publish_articles_by_journal")
    @patch("proc.tasks.ArticleProc")
    @patch("proc.tasks.TaskTracker")
    def test_kwargs_use_journal_acron_from_grouped_dict_key(
        self, mock_task_tracker, mock_article_proc, mock_by_journal
    ):
        # journal_acron do dict agrupado prevalece sobre o parâmetro de filtro
        mock_article_proc.get_journal_and_issue_proc_ids.return_value = {
            (2, "xyz"): {30},
        }

        task_migrate_and_publish_articles(
            journal_acron="filter-acron", collection_acron="scl"
        )

        kwargs = mock_by_journal.delay.call_args.kwargs
        self.assertEqual(kwargs["journal_acron"], "xyz")
        self.assertEqual(kwargs["journal_proc_id"], 2)
        self.assertEqual(kwargs["issue_proc_id_list"], [30])


class TaskMigrateAndPublishArticlesByJournalTest(TestCase):
    """Testes para task_migrate_and_publish_articles_by_journal."""

    @patch("proc.tasks.get_total_status_data")
    @patch("proc.tasks.task_migrate_and_publish_articles_by_issue")
    @patch("proc.tasks.task_exclude_invalid_issue_articles")
    @patch("proc.tasks.get_api_data")
    @patch("proc.tasks.migration_controller")
    @patch("proc.tasks.fix_publication_status")
    @patch("proc.tasks.JournalProc")
    @patch("proc.tasks.TaskTracker")
    def test_happy_path(
        self,
        mock_task_tracker,
        mock_journal_proc,
        mock_fix_pub_status,
        mock_migration_controller,
        mock_get_api_data,
        mock_exclude_invalid,
        mock_by_issue,
        mock_get_total_status_data,
    ):
        mock_tracker_instance = MagicMock()
        mock_task_tracker.create.return_value = mock_tracker_instance
        mock_get_total_status_data.return_value = {}

        mock_journal = MagicMock()
        mock_journal.collection = MagicMock()
        mock_journal_proc.objects.get.return_value = mock_journal

        mock_migration_controller.import_journal_acron_id_records.return_value = {
            "imported": 3
        }
        mock_get_api_data.side_effect = [{"qa": True}, {"public": True}]
        mock_exclude_invalid.return_value = {"excluded": 1}

        task_migrate_and_publish_articles_by_journal(
            journal_proc_id=1,
            issue_proc_id_list=[10, 11],
        )

        mock_fix_pub_status.assert_called_once_with(mock_journal.collection)
        mock_migration_controller.import_journal_acron_id_records.assert_called_once()
        self.assertEqual(mock_by_issue.delay.call_count, 2)
        for c in mock_by_issue.delay.call_args_list:
            self.assertEqual(
                c.kwargs["exclude_invalid_articles_response"], {"excluded": 1}
            )
            self.assertEqual(c.kwargs["qa_api_data"], {"qa": True})
            self.assertEqual(c.kwargs["public_api_data"], {"public": True})
        self.assertEqual(mock_tracker_instance.total_processed, 2)
        self.assertEqual(mock_tracker_instance.total_to_process, 2)
        mock_tracker_instance.finish.assert_called_once()

    @patch("proc.tasks.task_migrate_and_publish_articles_by_issue")
    @patch("proc.tasks.TaskTracker")
    def test_missing_journal_proc_id_raises_value_error_and_finishes_with_exception(
        self, mock_task_tracker, mock_by_issue
    ):
        mock_tracker_instance = MagicMock()
        mock_task_tracker.create.return_value = mock_tracker_instance

        task_migrate_and_publish_articles_by_journal(journal_proc_id=None)

        mock_by_issue.delay.assert_not_called()
        finish_kwargs = mock_tracker_instance.finish.call_args.kwargs
        self.assertIsInstance(finish_kwargs["exception"], ValueError)

    @patch("proc.tasks.get_total_status_data")
    @patch("proc.tasks.task_migrate_and_publish_articles_by_issue")
    @patch("proc.tasks.get_api_data")
    @patch("proc.tasks.migration_controller")
    @patch("proc.tasks.fix_publication_status")
    @patch("proc.tasks.JournalProc")
    @patch("proc.tasks.TaskTracker")
    def test_exception_during_import_calls_finish_with_exception(
        self,
        mock_task_tracker,
        mock_journal_proc,
        mock_fix_pub_status,
        mock_migration_controller,
        mock_get_api_data,
        mock_by_issue,
        mock_get_total_status_data,
    ):
        mock_tracker_instance = MagicMock()
        mock_task_tracker.create.return_value = mock_tracker_instance
        mock_get_total_status_data.return_value = {}
        mock_journal_proc.objects.get.return_value = MagicMock()
        mock_migration_controller.import_journal_acron_id_records.side_effect = (
            RuntimeError("import failed")
        )

        task_migrate_and_publish_articles_by_journal(
            journal_proc_id=1, issue_proc_id_list=[]
        )

        mock_by_issue.delay.assert_not_called()
        finish_kwargs = mock_tracker_instance.finish.call_args.kwargs
        self.assertIsInstance(finish_kwargs["exception"], RuntimeError)

    @patch("proc.tasks.get_total_status_data")
    @patch("proc.tasks.task_migrate_and_publish_articles_by_issue")
    @patch("proc.tasks.task_exclude_invalid_issue_articles")
    @patch("proc.tasks.get_api_data")
    @patch("proc.tasks.migration_controller")
    @patch("proc.tasks.fix_publication_status")
    @patch("proc.tasks.JournalProc")
    @patch("proc.tasks.TaskTracker")
    def test_exclude_invalid_articles_response_flows_into_delay_kwargs_per_issue(
        self,
        mock_task_tracker,
        mock_journal_proc,
        mock_fix_pub_status,
        mock_migration_controller,
        mock_get_api_data,
        mock_exclude_invalid,
        mock_by_issue,
        mock_get_total_status_data,
    ):
        mock_get_total_status_data.return_value = {}
        mock_journal_proc.objects.get.return_value = MagicMock()
        mock_get_api_data.side_effect = [{"qa": True}, {"public": True}]
        mock_exclude_invalid.side_effect = [{"e": 1}, {"e": 2}]

        task_migrate_and_publish_articles_by_journal(
            journal_proc_id=1,
            issue_proc_id_list=[10, 20],
            username="user1",
            user_id=None,
        )

        mock_exclude_invalid.assert_has_calls(
            [
                call(
                    issue_proc_id=10,
                    username="user1",
                    user_id=None,
                    public_api_data={"public": True},
                ),
                call(
                    issue_proc_id=20,
                    username="user1",
                    user_id=None,
                    public_api_data={"public": True},
                ),
            ]
        )
        calls = mock_by_issue.delay.call_args_list
        self.assertEqual(calls[0].kwargs["issue_proc_id"], 10)
        self.assertEqual(calls[0].kwargs["exclude_invalid_articles_response"], {"e": 1})
        self.assertEqual(calls[1].kwargs["issue_proc_id"], 20)
        self.assertEqual(calls[1].kwargs["exclude_invalid_articles_response"], {"e": 2})


class TaskMigrateAndPublishArticlesByIssueTest(TestCase):
    """Testes para task_migrate_and_publish_articles_by_issue."""

    @patch("proc.tasks.get_total_status_data")
    @patch("proc.tasks.task_publish_issue_articles")
    @patch("proc.tasks.ArticleProc")
    @patch("proc.tasks.migration_controller")
    @patch("proc.tasks.IssueProc")
    @patch("proc.tasks.TaskTracker")
    def test_happy_path_migrates_articles_and_schedules_publish(
        self,
        mock_task_tracker,
        mock_issue_proc,
        mock_migration_controller,
        mock_article_proc,
        mock_publish_issue_articles,
        mock_get_total_status_data,
    ):
        mock_tracker_instance = MagicMock()
        mock_task_tracker.create.return_value = mock_tracker_instance
        mock_get_total_status_data.return_value = {}

        mock_issue = MagicMock()
        mock_issue.migrate_document_records.return_value = {"records": "ok"}
        mock_issue.migrate_document_files.return_value = {"files": "ok"}
        mock_issue.journal_proc_id = 99
        mock_issue.articleproc_set.count.return_value = 5
        mock_issue_proc.objects.select_related.return_value.get.return_value = (
            mock_issue
        )

        article1 = MagicMock(pid="pid-1")
        article2 = MagicMock(pid="pid-2")
        mock_qs = make_id_queryset([article1, article2])
        mock_article_proc.select_items.return_value = mock_qs

        task_migrate_and_publish_articles_by_issue(issue_proc_id=5)

        mock_issue.migrate_document_records.assert_called_once_with(None, False)
        mock_issue.migrate_document_files.assert_called_once_with(
            None, False, mock_migration_controller.migrate_issue_files
        )
        article1.migrate_article.assert_called_once_with(None, False)
        article2.migrate_article.assert_called_once_with(None, False)
        mock_publish_issue_articles.delay.assert_called_once()
        self.assertEqual(mock_tracker_instance.total_processed, 2)
        mock_tracker_instance.finish.assert_called_once()
        finish_kwargs = mock_tracker_instance.finish.call_args.kwargs
        self.assertTrue(finish_kwargs["completed"])

    @patch("proc.tasks.get_total_status_data")
    @patch("proc.tasks.task_publish_issue_articles")
    @patch("proc.tasks.ArticleProc")
    @patch("proc.tasks.migration_controller")
    @patch("proc.tasks.IssueProc")
    @patch("proc.tasks.TaskTracker")
    def test_per_article_exception_continues_loop_and_still_schedules_publish(
        self,
        mock_task_tracker,
        mock_issue_proc,
        mock_migration_controller,
        mock_article_proc,
        mock_publish_issue_articles,
        mock_get_total_status_data,
    ):
        mock_tracker_instance = MagicMock()
        mock_task_tracker.create.return_value = mock_tracker_instance
        mock_get_total_status_data.return_value = {}

        mock_issue = MagicMock()
        mock_issue_proc.objects.select_related.return_value.get.return_value = (
            mock_issue
        )

        article1 = MagicMock(pid="pid-1")
        article1.migrate_article.side_effect = RuntimeError("boom")
        article2 = MagicMock(pid="pid-2")
        mock_qs = make_id_queryset([article1, article2])
        mock_article_proc.select_items.return_value = mock_qs

        task_migrate_and_publish_articles_by_issue(issue_proc_id=5)

        self.assertEqual(mock_tracker_instance.total_processed, 1)
        mock_publish_issue_articles.delay.assert_called_once()
        mock_tracker_instance.finish.assert_called_once()
        finish_kwargs = mock_tracker_instance.finish.call_args.kwargs
        self.assertFalse(finish_kwargs["completed"])

    @patch("proc.tasks.get_total_status_data")
    @patch("proc.tasks.task_publish_issue_articles")
    @patch("proc.tasks.ArticleProc")
    @patch("proc.tasks.migration_controller")
    @patch("proc.tasks.IssueProc")
    @patch("proc.tasks.TaskTracker")
    def test_kwargs_correctness_for_select_items_and_delay(
        self,
        mock_task_tracker,
        mock_issue_proc,
        mock_migration_controller,
        mock_article_proc,
        mock_publish_issue_articles,
        mock_get_total_status_data,
    ):
        mock_get_total_status_data.return_value = {}
        mock_issue = MagicMock()
        mock_issue_proc.objects.select_related.return_value.get.return_value = (
            mock_issue
        )
        mock_article_proc.select_items.return_value = make_id_queryset([])

        task_migrate_and_publish_articles_by_issue(
            user_id=None,
            username="u1",
            issue_proc_id=5,
            force_update=True,
        )

        mock_issue_proc.objects.select_related.assert_called_once_with(
            "collection", "journal_proc"
        )
        mock_article_proc.select_items.assert_called_once_with(
            issue_proc_id=5, status_list=None
        )
        delay_kwargs = mock_publish_issue_articles.delay.call_args.kwargs
        self.assertEqual(delay_kwargs["user_id"], None)
        self.assertEqual(delay_kwargs["username"], "u1")
        self.assertEqual(delay_kwargs["issue_proc_id"], 5)
        self.assertTrue(delay_kwargs["force_update"])
        # confere explicitamente que o status passado ao filho é o já normalizado
        # (force_update=True -> PROGRESS_STATUS_FORCE_UPDATE)
        self.assertIn("REPROC", delay_kwargs["status"])
        self.assertIn("TODO", delay_kwargs["status"])
        self.assertIn("DONE", delay_kwargs["status"])

    @patch("proc.tasks.IssueProc")
    @patch("proc.tasks.TaskTracker")
    def test_outer_exception_calls_finish_with_exception(
        self, mock_task_tracker, mock_issue_proc
    ):
        mock_tracker_instance = MagicMock()
        mock_task_tracker.create.return_value = mock_tracker_instance
        mock_issue_proc.objects.select_related.return_value.get.side_effect = (
            RuntimeError("not found")
        )

        task_migrate_and_publish_articles_by_issue(issue_proc_id=999)

        finish_kwargs = mock_tracker_instance.finish.call_args.kwargs
        self.assertIsInstance(finish_kwargs["exception"], RuntimeError)


class TaskPublishIssueArticlesTest(TestCase):
    """Testes para task_publish_issue_articles."""

    @patch("proc.tasks.get_total_status_data")
    @patch("proc.tasks.task_sync_issue")
    @patch("proc.tasks.task_publish_article")
    @patch("proc.tasks.WebSiteConfiguration")
    @patch("proc.tasks.fix_publication_status")
    @patch("proc.tasks.ArticleProc")
    @patch("proc.tasks.IssueProc")
    @patch("proc.tasks.TaskTracker")
    def test_happy_path_publishes_articles_and_schedules_sync(
        self,
        mock_task_tracker,
        mock_issue_proc,
        mock_article_proc,
        mock_fix_pub_status,
        mock_website_config,
        mock_publish_article,
        mock_task_sync_issue,
        mock_get_total_status_data,
    ):
        mock_tracker_instance = MagicMock()
        mock_task_tracker.create.return_value = mock_tracker_instance
        mock_get_total_status_data.return_value = {}

        mock_issue = MagicMock()
        mock_issue.collection = MagicMock()
        mock_issue_proc.objects.select_related.return_value.get.return_value = (
            mock_issue
        )

        mock_articles = MagicMock()
        mock_article_proc.objects.select_related.return_value.filter.return_value = (
            mock_articles
        )
        ids_qs = make_id_queryset([101, 102])
        mock_filtered = MagicMock()
        mock_filtered.values_list.return_value = ids_qs
        mock_articles.filter.return_value = mock_filtered

        website = MagicMock()
        website.id = 7
        website.purpose = "QA"
        website.get_data.return_value = {"post_data_url": "x"}
        mock_website_config.objects.filter.return_value = [website]

        task_publish_issue_articles(
            issue_proc_id=5, user_id=None, username=None, force_update=False
        )

        mock_fix_pub_status.assert_called_once_with(mock_issue.collection)
        self.assertEqual(mock_publish_article.call_count, 2)
        called_ids = [
            c.kwargs["article_proc_id"] for c in mock_publish_article.call_args_list
        ]
        self.assertEqual(called_ids, [101, 102])
        first_kwargs = mock_publish_article.call_args_list[0].kwargs
        self.assertEqual(first_kwargs["website_id"], 7)
        self.assertEqual(first_kwargs["website_kind"], "QA")
        self.assertEqual(first_kwargs["api_data"], {"post_data_url": "x"})
        self.assertFalse(first_kwargs["force_update"])

        mock_task_sync_issue.delay.assert_called_once()
        sync_kwargs = mock_task_sync_issue.delay.call_args.kwargs
        self.assertEqual(sync_kwargs["website_kind"], "QA")
        self.assertEqual(sync_kwargs["issue_proc_id"], 5)
        self.assertEqual(sync_kwargs["api_data"], {"post_data_url": "x"})

        self.assertEqual(mock_tracker_instance.total_processed, 2)
        mock_tracker_instance.finish.assert_called_once()

    @patch("proc.tasks.get_total_status_data")
    @patch("proc.tasks.task_sync_issue")
    @patch("proc.tasks.task_publish_article")
    @patch("proc.tasks.WebSiteConfiguration")
    @patch("proc.tasks.fix_publication_status")
    @patch("proc.tasks.ArticleProc")
    @patch("proc.tasks.IssueProc")
    @patch("proc.tasks.TaskTracker")
    def test_zero_enabled_website_configs_publishes_nothing(
        self,
        mock_task_tracker,
        mock_issue_proc,
        mock_article_proc,
        mock_fix_pub_status,
        mock_website_config,
        mock_publish_article,
        mock_task_sync_issue,
        mock_get_total_status_data,
    ):
        mock_get_total_status_data.return_value = {}
        mock_issue_proc.objects.select_related.return_value.get.return_value = (
            MagicMock()
        )
        mock_website_config.objects.filter.return_value = []

        task_publish_issue_articles(issue_proc_id=5)

        mock_publish_article.assert_not_called()
        mock_task_sync_issue.delay.assert_not_called()

    @patch("proc.tasks.get_total_status_data")
    @patch("proc.tasks.task_sync_issue")
    @patch("proc.tasks.task_publish_article")
    @patch("proc.tasks.WebSiteConfiguration")
    @patch("proc.tasks.fix_publication_status")
    @patch("proc.tasks.ArticleProc")
    @patch("proc.tasks.IssueProc")
    @patch("proc.tasks.TaskTracker")
    def test_per_article_exception_continues_and_sync_still_scheduled(
        self,
        mock_task_tracker,
        mock_issue_proc,
        mock_article_proc,
        mock_fix_pub_status,
        mock_website_config,
        mock_publish_article,
        mock_task_sync_issue,
        mock_get_total_status_data,
    ):
        mock_get_total_status_data.return_value = {}
        mock_issue_proc.objects.select_related.return_value.get.return_value = (
            MagicMock()
        )

        mock_articles = MagicMock()
        mock_article_proc.objects.select_related.return_value.filter.return_value = (
            mock_articles
        )
        ids_qs = make_id_queryset([101, 102])
        mock_filtered = MagicMock()
        mock_filtered.values_list.return_value = ids_qs
        mock_articles.filter.return_value = mock_filtered

        website = MagicMock(id=7, purpose="QA")
        website.get_data.return_value = {}
        mock_website_config.objects.filter.return_value = [website]
        mock_publish_article.side_effect = [RuntimeError("fail1"), None]

        task_publish_issue_articles(issue_proc_id=5)

        self.assertEqual(mock_publish_article.call_count, 2)
        mock_task_sync_issue.delay.assert_called_once()

    @patch("proc.tasks.get_total_status_data")
    @patch("proc.tasks.task_sync_issue")
    @patch("proc.tasks.task_publish_article")
    @patch("proc.tasks.WebSiteConfiguration")
    @patch("proc.tasks.fix_publication_status")
    @patch("proc.tasks.ArticleProc")
    @patch("proc.tasks.IssueProc")
    @patch("proc.tasks.TaskTracker")
    def test_multiple_website_configs_schedule_sync_once_each(
        self,
        mock_task_tracker,
        mock_issue_proc,
        mock_article_proc,
        mock_fix_pub_status,
        mock_website_config,
        mock_publish_article,
        mock_task_sync_issue,
        mock_get_total_status_data,
    ):
        mock_get_total_status_data.return_value = {}
        mock_issue_proc.objects.select_related.return_value.get.return_value = (
            MagicMock()
        )

        mock_articles = MagicMock()
        mock_article_proc.objects.select_related.return_value.filter.return_value = (
            mock_articles
        )
        mock_filtered = MagicMock()
        mock_filtered.values_list.side_effect = [
            make_id_queryset([101]),
            make_id_queryset([201]),
        ]
        mock_articles.filter.return_value = mock_filtered

        qa_website = MagicMock(id=1, purpose="QA")
        qa_website.get_data.return_value = {"kind": "qa"}
        public_website = MagicMock(id=2, purpose="PUBLIC")
        public_website.get_data.return_value = {"kind": "public"}
        mock_website_config.objects.filter.return_value = [qa_website, public_website]

        task_publish_issue_articles(issue_proc_id=5)

        self.assertEqual(mock_task_sync_issue.delay.call_count, 2)
        website_kinds = [
            c.kwargs["website_kind"] for c in mock_task_sync_issue.delay.call_args_list
        ]
        self.assertEqual(website_kinds, ["QA", "PUBLIC"])
        self.assertEqual(mock_publish_article.call_count, 2)

    @patch("proc.tasks.IssueProc")
    @patch("proc.tasks.TaskTracker")
    def test_outer_exception_calls_finish_with_exception(
        self, mock_task_tracker, mock_issue_proc
    ):
        mock_tracker_instance = MagicMock()
        mock_task_tracker.create.return_value = mock_tracker_instance
        mock_issue_proc.objects.select_related.return_value.get.side_effect = (
            RuntimeError("not found")
        )

        task_publish_issue_articles(issue_proc_id=999)

        finish_kwargs = mock_tracker_instance.finish.call_args.kwargs
        self.assertIsInstance(finish_kwargs["exception"], RuntimeError)


class TaskSyncIssueTest(TestCase):
    """Testes para task_sync_issue."""

    @patch("proc.tasks.sync_issue")
    @patch("proc.tasks.get_api_data")
    @patch("proc.tasks.IssueProc")
    def test_api_data_provided_skips_fetch(
        self, mock_issue_proc, mock_get_api_data, mock_sync_issue
    ):
        mock_issue = MagicMock()
        mock_event = MagicMock()
        mock_issue.start.return_value = mock_event
        mock_issue_proc.objects.get.return_value = mock_issue
        mock_sync_issue.return_value = {"synced": True}

        task_sync_issue(
            issue_proc_id=3, website_kind="QA", api_data={"already": "there"}
        )

        mock_get_api_data.assert_not_called()
        mock_sync_issue.assert_called_once_with(mock_issue, {"already": "there"})
        mock_event.finish.assert_called_once()
        finish_kwargs = mock_event.finish.call_args.kwargs
        self.assertTrue(finish_kwargs["completed"])
        self.assertEqual(finish_kwargs["detail"], {"synced": True})

    @patch("proc.tasks.sync_issue")
    @patch("proc.tasks.get_api_data")
    @patch("proc.tasks.IssueProc")
    def test_api_data_none_fetches_via_get_api_data(
        self, mock_issue_proc, mock_get_api_data, mock_sync_issue
    ):
        mock_issue = MagicMock()
        mock_issue.collection = MagicMock()
        mock_event = MagicMock()
        mock_issue.start.return_value = mock_event
        mock_issue_proc.objects.get.return_value = mock_issue
        mock_get_api_data.return_value = {"fetched": True}
        mock_sync_issue.return_value = {"synced": True}

        task_sync_issue(issue_proc_id=3, website_kind="PUBLIC", api_data=None)

        mock_get_api_data.assert_called_once_with(mock_issue.collection, "issue", "PUBLIC")
        mock_sync_issue.assert_called_once_with(mock_issue, {"fetched": True})

    @patch("proc.tasks.sync_issue")
    @patch("proc.tasks.get_api_data")
    @patch("proc.tasks.IssueProc")
    def test_exception_after_event_started_calls_event_finish(
        self, mock_issue_proc, mock_get_api_data, mock_sync_issue
    ):
        mock_issue = MagicMock()
        mock_event = MagicMock()
        mock_issue.start.return_value = mock_event
        mock_issue_proc.objects.get.return_value = mock_issue
        mock_sync_issue.side_effect = RuntimeError("sync failed")

        task_sync_issue(issue_proc_id=3, website_kind="QA", api_data={"x": 1})

        mock_event.finish.assert_called_once()
        finish_kwargs = mock_event.finish.call_args.kwargs
        self.assertFalse(finish_kwargs["completed"])
        self.assertIsInstance(finish_kwargs["exception"], RuntimeError)

    @patch("proc.tasks.UnexpectedEvent")
    @patch("proc.tasks.sync_issue")
    @patch("proc.tasks.get_api_data")
    @patch("proc.tasks.IssueProc")
    def test_fallback_to_unexpected_event_when_event_undefined(
        self,
        mock_issue_proc,
        mock_get_api_data,
        mock_sync_issue,
        mock_unexpected_event,
    ):
        mock_issue_proc.objects.get.side_effect = RuntimeError("db down")

        task_sync_issue(issue_proc_id=3, website_kind="QA")

        mock_sync_issue.assert_not_called()
        mock_unexpected_event.create.assert_called_once()
        create_kwargs = mock_unexpected_event.create.call_args.kwargs
        self.assertIsInstance(create_kwargs["e"], RuntimeError)
        self.assertEqual(create_kwargs["detail"]["issue_proc_id"], 3)


class TaskPublishArticlesTest(TestCase):
    """Testes para task_publish_articles."""

    @patch("proc.tasks.task_publish_issue_articles")
    @patch("proc.tasks.IssueProc")
    @patch("proc.tasks.fix_publication_status")
    @patch("proc.tasks.Collection")
    def test_happy_path_schedules_publish_per_issue(
        self, mock_collection, mock_fix_pub_status, mock_issue_proc, mock_publish_issue_articles
    ):
        coll = MagicMock()
        mock_collection.objects.filter.return_value.iterator.return_value = iter(
            [coll]
        )

        issue1 = MagicMock(id=1)
        issue2 = MagicMock(id=2)
        mock_qs = make_id_queryset([issue1, issue2])
        mock_issue_proc.select_items.return_value = mock_qs

        task_publish_articles(collection_acron="scl", journal_acron="abc")

        mock_collection.objects.filter.assert_called_once_with(acron="scl")
        mock_fix_pub_status.assert_called_once_with(coll)
        mock_issue_proc.select_items.assert_called_once_with(
            collection_acron="scl",
            journal_acron="abc",
            issue_folder=None,
            publication_year=None,
            issue_proc_id=None,
        )
        self.assertEqual(mock_publish_issue_articles.delay.call_count, 2)
        ids = [
            c.kwargs["issue_proc_id"]
            for c in mock_publish_issue_articles.delay.call_args_list
        ]
        self.assertEqual(ids, [1, 2])
        first_kwargs = mock_publish_issue_articles.delay.call_args_list[0].kwargs
        self.assertIsNone(first_kwargs["status"])
        self.assertFalse(first_kwargs["force_update"])

    @patch("proc.tasks.task_publish_issue_articles")
    @patch("proc.tasks.IssueProc")
    @patch("proc.tasks.fix_publication_status")
    @patch("proc.tasks.Collection")
    def test_fix_publication_status_called_per_collection_but_select_items_called_once(
        self, mock_collection, mock_fix_pub_status, mock_issue_proc, mock_publish_issue_articles
    ):
        coll1, coll2 = MagicMock(), MagicMock()
        mock_collection.objects.iterator.return_value = iter([coll1, coll2])
        mock_issue_proc.select_items.return_value = make_id_queryset([])

        task_publish_articles(collection_acron=None)

        self.assertEqual(mock_fix_pub_status.call_count, 2)
        mock_fix_pub_status.assert_has_calls([call(coll1), call(coll2)])
        mock_issue_proc.select_items.assert_called_once()
        mock_publish_issue_articles.delay.assert_not_called()

    @patch("proc.tasks.UnexpectedEvent")
    @patch("proc.tasks.task_publish_issue_articles")
    @patch("proc.tasks.IssueProc")
    @patch("proc.tasks.fix_publication_status")
    @patch("proc.tasks.Collection")
    def test_exception_path_calls_unexpected_event_create(
        self,
        mock_collection,
        mock_fix_pub_status,
        mock_issue_proc,
        mock_publish_issue_articles,
        mock_unexpected_event,
    ):
        mock_collection.objects.filter.return_value.iterator.return_value = iter(
            [MagicMock()]
        )
        mock_issue_proc.select_items.side_effect = RuntimeError("boom")

        task_publish_articles(collection_acron="scl")

        mock_publish_issue_articles.delay.assert_not_called()
        mock_unexpected_event.create.assert_called_once()
        create_kwargs = mock_unexpected_event.create.call_args.kwargs
        self.assertIsInstance(create_kwargs["e"], RuntimeError)


class TaskPublishArticleTest(TestCase):
    """Testes para task_publish_article."""

    @patch("proc.tasks.UnexpectedEvent")
    @patch("proc.tasks.task_check_article_webpages")
    @patch("proc.tasks.ArticleProc")
    def test_published_true_schedules_check_article_webpages(
        self, mock_article_proc, mock_check_webpages, mock_unexpected_event
    ):
        mock_article = MagicMock()
        mock_article.id = 55
        mock_article_proc_instance = MagicMock()
        mock_article_proc_instance.collection.id = 3
        mock_article_proc_instance.article = mock_article
        mock_event = MagicMock()
        mock_article_proc_instance.start.return_value = mock_event
        mock_article_proc_instance.publish.return_value = {"completed": True}
        mock_article_proc.objects.get.return_value = mock_article_proc_instance

        task_publish_article(article_proc_id=42, website_kind="QA", api_data={"x": 1})

        mock_check_webpages.delay.assert_called_once()
        kwargs = mock_check_webpages.delay.call_args.kwargs
        self.assertEqual(kwargs["article_id"], 55)
        self.assertEqual(kwargs["collection_id"], 3)
        self.assertEqual(kwargs["article_proc_id"], 42)
        self.assertEqual(kwargs["website_kind"], "QA")
        mock_event.finish.assert_called_once()
        finish_kwargs = mock_event.finish.call_args.kwargs
        self.assertTrue(finish_kwargs["completed"])
        self.assertTrue(finish_kwargs["detail"]["published"])
        mock_unexpected_event.create.assert_not_called()

    @patch("proc.tasks.UnexpectedEvent")
    @patch("proc.tasks.task_check_article_webpages")
    @patch("proc.tasks.ArticleProc")
    def test_published_false_does_not_schedule_check_article_webpages(
        self, mock_article_proc, mock_check_webpages, mock_unexpected_event
    ):
        mock_article_proc_instance = MagicMock()
        mock_event = MagicMock()
        mock_article_proc_instance.start.return_value = mock_event
        mock_article_proc_instance.publish.return_value = {"completed": False}
        mock_article_proc.objects.get.return_value = mock_article_proc_instance

        task_publish_article(article_proc_id=42, website_kind="QA")

        mock_check_webpages.delay.assert_not_called()
        mock_event.finish.assert_called_once()
        finish_kwargs = mock_event.finish.call_args.kwargs
        self.assertFalse(finish_kwargs["detail"]["published"])

    @patch("proc.tasks.UnexpectedEvent")
    @patch("proc.tasks.task_check_article_webpages")
    @patch("proc.tasks.ArticleProc")
    def test_fallback_to_unexpected_event_when_article_proc_lookup_fails(
        self, mock_article_proc, mock_check_webpages, mock_unexpected_event
    ):
        mock_article_proc.objects.get.side_effect = RuntimeError("db down")

        task_publish_article(article_proc_id=42, website_kind="QA")

        mock_check_webpages.delay.assert_not_called()
        mock_unexpected_event.create.assert_called_once()
        create_kwargs = mock_unexpected_event.create.call_args.kwargs
        self.assertIsInstance(create_kwargs["e"], RuntimeError)
        self.assertIsNone(create_kwargs["detail"]["pid"])
        self.assertEqual(create_kwargs["detail"]["article_proc_id"], 42)

    @patch("proc.tasks.UnexpectedEvent")
    @patch("proc.tasks.task_check_article_webpages")
    @patch("proc.tasks.ArticleProc")
    def test_fallback_when_event_exists_but_user_is_none(
        self, mock_article_proc, mock_check_webpages, mock_unexpected_event
    ):
        # sem user_id/username, _get_user retorna None: mesmo com event
        # criado, a condição `if event and user` é falsa e cai no fallback.
        mock_article_proc_instance = MagicMock()
        mock_event = MagicMock()
        mock_article_proc_instance.start.return_value = mock_event
        mock_article_proc_instance.publish.side_effect = RuntimeError("publish failed")
        mock_article_proc_instance.pid = "S1234-56782020000100001"
        mock_article_proc.objects.get.return_value = mock_article_proc_instance

        task_publish_article(article_proc_id=42, website_kind="QA")

        mock_check_webpages.delay.assert_not_called()
        mock_event.finish.assert_not_called()
        mock_unexpected_event.create.assert_called_once()
        create_kwargs = mock_unexpected_event.create.call_args.kwargs
        self.assertEqual(create_kwargs["detail"]["pid"], "S1234-56782020000100001")

    @patch("proc.tasks.UnexpectedEvent")
    @patch("proc.tasks.task_check_article_webpages")
    @patch("proc.tasks.ArticleProc")
    @patch("proc.tasks._get_user")
    def test_event_finish_called_with_exception_when_user_present(
        self, mock_get_user, mock_article_proc, mock_check_webpages, mock_unexpected_event
    ):
        mock_user = MagicMock()
        mock_get_user.return_value = mock_user

        mock_article_proc_instance = MagicMock()
        mock_event = MagicMock()
        mock_article_proc_instance.start.return_value = mock_event
        mock_article_proc_instance.publish.side_effect = RuntimeError("publish failed")
        mock_article_proc.objects.get.return_value = mock_article_proc_instance

        task_publish_article(user_id=1, article_proc_id=42, website_kind="QA")

        mock_event.finish.assert_called_once()
        finish_args = mock_event.finish.call_args.args
        finish_kwargs = mock_event.finish.call_args.kwargs
        self.assertEqual(finish_args[0], mock_user)
        self.assertIsInstance(finish_kwargs["exception"], RuntimeError)
        mock_unexpected_event.create.assert_not_called()
        mock_check_webpages.delay.assert_not_called()
