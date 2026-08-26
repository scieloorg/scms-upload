import unittest
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.test import TestCase

from migration import choices as migration_choices
from tracker import choices as tracker_choices
from proc import tasks

User = get_user_model()


class NothingToProcessTest(unittest.TestCase):
    """Testes triviais para a exceção NothingToProcess."""

    def test_is_exception_subclass(self):
        self.assertTrue(issubclass(tasks.NothingToProcess, Exception))


class TaskExecutionInitTest(TestCase):
    """Testes para TaskExecution.__init__."""

    @patch("proc.tasks.TaskTracker")
    def test_init_creates_task_tracker_and_sets_defaults(self, mock_tracker_cls):
        mock_tracker = MagicMock()
        mock_tracker_cls.create.return_value = mock_tracker

        task_exec = tasks.TaskExecution(name="task", item="item1", params={"a": 1})

        mock_tracker_cls.create.assert_called_once_with(name="task", item="item1")
        self.assertEqual(task_exec.task_tracker, mock_tracker)
        self.assertEqual(task_exec.params, {"a": 1})
        self.assertEqual(task_exec.events, [])
        self.assertEqual(task_exec.stats, {})
        self.assertEqual(task_exec.exceptions, [])
        self.assertIsNone(task_exec.journal_proc_id)
        self.assertEqual(task_exec.status_changes, {})


class TaskExecutionPropertiesTest(TestCase):
    """Testes para as propriedades item/total_to_process/total_processed (passthrough)."""

    @patch("proc.tasks.TaskTracker")
    def test_item_getter_and_setter_delegate_to_task_tracker(self, mock_tracker_cls):
        mock_tracker = MagicMock()
        mock_tracker_cls.create.return_value = mock_tracker
        task_exec = tasks.TaskExecution(name="n", item="i", params={})

        mock_tracker.item = "original"
        self.assertEqual(task_exec.item, "original")

        task_exec.item = "changed"
        self.assertEqual(mock_tracker.item, "changed")

    @patch("proc.tasks.TaskTracker")
    def test_total_to_process_getter_and_setter_delegate_to_task_tracker(self, mock_tracker_cls):
        mock_tracker = MagicMock()
        mock_tracker_cls.create.return_value = mock_tracker
        task_exec = tasks.TaskExecution(name="n", item="i", params={})

        mock_tracker.total_to_process = 3
        self.assertEqual(task_exec.total_to_process, 3)

        task_exec.total_to_process = 10
        self.assertEqual(mock_tracker.total_to_process, 10)

    @patch("proc.tasks.TaskTracker")
    def test_total_processed_getter_and_setter_delegate_to_task_tracker(self, mock_tracker_cls):
        mock_tracker = MagicMock()
        mock_tracker_cls.create.return_value = mock_tracker
        task_exec = tasks.TaskExecution(name="n", item="i", params={})

        mock_tracker.total_processed = 1
        self.assertEqual(task_exec.total_processed, 1)

        task_exec.total_processed = 5
        self.assertEqual(mock_tracker.total_processed, 5)


class TaskExecutionAddExceptionTest(TestCase):
    """Testes para TaskExecution.add_exception."""

    @patch("proc.tasks.TaskTracker")
    def test_add_exception_appends_type_and_message(self, mock_tracker_cls):
        mock_tracker_cls.create.return_value = MagicMock()
        task_exec = tasks.TaskExecution(name="n", item="i", params={})

        try:
            raise ValueError("boom")
        except ValueError as e:
            task_exec.add_exception(e)

        self.assertEqual(len(task_exec.exceptions), 1)
        self.assertEqual(task_exec.exceptions[0]["message"], "boom")
        self.assertIn("ValueError", task_exec.exceptions[0]["type"])


class TaskExecutionAddEventTest(TestCase):
    """Testes para TaskExecution.add_event (evento único e lista)."""

    @patch("proc.tasks.TaskTracker")
    def test_add_event_appends_single_event(self, mock_tracker_cls):
        mock_tracker_cls.create.return_value = MagicMock()
        task_exec = tasks.TaskExecution(name="n", item="i", params={})

        task_exec.add_event({"a": 1})

        self.assertEqual(task_exec.events, [{"a": 1}])

    @patch("proc.tasks.TaskTracker")
    def test_add_event_extends_with_list(self, mock_tracker_cls):
        mock_tracker_cls.create.return_value = MagicMock()
        task_exec = tasks.TaskExecution(name="n", item="i", params={})

        task_exec.add_event([{"a": 1}, {"b": 2}])

        self.assertEqual(task_exec.events, [{"a": 1}, {"b": 2}])

    @patch("proc.tasks.TaskTracker")
    def test_add_event_mixes_single_and_list_calls(self, mock_tracker_cls):
        mock_tracker_cls.create.return_value = MagicMock()
        task_exec = tasks.TaskExecution(name="n", item="i", params={})

        task_exec.add_event({"a": 1})
        task_exec.add_event([{"b": 2}, {"c": 3}])

        self.assertEqual(task_exec.events, [{"a": 1}, {"b": 2}, {"c": 3}])


class TaskExecutionAddNumberTest(TestCase):
    """Testes para TaskExecution.add_number."""

    @patch("proc.tasks.TaskTracker")
    def test_add_number_sets_stats_key(self, mock_tracker_cls):
        mock_tracker_cls.create.return_value = MagicMock()
        task_exec = tasks.TaskExecution(name="n", item="i", params={})

        task_exec.add_number("total", 5)

        self.assertEqual(task_exec.stats["total"], 5)


class TaskExecutionFinishTest(TestCase):
    """Testes para TaskExecution.finish: completed flag, fallback JSON e erro interno."""

    @patch("proc.tasks.TaskTracker")
    def test_completed_true_when_no_exception_no_traceback_no_exceptions(self, mock_tracker_cls):
        mock_tracker = MagicMock()
        mock_tracker.total_to_process = 10
        mock_tracker.total_processed = 10
        mock_tracker_cls.create.return_value = mock_tracker
        task_exec = tasks.TaskExecution(name="n", item="i", params={})

        task_exec.finish()

        kwargs = mock_tracker.finish.call_args.kwargs
        self.assertTrue(kwargs["completed"])
        self.assertIsNone(kwargs["exception"])
        self.assertIsNone(kwargs["exc_traceback"])

    @patch("proc.tasks.TaskTracker")
    def test_completed_false_when_exception_given(self, mock_tracker_cls):
        mock_tracker = MagicMock()
        mock_tracker.total_to_process = 0
        mock_tracker.total_processed = 0
        mock_tracker_cls.create.return_value = mock_tracker
        task_exec = tasks.TaskExecution(name="n", item="i", params={})

        task_exec.finish(exception=ValueError("x"))

        self.assertFalse(mock_tracker.finish.call_args.kwargs["completed"])

    @patch("proc.tasks.TaskTracker")
    def test_completed_false_when_exc_traceback_given(self, mock_tracker_cls):
        mock_tracker = MagicMock()
        mock_tracker.total_to_process = 0
        mock_tracker.total_processed = 0
        mock_tracker_cls.create.return_value = mock_tracker
        task_exec = tasks.TaskExecution(name="n", item="i", params={})

        try:
            raise ValueError("boom")
        except ValueError:
            import sys
            _, _, tb = sys.exc_info()
            task_exec.finish(exc_traceback=tb)

        self.assertFalse(mock_tracker.finish.call_args.kwargs["completed"])

    @patch("proc.tasks.TaskTracker")
    def test_completed_false_when_self_exceptions_present(self, mock_tracker_cls):
        mock_tracker = MagicMock()
        mock_tracker.total_to_process = 0
        mock_tracker.total_processed = 0
        mock_tracker_cls.create.return_value = mock_tracker
        task_exec = tasks.TaskExecution(name="n", item="i", params={})
        task_exec.add_exception(ValueError("previous failure"))

        task_exec.finish()

        self.assertFalse(mock_tracker.finish.call_args.kwargs["completed"])

    @patch("proc.tasks.TaskTracker")
    def test_stats_totals_are_populated_from_task_tracker(self, mock_tracker_cls):
        mock_tracker = MagicMock()
        mock_tracker.total_to_process = 7
        mock_tracker.total_processed = 3
        mock_tracker_cls.create.return_value = mock_tracker
        task_exec = tasks.TaskExecution(name="n", item="i", params={})

        task_exec.finish()

        detail = mock_tracker.finish.call_args.kwargs["detail"]
        self.assertEqual(detail["stats"]["total_to_process"], 7)
        self.assertEqual(detail["stats"]["total_processed"], 3)

    @patch("proc.tasks.TaskTracker")
    def test_falls_back_to_str_for_non_json_serializable_params(self, mock_tracker_cls):
        mock_tracker = MagicMock()
        mock_tracker.total_to_process = 0
        mock_tracker.total_processed = 0
        mock_tracker_cls.create.return_value = mock_tracker
        non_serializable = {"bad": ValueError("cannot serialize me")}
        task_exec = tasks.TaskExecution(name="n", item="i", params=non_serializable)

        task_exec.finish()

        detail = mock_tracker.finish.call_args.kwargs["detail"]
        # params could not be json-serialized as a whole, so it was stringified
        self.assertIsInstance(detail["params"], str)
        # the remaining, serializable fields are preserved as-is
        self.assertEqual(detail["stats"], {"total_to_process": 0, "total_processed": 0})
        self.assertEqual(detail["events"], [])
        self.assertEqual(detail["exceptions"], [])
        self.assertEqual(detail["status_changes"], {})

    @patch("proc.tasks.TaskTracker")
    def test_falls_back_to_str_for_non_serializable_set_value(self, mock_tracker_cls):
        mock_tracker = MagicMock()
        mock_tracker.total_to_process = 0
        mock_tracker.total_processed = 0
        mock_tracker_cls.create.return_value = mock_tracker
        task_exec = tasks.TaskExecution(name="n", item="i", params={"bad": {1, 2, 3}})

        task_exec.finish()

        detail = mock_tracker.finish.call_args.kwargs["detail"]
        self.assertIsInstance(detail["params"], str)
        self.assertIn("1", detail["params"])

    @patch("proc.tasks.UnexpectedEvent")
    @patch("proc.tasks.TaskTracker")
    def test_calls_unexpected_event_create_when_task_tracker_finish_raises(
        self, mock_tracker_cls, mock_unexpected_event
    ):
        mock_tracker = MagicMock()
        mock_tracker.total_to_process = 0
        mock_tracker.total_processed = 0
        mock_tracker.item = "item-x"
        mock_tracker.finish.side_effect = Exception("db unavailable")
        mock_tracker_cls.create.return_value = mock_tracker
        task_exec = tasks.TaskExecution(name="n", item="item-x", params={})

        task_exec.finish()

        mock_unexpected_event.create.assert_called_once()
        kwargs = mock_unexpected_event.create.call_args.kwargs
        self.assertEqual(kwargs["detail"]["task"], "proc.tasks.TaskExecution.finish")
        self.assertEqual(kwargs["detail"]["item"], "item-x")


class TaskExecutionUpdateTotalStatusTest(TestCase):
    """Testes para TaskExecution.update_total_status."""

    @patch("proc.tasks.get_total_status_data")
    @patch("proc.tasks.TaskTracker")
    def test_builds_previous_from_status_changes_history_and_appends(
        self, mock_tracker_cls, mock_get_total_status_data
    ):
        mock_tracker_cls.create.return_value = MagicMock()
        task_exec = tasks.TaskExecution(name="n", item="i", params={})
        task_exec.journal_proc_id = 42

        mock_get_total_status_data.return_value = {
            "journal": ["TODO"],
            "issue": ["DONE"],
        }
        task_exec.update_total_status("Start", issue_proc_id=7)

        mock_get_total_status_data.assert_called_once_with({}, 42, 7)
        self.assertEqual(
            task_exec.status_changes["journal"],
            [{"label": "Start", "total_status": ["TODO"]}],
        )
        self.assertEqual(
            task_exec.status_changes["issue"],
            [{"label": "Start", "total_status": ["DONE"]}],
        )

        mock_get_total_status_data.return_value = {
            "journal": ["DONE"],
            "issue": ["DONE"],
        }
        task_exec.update_total_status("Next", issue_proc_id=7)

        mock_get_total_status_data.assert_called_with(
            {"journal": ["TODO"], "issue": ["DONE"]}, 42, 7
        )
        self.assertEqual(len(task_exec.status_changes["journal"]), 2)
        self.assertEqual(
            task_exec.status_changes["journal"][1],
            {"label": "Next", "total_status": ["DONE"]},
        )

    @patch("proc.tasks.get_total_status_data")
    @patch("proc.tasks.TaskTracker")
    def test_previous_defaults_to_empty_list_when_history_entry_is_malformed(
        self, mock_tracker_cls, mock_get_total_status_data
    ):
        mock_tracker_cls.create.return_value = MagicMock()
        task_exec = tasks.TaskExecution(name="n", item="i", params={})
        # entrada de histórico existente porém vazia -> items[-1] dispara IndexError
        task_exec.status_changes = {"journal": []}
        mock_get_total_status_data.return_value = {"journal": ["X"]}

        task_exec.update_total_status("Label")

        mock_get_total_status_data.assert_called_once_with({"journal": []}, None, None)


class GetUserTest(TestCase):
    """Testes para o helper _get_user."""

    @patch("proc.tasks.User")
    def test_returns_user_by_id_when_user_id_truthy(self, mock_user):
        mock_user.objects.get.return_value = "USER_BY_ID"

        result = tasks._get_user(user_id=1, username="ignored")

        mock_user.objects.get.assert_called_once_with(pk=1)
        self.assertEqual(result, "USER_BY_ID")

    @patch("proc.tasks.User")
    def test_returns_user_by_username_when_user_id_falsy(self, mock_user):
        mock_user.objects.get.return_value = "USER_BY_USERNAME"

        result = tasks._get_user(user_id=None, username="bob")

        mock_user.objects.get.assert_called_once_with(username="bob")
        self.assertEqual(result, "USER_BY_USERNAME")

    def test_returns_none_when_both_falsy(self):
        result = tasks._get_user(user_id=None, username=None)

        self.assertIsNone(result)

    @patch("proc.tasks.UnexpectedEvent")
    @patch("proc.tasks.User")
    def test_returns_none_and_creates_unexpected_event_on_exception(
        self, mock_user, mock_unexpected_event
    ):
        mock_user.objects.get.side_effect = Exception("db down")

        result = tasks._get_user(user_id=5, username=None)

        self.assertIsNone(result)
        mock_unexpected_event.create.assert_called_once()
        kwargs = mock_unexpected_event.create.call_args.kwargs
        self.assertEqual(
            kwargs["detail"],
            {"task": "proc.tasks._get_user", "user_id": 5, "username": None},
        )


class GetCollectionsTest(TestCase):
    """Testes para o helper _get_collections."""

    @patch("proc.tasks.Collection")
    def test_filters_by_acron_when_given(self, mock_collection):
        mock_qs = MagicMock()
        mock_collection.objects.filter.return_value = mock_qs

        result = tasks._get_collections("scl")

        mock_collection.objects.filter.assert_called_once_with(acron="scl")
        mock_qs.iterator.assert_called_once()
        self.assertEqual(result, mock_qs.iterator.return_value)

    @patch("proc.tasks.Collection")
    def test_returns_all_when_acron_not_given(self, mock_collection):
        mock_collection.objects.iterator.return_value = "ALL_ITER"

        result = tasks._get_collections(None)

        mock_collection.objects.filter.assert_not_called()
        mock_collection.objects.iterator.assert_called_once()
        self.assertEqual(result, "ALL_ITER")

    @patch("proc.tasks.UnexpectedEvent")
    @patch("proc.tasks.Collection")
    def test_returns_empty_list_and_creates_unexpected_event_on_exception(
        self, mock_collection, mock_unexpected_event
    ):
        mock_collection.objects.iterator.side_effect = Exception("boom")

        result = tasks._get_collections(None)

        self.assertEqual(result, [])
        mock_unexpected_event.create.assert_called_once()
        kwargs = mock_unexpected_event.create.call_args.kwargs
        self.assertEqual(kwargs["detail"]["task"], "proc.tasks._get_collections")


class FixPublicationStatusTest(TestCase):
    """Testes para fix_publication_status: TODO <-> IGNORED conforme WebSiteConfiguration."""

    @patch("proc.tasks.ArticleProc")
    @patch("proc.tasks.IssueProc")
    @patch("proc.tasks.JournalProc")
    @patch("proc.tasks.WebSiteConfiguration")
    def test_qa_enabled_public_disabled(
        self, mock_wsc, mock_journal_proc, mock_issue_proc, mock_article_proc
    ):
        mock_wsc.objects.filter.return_value.values_list.return_value = ["QA"]
        collection = MagicMock()

        tasks.fix_publication_status(collection)

        mock_wsc.objects.filter.assert_called_once_with(
            collection=collection, enabled=True
        )
        mock_wsc.objects.filter.return_value.values_list.assert_called_once_with(
            "purpose", flat=True
        )

        for mock_model in (mock_journal_proc, mock_issue_proc, mock_article_proc):
            # QA habilitado: IGNORED -> TODO
            mock_model.objects.filter.assert_any_call(
                collection=collection,
                qa_ws_status=tracker_choices.PROGRESS_STATUS_IGNORED,
            )
            # PUBLIC desabilitado: TODO -> IGNORED
            mock_model.objects.filter.assert_any_call(
                collection=collection,
                public_ws_status=tracker_choices.PROGRESS_STATUS_TODO,
            )
            mock_model.objects.filter.return_value.update.assert_any_call(
                qa_ws_status=tracker_choices.PROGRESS_STATUS_TODO
            )
            mock_model.objects.filter.return_value.update.assert_any_call(
                public_ws_status=tracker_choices.PROGRESS_STATUS_IGNORED
            )

    @patch("proc.tasks.ArticleProc")
    @patch("proc.tasks.IssueProc")
    @patch("proc.tasks.JournalProc")
    @patch("proc.tasks.WebSiteConfiguration")
    def test_both_disabled(
        self, mock_wsc, mock_journal_proc, mock_issue_proc, mock_article_proc
    ):
        mock_wsc.objects.filter.return_value.values_list.return_value = []
        collection = MagicMock()

        tasks.fix_publication_status(collection)

        for mock_model in (mock_journal_proc, mock_issue_proc, mock_article_proc):
            mock_model.objects.filter.assert_any_call(
                collection=collection,
                qa_ws_status=tracker_choices.PROGRESS_STATUS_TODO,
            )
            mock_model.objects.filter.assert_any_call(
                collection=collection,
                public_ws_status=tracker_choices.PROGRESS_STATUS_TODO,
            )
            mock_model.objects.filter.return_value.update.assert_any_call(
                qa_ws_status=tracker_choices.PROGRESS_STATUS_IGNORED
            )
            mock_model.objects.filter.return_value.update.assert_any_call(
                public_ws_status=tracker_choices.PROGRESS_STATUS_IGNORED
            )

    @patch("proc.tasks.ArticleProc")
    @patch("proc.tasks.IssueProc")
    @patch("proc.tasks.JournalProc")
    @patch("proc.tasks.WebSiteConfiguration")
    def test_both_enabled(
        self, mock_wsc, mock_journal_proc, mock_issue_proc, mock_article_proc
    ):
        mock_wsc.objects.filter.return_value.values_list.return_value = ["QA", "PUBLIC"]
        collection = MagicMock()

        tasks.fix_publication_status(collection)

        for mock_model in (mock_journal_proc, mock_issue_proc, mock_article_proc):
            mock_model.objects.filter.assert_any_call(
                collection=collection,
                qa_ws_status=tracker_choices.PROGRESS_STATUS_IGNORED,
            )
            mock_model.objects.filter.assert_any_call(
                collection=collection,
                public_ws_status=tracker_choices.PROGRESS_STATUS_IGNORED,
            )
            mock_model.objects.filter.return_value.update.assert_any_call(
                qa_ws_status=tracker_choices.PROGRESS_STATUS_TODO
            )
            mock_model.objects.filter.return_value.update.assert_any_call(
                public_ws_status=tracker_choices.PROGRESS_STATUS_TODO
            )


class TaskFetchAndCreateJournalTest(TestCase):
    """Testes para task_fetch_and_create_journal."""

    @patch("proc.tasks.TaskExecution")
    @patch("proc.tasks.fetch_and_create_journal")
    @patch("proc.tasks._get_user")
    def test_happy_path_fetches_and_finishes(
        self, mock_get_user, mock_fetch, mock_task_exec_cls
    ):
        mock_get_user.return_value = "USER"
        mock_task_exec = MagicMock()
        mock_task_exec_cls.return_value = mock_task_exec

        tasks.task_fetch_and_create_journal(
            user_id=1,
            username="bob",
            collection_acron="scl",
            issn_electronic="1234-5678",
            issn_print="8765-4321",
            force_update=True,
        )

        mock_get_user.assert_called_once_with(user_id=1, username="bob")
        mock_fetch.assert_called_once_with(
            "USER",
            collection_acron="scl",
            issn_electronic="1234-5678",
            issn_print="8765-4321",
            force_update=True,
        )
        mock_task_exec.finish.assert_called_once_with()

    @patch("proc.tasks.TaskExecution")
    @patch("proc.tasks.fetch_and_create_journal")
    @patch("proc.tasks._get_user")
    def test_exception_calls_finish_with_exception(
        self, mock_get_user, mock_fetch, mock_task_exec_cls
    ):
        mock_get_user.return_value = "USER"
        mock_task_exec = MagicMock()
        mock_task_exec_cls.return_value = mock_task_exec
        mock_fetch.side_effect = ValueError("boom")

        tasks.task_fetch_and_create_journal(user_id=1, username="bob")

        kwargs = mock_task_exec.finish.call_args.kwargs
        self.assertIsInstance(kwargs["exception"], ValueError)
        self.assertIsNotNone(kwargs["exc_traceback"])


class TaskExcludeInvalidIssueArticlesTest(TestCase):
    """Testes para task_exclude_invalid_issue_articles (não usa TaskExecution)."""

    @patch("proc.tasks.Article")
    @patch("proc.tasks.ArticleProc")
    @patch("proc.tasks.IssueProc")
    @patch("proc.tasks._get_user")
    def test_happy_path_without_deleted_sps_pkg_ids_calls_exclude_invalid_items_once(
        self, mock_get_user, mock_issue_proc, mock_article_proc, mock_article
    ):
        mock_get_user.return_value = "USER"
        mock_issue = MagicMock()
        mock_issue_proc_instance = MagicMock(issue=mock_issue)
        mock_issue_proc.objects.select_related.return_value.get.return_value = (
            mock_issue_proc_instance
        )
        mock_article_proc.exclude_invalid_items.return_value = {
            "sps_pkg_id_list": [1, 2]
        }
        mock_article.exclude_invalid_records.return_value = {
            "deleted_sps_pkg_ids": []
        }

        result = tasks.task_exclude_invalid_issue_articles(
            issue_proc_id=10, username="bob", user_id=None, public_api_data={"x": 1}
        )

        mock_issue_proc.objects.select_related.assert_called_once_with("issue")
        mock_issue_proc.objects.select_related.return_value.get.assert_called_once_with(
            id=10
        )
        mock_article_proc.exclude_invalid_items.assert_called_once_with(
            "USER", mock_issue
        )
        mock_article.exclude_invalid_records.assert_called_once_with(
            "USER", mock_issue, [1, 2], timeout=None
        )
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["operation"], "ArticleProc.exclude_invalid_items")
        self.assertEqual(result[1]["operation"], "Article.exclude_invalid_records")

    @patch("proc.tasks.Article")
    @patch("proc.tasks.ArticleProc")
    @patch("proc.tasks.IssueProc")
    @patch("proc.tasks._get_user")
    def test_reruns_exclude_invalid_items_when_deleted_sps_pkg_ids_present(
        self, mock_get_user, mock_issue_proc, mock_article_proc, mock_article
    ):
        mock_get_user.return_value = "USER"
        mock_issue = MagicMock()
        mock_issue_proc.objects.select_related.return_value.get.return_value = (
            MagicMock(issue=mock_issue)
        )
        mock_article_proc.exclude_invalid_items.side_effect = [
            {"sps_pkg_id_list": [1]},
            {"sps_pkg_id_list": []},
        ]
        mock_article.exclude_invalid_records.return_value = {
            "deleted_sps_pkg_ids": [99]
        }

        result = tasks.task_exclude_invalid_issue_articles(issue_proc_id=10)

        self.assertEqual(mock_article_proc.exclude_invalid_items.call_count, 2)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[2]["operation"], "ArticleProc.exclude_invalid_items")

    @patch("proc.tasks.UnexpectedEvent")
    @patch("proc.tasks.IssueProc")
    @patch("proc.tasks._get_user")
    def test_exception_returns_error_dict_without_creating_unexpected_event(
        self, mock_get_user, mock_issue_proc, mock_unexpected_event
    ):
        mock_get_user.return_value = "USER"
        mock_issue_proc.objects.select_related.return_value.get.side_effect = Exception(
            "db error"
        )

        result = tasks.task_exclude_invalid_issue_articles(issue_proc_id=10)

        self.assertIn("exc_type", result)
        self.assertIn("exc_value", result)
        self.assertIn("traceback", result)
        mock_unexpected_event.create.assert_not_called()


class TaskRemoveDuplicateIssuesTest(TestCase):
    """Testes para task_remove_duplicate_issues e seu isolamento de erros em 3 níveis."""

    @patch("proc.tasks.TaskExecution")
    @patch("proc.tasks.IssueProc")
    @patch("proc.tasks.Article")
    @patch("proc.tasks.Issue")
    @patch("proc.tasks.Journal")
    @patch("proc.tasks._get_user")
    def test_happy_path_keeps_most_recent_and_redirects_others(
        self,
        mock_get_user,
        mock_journal,
        mock_issue,
        mock_article,
        mock_issue_proc,
        mock_task_exec_cls,
    ):
        mock_get_user.return_value = "USER"
        mock_journal.objects.get.return_value = "JOURNAL"
        mock_task_exec = MagicMock()
        mock_task_exec_cls.return_value = mock_task_exec

        duplicated_data = {
            "journal": "JOURNAL",
            "volume": "1",
            "number": "1",
            "supplement": None,
        }
        mock_duplicates_qs = MagicMock()
        mock_duplicates_qs.count.return_value = 1
        mock_duplicates_qs.iterator.return_value = [duplicated_data]
        mock_issue.get_duplicates.return_value = mock_duplicates_qs

        keep_issue = MagicMock(id=1)
        dup_issue = MagicMock(id=2)
        mock_issue.objects.filter.return_value.order_by.return_value = [
            keep_issue,
            dup_issue,
        ]

        tasks.task_remove_duplicate_issues(user_id=1, username="bob", journal_id=99)

        mock_journal.objects.get.assert_called_once_with(id=99)
        mock_issue.get_duplicates.assert_called_once_with("JOURNAL")
        mock_issue.objects.filter.assert_called_once_with(**duplicated_data)
        mock_article.objects.filter.assert_called_once_with(issue=dup_issue)
        mock_article.objects.filter.return_value.update.assert_called_once_with(
            issue=keep_issue
        )
        mock_issue_proc.objects.filter.assert_called_once_with(issue=dup_issue)
        mock_issue_proc.objects.filter.return_value.update.assert_called_once_with(
            issue=keep_issue
        )
        dup_issue.delete.assert_called_once()
        keep_issue.delete.assert_not_called()
        mock_task_exec.finish.assert_called_once_with()

    @patch("proc.tasks.TaskExecution")
    @patch("proc.tasks.IssueProc")
    @patch("proc.tasks.Article")
    @patch("proc.tasks.Issue")
    @patch("proc.tasks.Journal")
    @patch("proc.tasks._get_user")
    def test_journal_id_none_skips_journal_lookup(
        self,
        mock_get_user,
        mock_journal,
        mock_issue,
        mock_article,
        mock_issue_proc,
        mock_task_exec_cls,
    ):
        mock_get_user.return_value = "USER"
        mock_task_exec = MagicMock()
        mock_task_exec_cls.return_value = mock_task_exec
        mock_duplicates_qs = MagicMock()
        mock_duplicates_qs.count.return_value = 0
        mock_duplicates_qs.iterator.return_value = []
        mock_issue.get_duplicates.return_value = mock_duplicates_qs

        tasks.task_remove_duplicate_issues(journal_id=None)

        mock_journal.objects.get.assert_not_called()
        mock_issue.get_duplicates.assert_called_once_with(None)

    @patch("proc.tasks.TaskExecution")
    @patch("proc.tasks.IssueProc")
    @patch("proc.tasks.Article")
    @patch("proc.tasks.Issue")
    @patch("proc.tasks.Journal")
    @patch("proc.tasks._get_user")
    def test_inner_issue_deletion_exception_is_isolated_and_recorded(
        self,
        mock_get_user,
        mock_journal,
        mock_issue,
        mock_article,
        mock_issue_proc,
        mock_task_exec_cls,
    ):
        mock_get_user.return_value = "USER"
        mock_task_exec = MagicMock()
        mock_task_exec_cls.return_value = mock_task_exec

        duplicated_data = {
            "journal": None,
            "volume": "1",
            "number": "1",
            "supplement": None,
        }
        mock_duplicates_qs = MagicMock()
        mock_duplicates_qs.count.return_value = 1
        mock_duplicates_qs.iterator.return_value = [duplicated_data]
        mock_issue.get_duplicates.return_value = mock_duplicates_qs

        keep_issue = MagicMock(id=1)
        dup_issue = MagicMock(id=2)
        dup_issue.delete.side_effect = Exception("cannot delete")
        mock_issue.objects.filter.return_value.order_by.return_value = [
            keep_issue,
            dup_issue,
        ]

        tasks.task_remove_duplicate_issues(journal_id=None)

        mock_task_exec.add_exception.assert_called_once()
        add_exc_arg = mock_task_exec.add_exception.call_args[0][0]
        self.assertEqual(add_exc_arg["issue_id"], 2)
        # a falha interna não impede finish() de ser chamado sem exceção externa
        mock_task_exec.finish.assert_called_once_with()

    @patch("proc.tasks.TaskExecution")
    @patch("proc.tasks.IssueProc")
    @patch("proc.tasks.Article")
    @patch("proc.tasks.Issue")
    @patch("proc.tasks.Journal")
    @patch("proc.tasks._get_user")
    def test_outer_exception_for_one_group_does_not_stop_others(
        self,
        mock_get_user,
        mock_journal,
        mock_issue,
        mock_article,
        mock_issue_proc,
        mock_task_exec_cls,
    ):
        mock_get_user.return_value = "USER"
        mock_task_exec = MagicMock()
        mock_task_exec_cls.return_value = mock_task_exec

        group1 = {"journal": None, "volume": "1", "number": "1", "supplement": None}
        group2 = {"journal": None, "volume": "2", "number": "1", "supplement": None}
        mock_duplicates_qs = MagicMock()
        mock_duplicates_qs.count.return_value = 2
        mock_duplicates_qs.iterator.return_value = [group1, group2]
        mock_issue.get_duplicates.return_value = mock_duplicates_qs

        keep2 = MagicMock(id=20)
        dup2 = MagicMock(id=21)

        def filter_side_effect(**kwargs):
            if kwargs == group1:
                raise Exception("query failed")
            m = MagicMock()
            m.order_by.return_value = [keep2, dup2]
            return m

        mock_issue.objects.filter.side_effect = filter_side_effect

        tasks.task_remove_duplicate_issues(journal_id=None)

        self.assertEqual(mock_task_exec.add_exception.call_count, 1)
        add_exc_arg = mock_task_exec.add_exception.call_args[0][0]
        self.assertEqual(add_exc_arg["duplicated_issue_data"], group1)
        dup2.delete.assert_called_once()
        mock_task_exec.finish.assert_called_once_with()

    @patch("proc.tasks.TaskExecution")
    @patch("proc.tasks.Issue")
    @patch("proc.tasks.Journal")
    @patch("proc.tasks._get_user")
    def test_top_level_exception_calls_finish_with_exception(
        self, mock_get_user, mock_journal, mock_issue, mock_task_exec_cls
    ):
        mock_get_user.return_value = "USER"
        mock_task_exec = MagicMock()
        mock_task_exec_cls.return_value = mock_task_exec
        mock_issue.get_duplicates.side_effect = Exception("boom")

        tasks.task_remove_duplicate_issues(journal_id=None)

        kwargs = mock_task_exec.finish.call_args.kwargs
        self.assertIsInstance(kwargs["exception"], Exception)
        self.assertIsNotNone(kwargs["exc_traceback"])


class TaskTrackClassicWebsiteArticlePidsTest(TestCase):
    """Testes para task_track_classic_website_article_pids."""

    @patch("proc.tasks.task_track_classic_website_article_pids_for_collection")
    @patch("proc.tasks._get_collections")
    @patch("proc.tasks._get_user")
    @patch("proc.tasks.TaskExecution")
    def test_schedules_task_for_each_collection(
        self, mock_task_exec_cls, mock_get_user, mock_get_collections, mock_subtask
    ):
        mock_task_exec = MagicMock()
        mock_task_exec_cls.return_value = mock_task_exec
        mock_get_user.return_value = "USER"
        col1 = MagicMock(acron="scl")
        col2 = MagicMock(acron="arg")
        mock_get_collections.return_value = [col1, col2]

        tasks.task_track_classic_website_article_pids(
            username="bob", user_id=1, collection_acron=None, timeout=5, force_update=True
        )

        self.assertEqual(mock_subtask.delay.call_count, 2)
        mock_subtask.delay.assert_any_call(
            username="bob", user_id=1, collection_acron="scl", timeout=5, force_update=True
        )
        mock_subtask.delay.assert_any_call(
            username="bob", user_id=1, collection_acron="arg", timeout=5, force_update=True
        )
        mock_task_exec.finish.assert_called_once_with()

    @patch("proc.tasks.task_track_classic_website_article_pids_for_collection")
    @patch("proc.tasks._get_collections")
    @patch("proc.tasks._get_user")
    @patch("proc.tasks.TaskExecution")
    def test_exception_calls_finish_with_exception(
        self, mock_task_exec_cls, mock_get_user, mock_get_collections, mock_subtask
    ):
        mock_task_exec = MagicMock()
        mock_task_exec_cls.return_value = mock_task_exec
        mock_get_user.return_value = "USER"
        mock_get_collections.side_effect = Exception("boom")

        tasks.task_track_classic_website_article_pids(username="bob")

        kwargs = mock_task_exec.finish.call_args.kwargs
        self.assertIsInstance(kwargs["exception"], Exception)


class TaskTrackClassicWebsiteArticlePidsForCollectionTest(TestCase):
    """Testes para task_track_classic_website_article_pids_for_collection."""

    @patch("proc.tasks.task_check_article_webpages")
    @patch("proc.tasks.WebSiteConfiguration")
    @patch("proc.tasks.ArticleProc")
    @patch("proc.tasks.ClassicWebsiteArticlePidTracker")
    @patch("proc.tasks.Collection")
    @patch("proc.tasks._get_user")
    @patch("proc.tasks.TaskExecution")
    def test_skips_article_proc_without_article_and_schedules_for_others(
        self,
        mock_task_exec_cls,
        mock_get_user,
        mock_collection,
        mock_tracker_cls,
        mock_article_proc,
        mock_wsc,
        mock_check_webpages,
    ):
        mock_task_exec = MagicMock()
        mock_task_exec_cls.return_value = mock_task_exec
        mock_get_user.return_value = "USER"
        collection = MagicMock()
        mock_collection.objects.get.return_value = collection
        mock_tracker = MagicMock()
        mock_tracker.update_pid_status.return_value = {"total": 1}
        mock_tracker_cls.return_value = mock_tracker

        ap_no_article = MagicMock(article=None)
        article = MagicMock(id=55)
        ap_with_article = MagicMock(article=article, id=10, collection=collection)
        mock_article_proc.items_to_check_url_and_content.return_value = [
            ap_no_article,
            ap_with_article,
        ]

        website_qa = MagicMock(purpose="QA")
        website_public = MagicMock(purpose="PUBLIC")
        mock_wsc.objects.filter.return_value = [website_qa, website_public]

        tasks.task_track_classic_website_article_pids_for_collection(
            username="bob", user_id=1, collection_acron="scl", timeout=5, force_update=True
        )

        mock_tracker_cls.assert_called_once_with("USER", collection)
        mock_tracker.update_pid_status.assert_called_once()
        mock_task_exec.add_event.assert_called_once_with({"total": 1})

        self.assertEqual(mock_check_webpages.delay.call_count, 2)
        mock_check_webpages.delay.assert_any_call(
            user_id=1,
            username="bob",
            collection_id=collection.id,
            website_kind="QA",
            article_id=55,
            timeout=5,
            force_update=True,
            article_proc_id=10,
        )
        mock_check_webpages.delay.assert_any_call(
            user_id=1,
            username="bob",
            collection_id=collection.id,
            website_kind="PUBLIC",
            article_id=55,
            timeout=5,
            force_update=True,
            article_proc_id=10,
        )
        mock_task_exec.finish.assert_called_once_with()

    @patch("proc.tasks.Collection")
    @patch("proc.tasks._get_user")
    @patch("proc.tasks.TaskExecution")
    def test_exception_calls_finish_with_exception(
        self, mock_task_exec_cls, mock_get_user, mock_collection
    ):
        mock_task_exec = MagicMock()
        mock_task_exec_cls.return_value = mock_task_exec
        mock_get_user.return_value = "USER"
        mock_collection.objects.get.side_effect = Exception("not found")

        tasks.task_track_classic_website_article_pids_for_collection(
            username="bob", collection_acron="missing"
        )

        kwargs = mock_task_exec.finish.call_args.kwargs
        self.assertIsInstance(kwargs["exception"], Exception)


class TaskCheckArticleWebpagesTest(TestCase):
    """Testes para task_check_article_webpages."""

    @patch("proc.tasks._get_user")
    @patch("proc.tasks.ArticleProc")
    def test_happy_path_sets_pid_status_for_each_valid_response(
        self, mock_article_proc, mock_get_user
    ):
        mock_get_user.return_value = "USER"
        article_proc = MagicMock()
        mock_article_proc.objects.get.return_value = article_proc
        event = MagicMock()
        article_proc.start.return_value = event
        article = MagicMock()
        article_proc.article = article
        article.availability = "AVAILABLE"
        resp_classic = {"valid": True, "new_pid_status": "CLASSIC_MATCHED"}
        resp_public = {"valid": True, "new_pid_status": "PUBLIC_VALID"}
        article.available_on_classic_website.return_value = resp_classic
        article.available_on_public_website.return_value = resp_public

        tasks.task_check_article_webpages(
            user_id=1,
            username="bob",
            article_id=99,
            collection_id=5,
            website_kind="QA",
            timeout=10,
            force_update=False,
            article_proc_id=77,
        )

        mock_article_proc.objects.get.assert_called_once_with(pk=77)
        article.create_or_update_article_collections.assert_called_once_with("USER")
        article.check_availability.assert_called_once_with(
            "USER", collection_id=5, purpose="QA", force_update=False
        )
        self.assertEqual(article_proc.set_pid_status.call_count, 2)
        article_proc.set_pid_status.assert_any_call("USER", "CLASSIC_MATCHED")
        article_proc.set_pid_status.assert_any_call("USER", "PUBLIC_VALID")
        event.finish.assert_called_once_with(
            "USER",
            completed=True,
            detail={
                "responses": [resp_classic, resp_public],
                "availability": "AVAILABLE",
            },
        )

    @patch("proc.tasks._get_user")
    @patch("proc.tasks.ArticleProc")
    def test_only_valid_response_triggers_set_pid_status(
        self, mock_article_proc, mock_get_user
    ):
        mock_get_user.return_value = "USER"
        article_proc = MagicMock()
        mock_article_proc.objects.get.return_value = article_proc
        event = MagicMock()
        article_proc.start.return_value = event
        article = MagicMock()
        article_proc.article = article
        article.availability = "PARTIAL"
        article.available_on_classic_website.return_value = {"valid": False}
        article.available_on_public_website.return_value = {
            "valid": True,
            "new_pid_status": "X",
        }

        tasks.task_check_article_webpages(article_proc_id=1)

        article_proc.set_pid_status.assert_called_once_with("USER", "X")

    @patch("proc.tasks.UnexpectedEvent")
    @patch("proc.tasks._get_user")
    @patch("proc.tasks.ArticleProc")
    def test_creates_unexpected_event_when_article_proc_lookup_fails_before_event_created(
        self, mock_article_proc, mock_get_user, mock_unexpected_event
    ):
        mock_get_user.return_value = "USER"
        mock_article_proc.objects.get.side_effect = Exception("not found")

        tasks.task_check_article_webpages(article_proc_id=1)

        mock_unexpected_event.create.assert_called_once()
        kwargs = mock_unexpected_event.create.call_args.kwargs
        self.assertEqual(
            kwargs["detail"]["task"], "proc.tasks.task_check_article_webpages"
        )

    @patch("proc.tasks.UnexpectedEvent")
    @patch("proc.tasks._get_user")
    @patch("proc.tasks.ArticleProc")
    def test_event_finish_called_with_exception_when_error_occurs_after_event_creation(
        self, mock_article_proc, mock_get_user, mock_unexpected_event
    ):
        mock_get_user.return_value = "USER"
        article_proc = MagicMock()
        mock_article_proc.objects.get.return_value = article_proc
        event = MagicMock()
        article_proc.start.return_value = event
        article = MagicMock()
        article_proc.article = article
        article.check_availability.side_effect = Exception("network error")

        tasks.task_check_article_webpages(article_proc_id=1)

        event.finish.assert_called_once()
        call_args, call_kwargs = event.finish.call_args
        self.assertEqual(call_args, ("USER",))
        self.assertIsInstance(call_kwargs["exception"], Exception)
        mock_unexpected_event.create.assert_not_called()


class TaskCheckArticlePageAvailabilityTest(TestCase):
    """Testes para task_check_article_page_availability."""

    @patch("proc.tasks.UnexpectedEvent")
    @patch("proc.tasks.ArticleWebPage")
    @patch("proc.tasks._get_user")
    def test_happy_path_calls_check_page(
        self, mock_get_user, mock_webpage, mock_unexpected_event
    ):
        mock_get_user.return_value = "USER"
        page = MagicMock()
        mock_webpage.objects.get.return_value = page

        tasks.task_check_article_page_availability(
            webpage_id=5, article_metadata={"a": 1}, timeout=10, force_update=True
        )

        mock_webpage.objects.get.assert_called_once_with(id=5)
        page.check_page.assert_called_once_with("USER", 10, {"a": 1}, True)
        mock_unexpected_event.create.assert_not_called()

    @patch("proc.tasks.UnexpectedEvent")
    def test_missing_webpage_id_raises_value_error_and_creates_unexpected_event(
        self, mock_unexpected_event
    ):
        tasks.task_check_article_page_availability(webpage_id=None)

        mock_unexpected_event.create.assert_called_once()
        kwargs = mock_unexpected_event.create.call_args.kwargs
        self.assertIsInstance(kwargs["e"], ValueError)
        self.assertEqual(
            kwargs["detail"]["task"], "proc.tasks.task_check_article_page_availability"
        )


class TaskUpdateArticleProcAvailabilityTest(TestCase):
    """Testes para task_update_article_proc_availability."""

    @patch("proc.tasks._get_user")
    @patch("proc.tasks.ArticleCollection")
    @patch("proc.tasks.ArticleProc")
    def test_sets_pid_status_when_article_collection_is_available(
        self, mock_article_proc, mock_article_collection, mock_get_user
    ):
        mock_get_user.return_value = "USER"
        article_proc = MagicMock()
        mock_article_proc.objects.select_related.return_value.get.return_value = (
            article_proc
        )
        art_col = MagicMock(is_available=True)
        mock_article_collection.objects.get.return_value = art_col

        tasks.task_update_article_proc_availability(
            article_proc_id=1, article_collection_id=2
        )

        article_proc.set_pid_status.assert_called_once_with(
            "USER", migration_choices.PID_STATUS_PUBLIC_VALID
        )

    @patch("proc.tasks._get_user")
    @patch("proc.tasks.ArticleCollection")
    @patch("proc.tasks.ArticleProc")
    def test_does_not_set_pid_status_when_not_available(
        self, mock_article_proc, mock_article_collection, mock_get_user
    ):
        mock_get_user.return_value = "USER"
        article_proc = MagicMock()
        mock_article_proc.objects.select_related.return_value.get.return_value = (
            article_proc
        )
        art_col = MagicMock(is_available=False)
        mock_article_collection.objects.get.return_value = art_col

        tasks.task_update_article_proc_availability(
            article_proc_id=1, article_collection_id=2
        )

        article_proc.set_pid_status.assert_not_called()

    @patch("proc.tasks.UnexpectedEvent")
    @patch("proc.tasks._get_user")
    @patch("proc.tasks.ArticleProc")
    def test_exception_creates_unexpected_event(
        self, mock_article_proc, mock_get_user, mock_unexpected_event
    ):
        mock_get_user.return_value = "USER"
        mock_article_proc.objects.select_related.return_value.get.side_effect = (
            Exception("db error")
        )

        tasks.task_update_article_proc_availability(
            article_proc_id=1, article_collection_id=2
        )

        mock_unexpected_event.create.assert_called_once()
        kwargs = mock_unexpected_event.create.call_args.kwargs
        self.assertEqual(
            kwargs["detail"]["task"], "proc.tasks.task_update_article_proc_availability"
        )


class TaskCheckArticlesAvailabilityTest(TestCase):
    """Testes para task_check_articles_availability."""

    @patch("proc.tasks.task_check_article_webpages")
    @patch("proc.tasks.ArticleProc")
    @patch("proc.tasks._get_user")
    def test_builds_filter_kwargs_and_schedules_check_for_each_article(
        self, mock_get_user, mock_article_proc, mock_check_webpages
    ):
        mock_get_user.return_value = "USER"
        ap1 = MagicMock(id=1, collection_id=10)
        ap1.article.id = 100
        mock_article_proc.objects.filter.return_value = [ap1]

        tasks.task_check_articles_availability(
            username="bob",
            user_id=2,
            article_pid_v3="pidv3",
            publication_year="2020",
            issue_folder="01",
            collection_acron="scl",
            timeout=5,
            force_update=True,
        )

        args, kwargs = mock_article_proc.objects.filter.call_args
        self.assertEqual(args[0], Q())
        self.assertEqual(
            kwargs,
            {
                "sps_pkg__pid_v3": "pidv3",
                "issue_proc__issue__publication_year": "2020",
                "issue_proc__issue__issue_folder": "01",
                "collection__acron": "scl",
            },
        )
        mock_check_webpages.delay.assert_called_once_with(
            user_id=2,
            username="bob",
            article_proc_id=1,
            article_id=100,
            collection_id=10,
            timeout=5,
            force_update=True,
        )

    @patch("proc.tasks.task_check_article_webpages")
    @patch("proc.tasks.ArticleProc")
    @patch("proc.tasks._get_user")
    def test_issn_filters_build_or_query(
        self, mock_get_user, mock_article_proc, mock_check_webpages
    ):
        mock_get_user.return_value = "USER"
        mock_article_proc.objects.filter.return_value = []

        tasks.task_check_articles_availability(
            username="bob", issn_print="1111-2222", issn_electronic="2222-3333"
        )

        args, kwargs = mock_article_proc.objects.filter.call_args
        expected_q = Q(
            issue_proc__journal_proc__journal__official_journal__issn_print="1111-2222"
        ) | Q(
            issue_proc__journal_proc__journal__official_journal__issn_electronic="2222-3333"
        )
        self.assertEqual(args[0], expected_q)

    @patch("proc.tasks.UnexpectedEvent")
    @patch("proc.tasks.ArticleProc")
    @patch("proc.tasks._get_user")
    def test_exception_creates_unexpected_event(
        self, mock_get_user, mock_article_proc, mock_unexpected_event
    ):
        mock_get_user.return_value = "USER"
        mock_article_proc.objects.filter.side_effect = Exception("boom")

        tasks.task_check_articles_availability(username="bob", collection_acron="scl")

        mock_unexpected_event.create.assert_called_once()
        kwargs = mock_unexpected_event.create.call_args.kwargs
        self.assertEqual(
            kwargs["detail"]["task"], "proc.tasks.task_check_articles_availability"
        )
        self.assertEqual(kwargs["detail"]["collection_acron"], "scl")


class TaskCheckMigratedArticleTest(TestCase):
    """Testes para task_check_migrated_article."""

    @patch("proc.tasks.UnexpectedEvent")
    @patch("proc.tasks._get_user")
    @patch("proc.tasks.ArticleProc")
    def test_missing_article_raises_value_error_and_creates_unexpected_event(
        self, mock_article_proc, mock_get_user, mock_unexpected_event
    ):
        mock_get_user.return_value = "USER"
        article_proc = MagicMock(article=None)
        mock_article_proc.objects.select_related.return_value.get.return_value = (
            article_proc
        )

        tasks.task_check_migrated_article(article_proc_id=5)

        mock_unexpected_event.create.assert_called_once()
        kwargs = mock_unexpected_event.create.call_args.kwargs
        self.assertIsInstance(kwargs["e"], ValueError)
        self.assertEqual(
            kwargs["detail"]["task"], "proc.tasks.task_check_migrated_article"
        )

    @patch("proc.tasks._get_user")
    @patch("proc.tasks.ArticleProc")
    def test_sets_pid_status_for_each_valid_response(
        self, mock_article_proc, mock_get_user
    ):
        mock_get_user.return_value = "USER"
        article_proc = MagicMock()
        article = MagicMock()
        article.webpages = []
        article_proc.article = article
        mock_article_proc.objects.select_related.return_value.get.return_value = (
            article_proc
        )
        resp_classic = {"valid": True, "new_pid_status": "CLASSIC_MATCHED"}
        resp_public = {"valid": True, "new_pid_status": "PUBLIC_VALID"}
        article.available_on_classic_website.return_value = resp_classic
        article.available_on_public_website.return_value = resp_public

        tasks.task_check_migrated_article(article_proc_id=5)

        article.create_or_update_article_collections.assert_called_once_with("USER")
        article.check_availability.assert_called_once_with("USER")
        self.assertEqual(article_proc.set_pid_status.call_count, 2)
        article_proc.set_pid_status.assert_any_call("USER", "CLASSIC_MATCHED")
        article_proc.set_pid_status.assert_any_call("USER", "PUBLIC_VALID")

    @patch("proc.tasks._get_user")
    @patch("proc.tasks.ArticleProc")
    def test_does_not_set_pid_status_when_responses_invalid(
        self, mock_article_proc, mock_get_user
    ):
        mock_get_user.return_value = "USER"
        article_proc = MagicMock()
        article = MagicMock()
        article.webpages = []
        article_proc.article = article
        mock_article_proc.objects.select_related.return_value.get.return_value = (
            article_proc
        )
        article.available_on_classic_website.return_value = {"valid": False}
        article.available_on_public_website.return_value = {"valid": False}

        tasks.task_check_migrated_article(article_proc_id=5)

        article_proc.set_pid_status.assert_not_called()


if __name__ == "__main__":
    unittest.main()
