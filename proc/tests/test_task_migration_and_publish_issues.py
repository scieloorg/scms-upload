"""
Testes unitários das tasks Celery de fascículos (ISSUES) em proc/tasks.py:

- task_migrate_and_publish_issues
- task_migrate_and_publish_issues_by_collection
- task_publish_issues
- task_publish_issue

Todas as dependências externas (models, TaskTracker, funções de
proc.controller/migration.controller/publication.api) são mockadas, evitando
qualquer acesso real ao banco de dados ou a um broker Celery.
"""

from unittest.mock import MagicMock, patch

from django.test import TestCase

import proc.tasks as tasks


def _make_task_tracker_mock(mock_task_tracker_cls):
    """Cria um TaskTracker mockado com os atributos usados por TaskExecution."""
    mock_task_tracker = MagicMock()
    mock_task_tracker.total_to_process = 0
    mock_task_tracker.total_processed = 0
    mock_task_tracker_cls.create.return_value = mock_task_tracker
    return mock_task_tracker


def _make_queryset_mock(items):
    """Cria um MagicMock que se comporta como um queryset com count()/iteração."""
    qs = MagicMock()
    qs.count.return_value = len(items)
    qs.__iter__.return_value = iter(items)
    return qs


class TaskMigrateAndPublishIssuesTest(TestCase):
    """Testes para task_migrate_and_publish_issues (ponto de entrada de migração de fascículos)."""

    @patch.object(tasks.task_migrate_and_publish_issues_by_collection, "delay")
    @patch("proc.tasks._get_collections")
    def test_schedules_task_for_each_collection_with_overridden_collection_acron(
        self, mock_get_collections, mock_delay
    ):
        collection_scl = MagicMock(acron="scl")
        collection_arg = MagicMock(acron="arg")
        mock_get_collections.return_value = [collection_scl, collection_arg]

        tasks.task_migrate_and_publish_issues(
            user_id=None,
            username=None,
            collection_acron=None,
            journal_acron="abc",
            publication_year="2020",
            issue_folder="v1n1",
            status=None,
            force_update=True,
            force_migrate_document_records=False,
        )

        self.assertEqual(mock_delay.call_count, 2)
        first_kwargs = mock_delay.call_args_list[0].kwargs
        second_kwargs = mock_delay.call_args_list[1].kwargs
        self.assertEqual(first_kwargs["collection_acron"], "scl")
        self.assertEqual(second_kwargs["collection_acron"], "arg")
        self.assertEqual(first_kwargs["journal_acron"], "abc")
        self.assertEqual(first_kwargs["publication_year"], "2020")
        self.assertEqual(first_kwargs["issue_folder"], "v1n1")
        self.assertTrue(first_kwargs["force_update"])
        self.assertFalse(first_kwargs["force_migrate_document_records"])

    @patch.object(tasks.task_migrate_and_publish_issues_by_collection, "delay")
    @patch("proc.tasks._get_collections")
    def test_no_collections_schedules_nothing(self, mock_get_collections, mock_delay):
        mock_get_collections.return_value = []

        tasks.task_migrate_and_publish_issues(collection_acron="non-existent")

        mock_delay.assert_not_called()

    @patch("proc.tasks.UnexpectedEvent")
    @patch.object(tasks.task_migrate_and_publish_issues_by_collection, "delay")
    @patch("proc.tasks._get_collections")
    def test_exception_is_captured_by_unexpected_event(
        self, mock_get_collections, mock_delay, mock_unexpected_event
    ):
        mock_get_collections.side_effect = RuntimeError("boom")

        tasks.task_migrate_and_publish_issues(collection_acron="scl")

        mock_delay.assert_not_called()
        mock_unexpected_event.create.assert_called_once()
        call_kwargs = mock_unexpected_event.create.call_args.kwargs
        self.assertEqual(
            call_kwargs["action"], "proc.tasks.task_migrate_and_publish_issues"
        )
        self.assertIsInstance(call_kwargs["e"], RuntimeError)


class TaskMigrateAndPublishIssuesByCollectionTest(TestCase):
    """Testes para task_migrate_and_publish_issues_by_collection (migração e agendamento de publicação por coleção)."""

    @patch.object(tasks.task_publish_issue, "apply_async")
    @patch("proc.tasks.migrate_issue")
    @patch("proc.tasks.get_api_data")
    @patch("proc.tasks.IssueProc")
    @patch("proc.tasks.fix_publication_status")
    @patch("proc.tasks.create_or_update_migrated_issue")
    @patch("proc.tasks.Collection")
    @patch("proc.tasks.migration_controller")
    @patch("proc.tasks.TaskTracker")
    def test_happy_path_schedules_publish_issue_for_qa_and_public(
        self,
        mock_task_tracker_cls,
        mock_migration_controller,
        mock_collection_cls,
        mock_create_or_update_migrated_issue,
        mock_fix_publication_status,
        mock_issue_proc_cls,
        mock_get_api_data,
        mock_migrate_issue,
        mock_apply_async,
    ):
        _make_task_tracker_mock(mock_task_tracker_cls)

        mock_classic_website = MagicMock()
        mock_migration_controller.get_classic_website.return_value = mock_classic_website

        mock_collection = MagicMock()
        mock_collection_cls.objects.get.return_value = mock_collection

        issue_proc_1 = MagicMock(id=1)
        issue_proc_2 = MagicMock(id=2)
        mock_issue_proc_cls.objects.filter.return_value = _make_queryset_mock(
            [issue_proc_1, issue_proc_2]
        )

        mock_get_api_data.side_effect = [
            {"qa": True},  # QA
            {"public": True},  # PUBLIC
        ]

        tasks.task_migrate_and_publish_issues_by_collection(
            user_id=None,
            username=None,
            collection_acron="scl",
            journal_acron="abc",
            force_update=True,
        )

        mock_migration_controller.get_classic_website.assert_called_once_with("scl")
        mock_collection_cls.objects.get.assert_called_once_with(acron="scl")
        mock_create_or_update_migrated_issue.assert_called_once_with(
            None, mock_collection, mock_classic_website, True
        )
        mock_fix_publication_status.assert_called_once_with(mock_collection)

        self.assertEqual(mock_migrate_issue.call_count, 2)
        mock_migrate_issue.assert_any_call(None, issue_proc_1, True)
        mock_migrate_issue.assert_any_call(None, issue_proc_2, True)

        self.assertEqual(mock_apply_async.call_count, 4)
        kwargs_list = [c.kwargs["kwargs"] for c in mock_apply_async.call_args_list]
        qa_calls = [k for k in kwargs_list if k["website_kind"] == "QA"]
        public_calls = [k for k in kwargs_list if k["website_kind"] == "PUBLIC"]
        self.assertEqual(len(qa_calls), 2)
        self.assertEqual(len(public_calls), 2)
        self.assertEqual(qa_calls[0]["api_data"], {"qa": True})
        self.assertEqual(public_calls[0]["api_data"], {"public": True})
        self.assertTrue(qa_calls[0]["force_update"])
        self.assertIn(qa_calls[0]["issue_proc_id"], (1, 2))
        self.assertIn(public_calls[0]["issue_proc_id"], (1, 2))

    @patch.object(tasks.task_publish_issue, "apply_async")
    @patch("proc.tasks.migrate_issue")
    @patch("proc.tasks.get_api_data")
    @patch("proc.tasks.IssueProc")
    @patch("proc.tasks.fix_publication_status")
    @patch("proc.tasks.create_or_update_migrated_issue")
    @patch("proc.tasks.Collection")
    @patch("proc.tasks.migration_controller")
    @patch("proc.tasks.TaskTracker")
    def test_no_items_short_circuits_without_migrating_or_publishing(
        self,
        mock_task_tracker_cls,
        mock_migration_controller,
        mock_collection_cls,
        mock_create_or_update_migrated_issue,
        mock_fix_publication_status,
        mock_issue_proc_cls,
        mock_get_api_data,
        mock_migrate_issue,
        mock_apply_async,
    ):
        mock_task_tracker = _make_task_tracker_mock(mock_task_tracker_cls)
        mock_collection_cls.objects.get.return_value = MagicMock()
        mock_issue_proc_cls.objects.filter.return_value = _make_queryset_mock([])

        tasks.task_migrate_and_publish_issues_by_collection(collection_acron="scl")

        # create_or_update_migrated_issue e fix_publication_status rodam ANTES
        # da checagem de "nada a processar", portanto devem ter sido chamados.
        mock_create_or_update_migrated_issue.assert_called_once()
        mock_fix_publication_status.assert_called_once()

        # já a checagem de itens interrompe o fluxo antes de buscar api_data,
        # migrar ou agendar publicação.
        mock_get_api_data.assert_not_called()
        mock_migrate_issue.assert_not_called()
        mock_apply_async.assert_not_called()
        mock_task_tracker.finish.assert_called_once()

    @patch.object(tasks.task_publish_issue, "apply_async")
    @patch("proc.tasks.migrate_issue")
    @patch("proc.tasks.get_api_data")
    @patch("proc.tasks.IssueProc")
    @patch("proc.tasks.fix_publication_status")
    @patch("proc.tasks.create_or_update_migrated_issue")
    @patch("proc.tasks.Collection")
    @patch("proc.tasks.migration_controller")
    @patch("proc.tasks.TaskTracker")
    def test_exception_in_one_item_does_not_stop_loop(
        self,
        mock_task_tracker_cls,
        mock_migration_controller,
        mock_collection_cls,
        mock_create_or_update_migrated_issue,
        mock_fix_publication_status,
        mock_issue_proc_cls,
        mock_get_api_data,
        mock_migrate_issue,
        mock_apply_async,
    ):
        mock_task_tracker = _make_task_tracker_mock(mock_task_tracker_cls)
        mock_collection_cls.objects.get.return_value = MagicMock()

        issue_proc_1 = MagicMock(id=1)
        issue_proc_2 = MagicMock(id=2)
        mock_issue_proc_cls.objects.filter.return_value = _make_queryset_mock(
            [issue_proc_1, issue_proc_2]
        )

        mock_get_api_data.side_effect = [{"qa": True}, {"public": True}]
        # falha ao migrar o primeiro issue_proc; o segundo é migrado normalmente
        mock_migrate_issue.side_effect = [RuntimeError("fail issue 1"), None]

        tasks.task_migrate_and_publish_issues_by_collection(collection_acron="scl")

        self.assertEqual(mock_migrate_issue.call_count, 2)

        # apenas o issue_proc_2 (que não falhou) é agendado para publicação
        # (QA + PUBLIC = 2 chamadas)
        self.assertEqual(mock_apply_async.call_count, 2)
        for call in mock_apply_async.call_args_list:
            self.assertEqual(call.kwargs["kwargs"]["issue_proc_id"], 2)

        # a exceção do primeiro item é capturada via task_exec.add_exception,
        # refletida no detail passado a task_tracker.finish (completed=False)
        mock_task_tracker.finish.assert_called_once()
        finish_call_kwargs = mock_task_tracker.finish.call_args.kwargs
        self.assertFalse(finish_call_kwargs["completed"])
        self.assertEqual(len(finish_call_kwargs["detail"]["exceptions"]), 1)

    @patch.object(tasks.task_publish_issue, "apply_async")
    @patch("proc.tasks.migrate_issue")
    @patch("proc.tasks.get_api_data")
    @patch("proc.tasks.IssueProc")
    @patch("proc.tasks.fix_publication_status")
    @patch("proc.tasks.create_or_update_migrated_issue")
    @patch("proc.tasks.Collection")
    @patch("proc.tasks.migration_controller")
    @patch("proc.tasks.TaskTracker")
    def test_outer_exception_is_captured_by_task_exec_finish(
        self,
        mock_task_tracker_cls,
        mock_migration_controller,
        mock_collection_cls,
        mock_create_or_update_migrated_issue,
        mock_fix_publication_status,
        mock_issue_proc_cls,
        mock_get_api_data,
        mock_migrate_issue,
        mock_apply_async,
    ):
        mock_task_tracker = _make_task_tracker_mock(mock_task_tracker_cls)
        mock_migration_controller.get_classic_website.side_effect = RuntimeError(
            "classic website unreachable"
        )

        tasks.task_migrate_and_publish_issues_by_collection(collection_acron="scl")

        mock_create_or_update_migrated_issue.assert_not_called()
        mock_migrate_issue.assert_not_called()
        mock_apply_async.assert_not_called()

        mock_task_tracker.finish.assert_called_once()
        finish_kwargs = mock_task_tracker.finish.call_args.kwargs
        self.assertFalse(finish_kwargs["completed"])
        self.assertIsInstance(finish_kwargs["exception"], RuntimeError)


class TaskPublishIssuesTest(TestCase):
    """Testes para task_publish_issues (agendamento de publicação de fascículos pendentes nos sites QA/PUBLIC)."""

    @patch.object(tasks.task_publish_issue, "apply_async")
    @patch("proc.tasks.IssueProc")
    @patch("proc.tasks.get_api_data")
    @patch("proc.tasks.fix_publication_status")
    @patch("proc.tasks._get_collections")
    @patch("proc.tasks.TaskTracker")
    def test_schedules_publish_issue_for_qa_and_public_per_collection(
        self,
        mock_task_tracker_cls,
        mock_get_collections,
        mock_fix_publication_status,
        mock_get_api_data,
        mock_issue_proc_cls,
        mock_apply_async,
    ):
        _make_task_tracker_mock(mock_task_tracker_cls)
        collection = MagicMock()
        mock_get_collections.return_value = [collection]

        mock_get_api_data.side_effect = [
            {"qa": True},  # QA
            {"public": True},  # PUBLIC
        ]

        issue_proc_qa = MagicMock(id=10)
        issue_proc_public = MagicMock(id=20)
        mock_issue_proc_cls.items_to_publish.side_effect = [
            _make_queryset_mock([issue_proc_qa]),
            _make_queryset_mock([issue_proc_public]),
        ]

        tasks.task_publish_issues(collection_acron="scl", force_update=True)

        mock_fix_publication_status.assert_called_once_with(collection)
        self.assertEqual(mock_apply_async.call_count, 2)
        kwargs_list = [c.kwargs["kwargs"] for c in mock_apply_async.call_args_list]

        self.assertEqual(kwargs_list[0]["website_kind"], "QA")
        self.assertEqual(kwargs_list[0]["issue_proc_id"], 10)
        self.assertEqual(kwargs_list[0]["api_data"]["qa"], True)
        self.assertTrue(kwargs_list[0]["force_update"])

        self.assertEqual(kwargs_list[1]["website_kind"], "PUBLIC")
        self.assertEqual(kwargs_list[1]["issue_proc_id"], 20)
        self.assertEqual(kwargs_list[1]["api_data"]["public"], True)

    @patch.object(tasks.task_publish_issue, "apply_async")
    @patch("proc.tasks.IssueProc")
    @patch("proc.tasks.get_api_data")
    @patch("proc.tasks.fix_publication_status")
    @patch("proc.tasks._get_collections")
    @patch("proc.tasks.TaskTracker")
    def test_skips_website_kind_when_api_data_missing_or_has_error(
        self,
        mock_task_tracker_cls,
        mock_get_collections,
        mock_fix_publication_status,
        mock_get_api_data,
        mock_issue_proc_cls,
        mock_apply_async,
    ):
        collection = MagicMock()
        mock_get_collections.return_value = [collection]
        # QA sem dados (falsy), PUBLIC com erro reportado pela API
        mock_get_api_data.side_effect = [None, {"error": "unreachable"}]

        tasks.task_publish_issues(collection_acron="scl")

        mock_issue_proc_cls.items_to_publish.assert_not_called()
        mock_apply_async.assert_not_called()
        mock_task_tracker_cls.create.assert_not_called()

    @patch.object(tasks.task_publish_issue, "apply_async")
    @patch("proc.tasks.IssueProc")
    @patch("proc.tasks.get_api_data")
    @patch("proc.tasks.fix_publication_status")
    @patch("proc.tasks._get_collections")
    @patch("proc.tasks.TaskTracker")
    def test_exception_scheduling_one_item_does_not_stop_others(
        self,
        mock_task_tracker_cls,
        mock_get_collections,
        mock_fix_publication_status,
        mock_get_api_data,
        mock_issue_proc_cls,
        mock_apply_async,
    ):
        mock_task_tracker = _make_task_tracker_mock(mock_task_tracker_cls)
        collection = MagicMock()
        mock_get_collections.return_value = [collection]
        # QA com dados válidos; PUBLIC sem dados (para simplificar o cenário
        # a um único par collection x website_kind)
        mock_get_api_data.side_effect = [{"qa": True}, None]

        issue_proc_1 = MagicMock(id=1)
        issue_proc_2 = MagicMock(id=2)
        mock_issue_proc_cls.items_to_publish.return_value = _make_queryset_mock(
            [issue_proc_1, issue_proc_2]
        )

        mock_apply_async.side_effect = [RuntimeError("broker down"), None]

        tasks.task_publish_issues(collection_acron="scl")

        self.assertEqual(mock_apply_async.call_count, 2)
        # apenas o segundo item (que não levantou exceção) é contabilizado
        # como processado; a exceção do primeiro é registrada via
        # task_exec.add_exception, sem interromper o loop.
        self.assertEqual(mock_task_tracker.total_processed, 1)


class TaskPublishIssueTest(TestCase):
    """Testes para task_publish_issue (publicação de um único fascículo via API)."""

    @patch("proc.tasks.UnexpectedEvent")
    @patch("proc.tasks.publish_issue")
    @patch("proc.tasks.IssueProc")
    def test_happy_path_publishes_and_finishes_event(
        self, mock_issue_proc_cls, mock_publish_issue, mock_unexpected_event
    ):
        issue_proc = MagicMock()
        event = MagicMock()
        issue_proc.start.return_value = event
        mock_issue_proc_cls.objects.get.return_value = issue_proc

        tasks.task_publish_issue(
            user_id=None,
            username=None,
            website_kind="QA",
            issue_proc_id=99,
            api_data={"foo": "bar"},
            force_update=True,
        )

        mock_issue_proc_cls.objects.get.assert_called_once_with(pk=99)
        issue_proc.start.assert_called_once_with(None, "proc.tasks.publish_issue")
        issue_proc.publish.assert_called_once_with(
            None,
            mock_publish_issue,
            content_type="issue",
            website_kind="QA",
            api_data={"foo": "bar"},
            force_update=True,
        )
        event.finish.assert_called_once_with(user=None, completed=True)
        mock_unexpected_event.create.assert_not_called()

    @patch("proc.tasks.UnexpectedEvent")
    @patch("proc.tasks.publish_issue")
    @patch("proc.tasks.IssueProc")
    def test_publish_failure_is_captured_by_event_finish(
        self, mock_issue_proc_cls, mock_publish_issue, mock_unexpected_event
    ):
        issue_proc = MagicMock()
        event = MagicMock()
        issue_proc.start.return_value = event
        issue_proc.publish.side_effect = RuntimeError("api down")
        mock_issue_proc_cls.objects.get.return_value = issue_proc

        tasks.task_publish_issue(
            user_id=None,
            username=None,
            website_kind="PUBLIC",
            issue_proc_id=5,
            api_data={},
            force_update=False,
        )

        event.finish.assert_called_once()
        finish_kwargs = event.finish.call_args.kwargs
        self.assertEqual(finish_kwargs["user"], None)
        self.assertFalse(finish_kwargs["completed"])
        self.assertIsInstance(finish_kwargs["exception"], RuntimeError)
        mock_unexpected_event.create.assert_not_called()

    @patch("proc.tasks.UnexpectedEvent")
    @patch("proc.tasks.publish_issue")
    @patch("proc.tasks.IssueProc")
    def test_start_failure_falls_back_to_unexpected_event(
        self, mock_issue_proc_cls, mock_publish_issue, mock_unexpected_event
    ):
        # issue_proc.start() falha antes que "event" seja atribuído, portanto
        # o bloco except interno (event.finish) também falha (NameError) e
        # o fallback UnexpectedEvent.create deve ser usado.
        issue_proc = MagicMock()
        issue_proc.start.side_effect = RuntimeError("cannot start operation")
        mock_issue_proc_cls.objects.get.return_value = issue_proc

        tasks.task_publish_issue(
            user_id=None,
            username=None,
            website_kind="QA",
            issue_proc_id=7,
            api_data={},
            force_update=False,
        )

        issue_proc.publish.assert_not_called()
        mock_unexpected_event.create.assert_called_once()
        call_kwargs = mock_unexpected_event.create.call_args.kwargs
        self.assertEqual(call_kwargs["item"], "7")
        self.assertEqual(call_kwargs["action"], "proc.tasks.publish_issue")
        self.assertIsInstance(call_kwargs["e"], RuntimeError)
        self.assertEqual(call_kwargs["detail"]["issue_proc_id"], 7)
        self.assertEqual(call_kwargs["detail"]["website_kind"], "QA")
