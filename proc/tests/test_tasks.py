import traceback
import unittest
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.test import TestCase

from migration import choices as migration_choices
from tracker import choices as tracker_choices
from proc import tasks
from proc.models import ArticleProc, IssueProc, JournalProc

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
        self.assertEqual(task_exec.steps, [])
        self.assertEqual(task_exec.stats, {})
        self.assertEqual(task_exec.errors, [])
        self.assertIsNone(task_exec.journal_proc_id)
        self.assertEqual(task_exec.first_status, {})
        self.assertEqual(task_exec.last_status, {})


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


def _new_task_exec(mock_tracker_cls, total_to_process=0, total_processed=0, params=None):
    mock_tracker = MagicMock()
    mock_tracker.total_to_process = total_to_process
    mock_tracker.total_processed = total_processed
    mock_tracker_cls.create.return_value = mock_tracker
    task_exec = tasks.TaskExecution(name="n", item="i", params=params or {})
    return task_exec, mock_tracker


def _titles(task_exec):
    """Retorna os títulos das etapas sem o prefixo "#N +Xs "."""
    return [next(iter(step)).split(" ", 1)[1] for step in task_exec.steps]


def _contents(task_exec):
    """Retorna o conteúdo das etapas sem "elapsed"."""
    return [
        {k: v for k, v in next(iter(step.values())).items() if k != "elapsed"}
        for step in task_exec.steps
    ]


class TaskExecutionAddExceptionTest(TestCase):
    """Testes para TaskExecution.add_exception."""

    @patch("proc.tasks.TaskTracker")
    def test_add_exception_with_exception_object(self, mock_tracker_cls):
        task_exec, _ = _new_task_exec(mock_tracker_cls)

        try:
            raise ValueError("boom")
        except ValueError as e:
            task_exec.add_exception(e, item="S0001")

        self.assertEqual(
            task_exec.errors,
            [{"type": "ValueError", "message": "boom", "item": "S0001", "step": "#1"}],
        )
        self.assertEqual(_titles(task_exec), ["ERROR ValueError: boom"])
        self.assertEqual(_contents(task_exec), [{"item": "S0001"}])

    @patch("proc.tasks.TaskTracker")
    def test_add_exception_parses_format_exc_text(self, mock_tracker_cls):
        task_exec, _ = _new_task_exec(mock_tracker_cls)
        task_exec.add_event({"operation": "first"})

        try:
            raise KeyError("missing")
        except KeyError:
            task_exec.add_exception(traceback.format_exc())

        error = task_exec.errors[0]
        self.assertEqual(error["type"], "KeyError")
        self.assertEqual(error["message"], "'missing'")
        self.assertEqual(error["step"], "#2")
        self.assertIsInstance(error["traceback"], list)
        self.assertTrue(error["traceback"][0].startswith("Traceback"))

    @patch("proc.tasks.TaskTracker")
    def test_add_exception_with_plain_message(self, mock_tracker_cls):
        task_exec, _ = _new_task_exec(mock_tracker_cls)

        task_exec.add_exception("Skip publish X")

        self.assertEqual(task_exec.errors, [{"message": "Skip publish X", "step": "#1"}])
        self.assertEqual(_titles(task_exec), ["ERROR Skip publish X"])

    @patch("proc.tasks.TaskTracker")
    def test_add_exception_with_dict_keeps_keys(self, mock_tracker_cls):
        task_exec, _ = _new_task_exec(mock_tracker_cls)

        task_exec.add_exception({"issue_id": 3, "traceback": "Traceback ...\nValueError: x"})

        error = task_exec.errors[0]
        self.assertEqual(error["issue_id"], 3)
        self.assertEqual(error["type"], "ValueError")
        self.assertEqual(error["message"], "x")


class TaskExecutionAddEventTest(TestCase):
    """Testes para TaskExecution.add_event."""

    @patch("proc.tasks.TaskTracker")
    def test_operation_becomes_step_title(self, mock_tracker_cls):
        task_exec, _ = _new_task_exec(mock_tracker_cls)

        task_exec.add_event({"operation": "migrate_document_records", "response": {"a": 1}})

        self.assertEqual(len(task_exec.steps), 1)
        (title, values), = task_exec.steps[0].items()
        self.assertEqual(title, "#1 migrate_document_records")
        self.assertRegex(values["elapsed"], r"^\d+\.\ds$")
        self.assertEqual(_contents(task_exec), [{"response": {"a": 1}}])

    @patch("proc.tasks.TaskTracker")
    def test_action_becomes_step_title(self, mock_tracker_cls):
        task_exec, _ = _new_task_exec(mock_tracker_cls)

        task_exec.add_event({"action": "scheduled", "item": "abc"})

        self.assertEqual(_titles(task_exec), ["scheduled"])
        self.assertEqual(_contents(task_exec), [{"item": "abc"}])

    @patch("proc.tasks.TaskTracker")
    def test_single_key_becomes_step_title(self, mock_tracker_cls):
        task_exec, _ = _new_task_exec(mock_tracker_cls)

        task_exec.add_event({"websites": [1]})

        self.assertEqual(_titles(task_exec), ["websites"])

    @patch("proc.tasks.TaskTracker")
    def test_operation_without_content_is_ok(self, mock_tracker_cls):
        task_exec, _ = _new_task_exec(mock_tracker_cls)

        task_exec.add_event({"operation": "Scheduled articles publication"})

        self.assertEqual(_contents(task_exec), [{}])

    @patch("proc.tasks.TaskTracker")
    def test_list_adds_one_step_per_item_and_none_is_ignored(self, mock_tracker_cls):
        task_exec, _ = _new_task_exec(mock_tracker_cls)

        task_exec.add_event(None)
        task_exec.add_event([{"operation": "a"}, {"operation": "b"}])
        task_exec.add_event({"operation": "c"})

        self.assertEqual(_titles(task_exec), ["a", "b", "c"])
        self.assertEqual(
            [next(iter(step)).split(" ")[0] for step in task_exec.steps],
            ["#1", "#2", "#3"],
        )


class TaskExecutionAddNumberTest(TestCase):
    """Testes para TaskExecution.add_number."""

    @patch("proc.tasks.TaskTracker")
    def test_add_number_sets_stats_key(self, mock_tracker_cls):
        task_exec, _ = _new_task_exec(mock_tracker_cls)

        task_exec.add_number("total", 5)

        self.assertEqual(task_exec.stats["total"], 5)


class TaskExecutionFinishTest(TestCase):
    """Testes para TaskExecution.finish: completed flag, resumo, fallback JSON e erro interno."""

    @patch("proc.tasks.TaskTracker")
    def test_completed_true_when_no_exception_no_traceback_no_errors(self, mock_tracker_cls):
        task_exec, mock_tracker = _new_task_exec(mock_tracker_cls, 10, 10)

        task_exec.finish()

        kwargs = mock_tracker.finish.call_args.kwargs
        self.assertTrue(kwargs["completed"])
        self.assertIsNone(kwargs["exception"])
        self.assertIsNone(kwargs["exc_traceback"])
        self.assertEqual(kwargs["detail"]["1_summary"]["result"], "completed")

    @patch("proc.tasks.TaskTracker")
    def test_completed_false_when_exception_given(self, mock_tracker_cls):
        task_exec, mock_tracker = _new_task_exec(mock_tracker_cls)

        task_exec.finish(exception=ValueError("x"))

        kwargs = mock_tracker.finish.call_args.kwargs
        self.assertFalse(kwargs["completed"])
        self.assertEqual(
            kwargs["detail"]["1_summary"]["result"], "interrupted (ValueError: x)"
        )

    @patch("proc.tasks.TaskTracker")
    def test_completed_false_when_exc_traceback_given(self, mock_tracker_cls):
        task_exec, mock_tracker = _new_task_exec(mock_tracker_cls)

        try:
            raise ValueError("boom")
        except ValueError:
            import sys
            _, _, tb = sys.exc_info()
            task_exec.finish(exc_traceback=tb)

        self.assertFalse(mock_tracker.finish.call_args.kwargs["completed"])

    @patch("proc.tasks.TaskTracker")
    def test_completed_false_when_errors_present(self, mock_tracker_cls):
        task_exec, mock_tracker = _new_task_exec(mock_tracker_cls)
        task_exec.add_exception(ValueError("previous failure"))

        task_exec.finish()

        kwargs = mock_tracker.finish.call_args.kwargs
        self.assertFalse(kwargs["completed"])
        summary = kwargs["detail"]["1_summary"]
        self.assertEqual(summary["result"], "completed with errors")
        self.assertEqual(summary["total_errors"], 1)
        self.assertEqual(len(kwargs["detail"]["4_errors"]), 1)

    @patch("proc.tasks.TaskTracker")
    def test_summary_has_totals_stats_and_duration(self, mock_tracker_cls):
        task_exec, mock_tracker = _new_task_exec(mock_tracker_cls, 7, 3)
        task_exec.add_number("total_articleprocs", 9)

        task_exec.finish(data={"x": 1})

        detail = mock_tracker.finish.call_args.kwargs["detail"]
        summary = detail["1_summary"]
        self.assertEqual(summary["total_to_process"], 7)
        self.assertEqual(summary["total_processed"], 3)
        self.assertEqual(summary["total_articleprocs"], 9)
        self.assertRegex(summary["duration"], r"^\d+\.\ds$")
        self.assertNotIn("status", summary)
        self.assertEqual(detail["5_data"], {"x": 1})

    @patch("proc.tasks.TaskTracker")
    def test_falls_back_to_str_for_non_json_serializable_params(self, mock_tracker_cls):
        task_exec, mock_tracker = _new_task_exec(
            mock_tracker_cls, params={"bad": ValueError("cannot serialize me")}
        )

        task_exec.finish()

        detail = mock_tracker.finish.call_args.kwargs["detail"]
        # only the non-serializable value is stringified
        self.assertEqual(detail["2_params"], {"bad": "cannot serialize me"})
        # the remaining, serializable fields are preserved as-is
        self.assertEqual(detail["1_summary"]["total_to_process"], 0)
        self.assertEqual(detail["3_steps"], [])
        self.assertEqual(detail["4_errors"], [])

    @patch("proc.tasks.TaskTracker")
    def test_falls_back_to_str_for_non_serializable_set_value(self, mock_tracker_cls):
        task_exec, mock_tracker = _new_task_exec(mock_tracker_cls, params={"bad": {1, 2, 3}})

        task_exec.finish()

        detail = mock_tracker.finish.call_args.kwargs["detail"]
        self.assertEqual(detail["2_params"], {"bad": [1, 2, 3]})

    @patch("proc.tasks.TaskTracker")
    def test_tuple_keys_and_sets_become_readable_json(self, mock_tracker_cls):
        task_exec, mock_tracker = _new_task_exec(mock_tracker_cls)
        task_exec.add_event({
            "operation": "selected",
            "response": {(4277, "rsp"): {"issue_proc_id_list": {16203, 16196}}},
        })

        task_exec.finish()

        detail = mock_tracker.finish.call_args.kwargs["detail"]
        step = detail["3_steps"][0]["#1 selected"]
        self.assertEqual(
            step["response"], {"4277 | rsp": {"issue_proc_id_list": [16196, 16203]}}
        )

    @patch("proc.tasks.UnexpectedEvent")
    @patch("proc.tasks.TaskTracker")
    def test_calls_unexpected_event_create_when_task_tracker_finish_raises(
        self, mock_tracker_cls, mock_unexpected_event
    ):
        task_exec, mock_tracker = _new_task_exec(mock_tracker_cls)
        mock_tracker.item = "item-x"
        mock_tracker.finish.side_effect = Exception("db unavailable")

        task_exec.finish()

        mock_unexpected_event.create.assert_called_once()
        kwargs = mock_unexpected_event.create.call_args.kwargs
        self.assertEqual(kwargs["action"], "proc.tasks.TaskExecution.finish")
        self.assertEqual(kwargs["item"], "item-x")


class TaskExecutionUpdateTotalStatusTest(TestCase):
    """Testes para TaskExecution.update_total_status."""

    @patch("proc.tasks.get_total_status_data")
    @patch("proc.tasks.TaskTracker")
    def test_first_call_records_full_status_then_only_changes(
        self, mock_tracker_cls, mock_get_total_status_data
    ):
        task_exec, mock_tracker = _new_task_exec(mock_tracker_cls)
        task_exec.journal_proc_id = 42

        mock_get_total_status_data.return_value = {
            "journal": [{"total": 1, "status": {"migration_status": "DONE"}}],
            "article": [{"migration_status": "TODO", "qa_ws_status": "TODO", "total": 10}],
        }
        task_exec.update_total_status("Start", issue_proc_id=7)
        mock_get_total_status_data.assert_called_once_with(42, 7)

        mock_get_total_status_data.return_value = {
            "journal": [{"total": 1, "status": {"migration_status": "DONE"}}],
            "article": [
                {"migration_status": "TODO", "qa_ws_status": "TODO", "total": 1},
                {"migration_status": "DONE", "qa_ws_status": "TODO", "total": 9},
            ],
        }
        task_exec.update_total_status("Migrated", issue_proc_id=7)
        task_exec.update_total_status("Nothing", issue_proc_id=7)

        self.assertEqual(_titles(task_exec), ["Start", "Migrated", "Nothing"])
        start, migrated, nothing = _contents(task_exec)
        self.assertEqual(
            start,
            {"status": {
                "journal": {"migration=DONE": 1},
                "article": {"migration=TODO | qa_ws=TODO": 10},
            }},
        )
        self.assertEqual(
            migrated,
            {"status_changes": {"article": {
                "migration=TODO | qa_ws=TODO": "10 -> 1",
                "migration=DONE | qa_ws=TODO": "0 -> 9",
            }}},
        )
        self.assertEqual(nothing, {"status_changes": "no changes"})

        task_exec.finish()
        summary = mock_tracker.finish.call_args.kwargs["detail"]["1_summary"]
        self.assertEqual(
            summary["status"]["1_before"],
            {
                "journal": {"migration=DONE": 1},
                "article": {"migration=TODO | qa_ws=TODO": 10},
            },
        )
        self.assertEqual(
            summary["status"]["2_after"],
            {
                "journal": {"migration=DONE": 1},
                "article": {
                    "migration=TODO | qa_ws=TODO": 1,
                    "migration=DONE | qa_ws=TODO": 9,
                },
            },
        )
        self.assertEqual(
            summary["status"]["3_changes"],
            {"article": {
                "migration=TODO | qa_ws=TODO": "10 -> 1",
                "migration=DONE | qa_ws=TODO": "0 -> 9",
            }},
        )

    @patch("proc.tasks.get_total_status_data")
    @patch("proc.tasks.TaskTracker")
    def test_summary_status_no_changes_when_only_start(
        self, mock_tracker_cls, mock_get_total_status_data
    ):
        task_exec, mock_tracker = _new_task_exec(mock_tracker_cls)
        mock_get_total_status_data.return_value = {
            "article": [{"migration_status": "DONE", "total": 3}],
        }
        task_exec.update_total_status("Start")

        task_exec.finish()

        status = mock_tracker.finish.call_args.kwargs["detail"]["1_summary"]["status"]
        self.assertEqual(status["1_before"], {"article": {"migration=DONE": 3}})
        self.assertEqual(status["2_after"], {"article": {"migration=DONE": 3}})
        self.assertEqual(status["3_changes"], "no changes")


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
    """Testes para *Proc.fix_publication_status: TODO <-> IGNORED conforme
    WebSiteConfiguration, somente nos itens da classe chamada."""

    PROC_CLASSES = (JournalProc, IssueProc, ArticleProc)

    def _run(self, proc_class, enabled_purposes):
        collection = MagicMock()
        with patch("proc.models.WebSiteConfiguration") as mock_wsc, patch.object(
            JournalProc, "objects"
        ) as journal_objects, patch.object(
            IssueProc, "objects"
        ) as issue_objects, patch.object(
            ArticleProc, "objects"
        ) as article_objects:
            mock_wsc.objects.filter.return_value.values_list.return_value = (
                enabled_purposes
            )
            proc_class.fix_publication_status(collection)
            mock_wsc.objects.filter.assert_called_once_with(
                collection=collection, enabled=True
            )
        objects = {
            JournalProc: journal_objects,
            IssueProc: issue_objects,
            ArticleProc: article_objects,
        }
        for other_class, other_objects in objects.items():
            if other_class is not proc_class:
                other_objects.filter.assert_not_called()
        return collection, objects[proc_class]

    def _assert_updates(self, collection, objects, qa_from, qa_to, public_from, public_to):
        objects.filter.assert_any_call(collection=collection, qa_ws_status=qa_from)
        objects.filter.assert_any_call(
            collection=collection, public_ws_status=public_from
        )
        objects.filter.return_value.update.assert_any_call(qa_ws_status=qa_to)
        objects.filter.return_value.update.assert_any_call(public_ws_status=public_to)

    def test_qa_enabled_public_disabled(self):
        for proc_class in self.PROC_CLASSES:
            with self.subTest(proc_class=proc_class.__name__):
                collection, objects = self._run(proc_class, ["QA"])
                self._assert_updates(
                    collection,
                    objects,
                    tracker_choices.PROGRESS_STATUS_IGNORED,
                    tracker_choices.PROGRESS_STATUS_TODO,
                    tracker_choices.PROGRESS_STATUS_TODO,
                    tracker_choices.PROGRESS_STATUS_IGNORED,
                )

    def test_both_disabled(self):
        for proc_class in self.PROC_CLASSES:
            with self.subTest(proc_class=proc_class.__name__):
                collection, objects = self._run(proc_class, [])
                self._assert_updates(
                    collection,
                    objects,
                    tracker_choices.PROGRESS_STATUS_TODO,
                    tracker_choices.PROGRESS_STATUS_IGNORED,
                    tracker_choices.PROGRESS_STATUS_TODO,
                    tracker_choices.PROGRESS_STATUS_IGNORED,
                )

    def test_both_enabled(self):
        for proc_class in self.PROC_CLASSES:
            with self.subTest(proc_class=proc_class.__name__):
                collection, objects = self._run(proc_class, ["QA", "PUBLIC"])
                self._assert_updates(
                    collection,
                    objects,
                    tracker_choices.PROGRESS_STATUS_IGNORED,
                    tracker_choices.PROGRESS_STATUS_TODO,
                    tracker_choices.PROGRESS_STATUS_IGNORED,
                    tracker_choices.PROGRESS_STATUS_TODO,
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


class TaskFixIssueArticlesTest(TestCase):
    """Testes para task_fix_issue_articles (não usa TaskExecution).

    Renomeada de task_exclude_invalid_issue_articles (commit ba92d1335be2):
    agora sempre reconcilia sps_pkg.collection_pid_v2
    (ArticleProc.complete_sps_pkg_ppx) e só executa as exclusões destrutivas
    (SPSPkg/Article/ArticleProc.exclude_invalid_records) quando as flags
    delete_* correspondentes são True.
    """

    @patch("proc.tasks.ArticleProc")
    @patch("proc.tasks.Article")
    @patch("proc.tasks.IssueProc")
    @patch("proc.tasks._get_user")
    def test_default_flags_only_reconciles_ppx_without_deleting(
        self, mock_get_user, mock_issue_proc, mock_article, mock_article_proc
    ):
        mock_get_user.return_value = "USER"
        mock_issue = MagicMock()
        mock_issue_proc_instance = MagicMock(issue=mock_issue)
        mock_issue_proc.objects.select_related.return_value.get.return_value = (
            mock_issue_proc_instance
        )
        mock_article_proc.complete_sps_pkg_ppx.return_value = {"completed": 2}

        result = tasks.task_fix_issue_articles(
            issue_proc_id=10, username="bob", user_id=None
        )

        mock_issue_proc.objects.select_related.assert_called_once_with("issue")
        mock_issue_proc.objects.select_related.return_value.get.assert_called_once_with(
            id=10
        )
        mock_article_proc.complete_sps_pkg_ppx.assert_called_once_with(
            "USER", issue_proc_id_list=[10]
        )
        mock_article.exclude_invalid_records.assert_not_called()
        mock_article_proc.exclude_invalid_records.assert_not_called()

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], {"params": {
            "delete_article_which_is_duplicated": False,
            "delete_article_which_sps_pkg_is_missing": False,
            "delete_sps_pkg_which_ppx_is_missing": False,
        }})
        self.assertEqual(result[1]["operation"], "ArticleProc.complete_sps_pkg_ppx")

    @patch("proc.tasks.SPSPkg")
    @patch("proc.tasks.ArticleProc")
    @patch("proc.tasks.Article")
    @patch("proc.tasks.IssueProc")
    @patch("proc.tasks._get_user")
    def test_delete_sps_pkg_flags_trigger_sps_pkg_exclude_invalid_records(
        self, mock_get_user, mock_issue_proc, mock_article, mock_article_proc, mock_sps_pkg
    ):
        mock_get_user.return_value = "USER"
        mock_issue = MagicMock()
        mock_issue_proc_instance = MagicMock(issue=mock_issue, pid="ISSUE-PID")
        mock_issue_proc.objects.select_related.return_value.get.return_value = (
            mock_issue_proc_instance
        )
        mock_sps_pkg.exclude_invalid_records.return_value = {"deleted": [1]}

        result = tasks.task_fix_issue_articles(
            issue_proc_id=10,
            delete_sps_pkg_which_ppx_is_missing=True,
            delete_sps_pkg_which_is_duplicated=True,
        )

        mock_sps_pkg.exclude_invalid_records.assert_called_once_with(
            "USER", "ISSUE-PID", True, True
        )
        operations = [item.get("operation") for item in result if "operation" in item]
        self.assertIn("SPSPkg.exclude_invalid_records", operations)
        mock_article.exclude_invalid_records.assert_not_called()
        mock_article_proc.exclude_invalid_records.assert_not_called()

    @patch("proc.tasks.ArticleProc")
    @patch("proc.tasks.Article")
    @patch("proc.tasks.IssueProc")
    @patch("proc.tasks._get_user")
    def test_delete_article_flags_trigger_article_exclude_invalid_records(
        self, mock_get_user, mock_issue_proc, mock_article, mock_article_proc
    ):
        mock_get_user.return_value = "USER"
        mock_issue = MagicMock()
        mock_issue_proc.objects.select_related.return_value.get.return_value = (
            MagicMock(issue=mock_issue)
        )
        mock_article.exclude_invalid_records.return_value = {"deleted": [2]}

        result = tasks.task_fix_issue_articles(
            issue_proc_id=10,
            timeout=30,
            delete_article_which_sps_pkg_is_missing=True,
            delete_article_which_is_duplicated=True,
        )

        mock_article.exclude_invalid_records.assert_called_once_with(
            "USER", mock_issue, True, True, timeout=30
        )
        operations = [item.get("operation") for item in result if "operation" in item]
        self.assertIn("Article.exclude_invalid_records", operations)
        mock_article_proc.exclude_invalid_records.assert_not_called()

    @patch("proc.tasks.ArticleProc")
    @patch("proc.tasks.Article")
    @patch("proc.tasks.IssueProc")
    @patch("proc.tasks._get_user")
    def test_delete_article_proc_flags_trigger_article_proc_exclude_invalid_records(
        self, mock_get_user, mock_issue_proc, mock_article, mock_article_proc
    ):
        mock_get_user.return_value = "USER"
        mock_issue_proc.objects.select_related.return_value.get.return_value = (
            MagicMock(issue=MagicMock())
        )
        mock_article_proc.exclude_invalid_records.return_value = {"deleted": [3]}

        result = tasks.task_fix_issue_articles(
            issue_proc_id=10,
            delete_article_procs_which_sps_pkg_is_missing=True,
            delete_article_procs_which_is_duplicated=True,
        )

        mock_article_proc.exclude_invalid_records.assert_called_once_with(
            "USER", 10, True, True
        )
        operations = [item.get("operation") for item in result if "operation" in item]
        self.assertIn("ArticleProc.exclude_invalid_records", operations)

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

        result = tasks.task_fix_issue_articles(issue_proc_id=10)

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
        article.create_or_update_article_collections.assert_called_once_with(
            "USER", force_update=False
        )
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

        article.create_or_update_article_collections.assert_called_once_with(
            "USER", force_update=None
        )
        article.check_availability.assert_called_once_with(
            "USER", force_update=None, timeout=None
        )
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
