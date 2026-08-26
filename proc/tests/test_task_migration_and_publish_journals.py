"""
Testes unitários para as tasks Celery de periódicos (JOURNALS) em proc/tasks.py.

Cobre: task_migrate_and_publish (stub obsoleto), task_migrate_and_publish_journals,
task_migrate_and_publish_journals_by_collection, task_publish_journals e
task_publish_journal.

Toda a camada de persistência (TaskTracker, Collection, JournalProc,
UnexpectedEvent, migration_controller, get_api_data, fix_publication_status)
é mockada, já que o objetivo é validar a lógica de orquestração das tasks
(o que é agendado, com quais kwargs, e como exceções são capturadas) e não
o comportamento real dos modelos. Chamadas ``.delay``/``.apply_async`` para
tasks filhas também são sempre mockadas para não depender de um broker real.
"""

import unittest
from unittest.mock import DEFAULT, MagicMock, patch

from django.test import TestCase

import proc.tasks as tasks


def _queryset(items):
    """Cria um MagicMock que se comporta como um QuerySet simples (count + iteração)."""
    qs = MagicMock()
    qs.count.return_value = len(items)
    qs.__iter__.return_value = iter(items)
    return qs


class TaskMigrateAndPublishDeprecatedTest(TestCase):
    """Testa o stub obsoleto task_migrate_and_publish: não deve levantar exceção nem
    executar nenhuma lógica real, apenas registrar mensagens de log."""

    def test_does_not_raise_and_logs_deprecation_messages(self):
        with self.assertLogs(level="INFO") as captured:
            result = tasks.task_migrate_and_publish()

        self.assertIsNone(result)
        joined = "\n".join(captured.output)
        self.assertIn("task_migrate_and_publish is discontinued", joined)
        self.assertIn("Use task_migrate_and_publish_journals", joined)
        self.assertIn("Use task_migrate_and_publish_issues", joined)
        self.assertIn("Use task_migrate_and_publish_articles", joined)


class TaskMigrateAndPublishJournalsTest(TestCase):
    """Testa o ponto de entrada task_migrate_and_publish_journals, que agenda
    task_migrate_and_publish_journals_by_collection para cada coleção."""

    @patch("proc.tasks.task_migrate_and_publish_journals_by_collection.delay")
    @patch("proc.tasks._get_collections")
    def test_schedules_by_collection_task_for_each_collection(
        self, mock_get_collections, mock_delay
    ):
        col1 = MagicMock(acron="scl")
        col2 = MagicMock(acron="arg")
        mock_get_collections.return_value = [col1, col2]

        tasks.task_migrate_and_publish_journals(
            user_id=None,
            username=None,
            collection_acron=None,
            journal_acron="rbt",
            force_update=True,
            status="TODO",
            force_import_acron_id_file=False,
            force_core_sync=False,
        )

        mock_get_collections.assert_called_once_with(None)
        self.assertEqual(mock_delay.call_count, 2)
        mock_delay.assert_any_call(
            user_id=None,
            username=None,
            collection_acron="scl",
            journal_acron="rbt",
            force_update=True,
            status="TODO",
            force_import_acron_id_file=False,
            force_core_sync=False,
        )
        mock_delay.assert_any_call(
            user_id=None,
            username=None,
            collection_acron="arg",
            journal_acron="rbt",
            force_update=True,
            status="TODO",
            force_import_acron_id_file=False,
            force_core_sync=False,
        )

    @patch("proc.tasks.task_migrate_and_publish_journals_by_collection.delay")
    @patch("proc.tasks._get_collections")
    def test_no_collections_schedules_nothing(self, mock_get_collections, mock_delay):
        mock_get_collections.return_value = []

        tasks.task_migrate_and_publish_journals(collection_acron="unknown")

        mock_delay.assert_not_called()

    @patch("proc.tasks.UnexpectedEvent")
    @patch("proc.tasks._get_collections")
    def test_unexpected_exception_is_captured_via_unexpected_event(
        self, mock_get_collections, mock_unexpected_event
    ):
        mock_get_collections.side_effect = Exception("boom")

        tasks.task_migrate_and_publish_journals(collection_acron="scl")

        mock_unexpected_event.create.assert_called_once()
        _, kwargs = mock_unexpected_event.create.call_args
        self.assertEqual(
            kwargs["action"], "proc.tasks.task_migrate_and_publish_journals"
        )
        self.assertEqual(kwargs["item"], "scl")


class TaskMigrateAndPublishJournalsByCollectionTest(TestCase):
    """Testa task_migrate_and_publish_journals_by_collection: migração de periódicos
    de uma coleção a partir do site clássico (ou da core, se force_core_sync) e o
    agendamento de task_publish_journal para QA e/ou PUBLIC."""

    def setUp(self):
        patcher = patch.multiple(
            "proc.tasks",
            TaskTracker=DEFAULT,
            Collection=DEFAULT,
            JournalProc=DEFAULT,
            get_api_data=DEFAULT,
            fix_publication_status=DEFAULT,
            migration_controller=DEFAULT,
            create_or_update_migrated_journal=DEFAULT,
            fetch_and_create_journal=DEFAULT,
            UnexpectedEvent=DEFAULT,
        )
        self.mocks = patcher.start()
        self.addCleanup(patcher.stop)

        apply_async_patcher = patch.object(tasks.task_publish_journal, "apply_async")
        self.mock_apply_async = apply_async_patcher.start()
        self.addCleanup(apply_async_patcher.stop)

        self.mock_collection = MagicMock(acron="scl")
        self.mocks["Collection"].objects.get.return_value = self.mock_collection
        self.mocks["migration_controller"].get_classic_website.return_value = MagicMock()

    def test_nothing_to_process_finishes_early_without_scheduling(self):
        self.mocks["JournalProc"].objects.filter.return_value = _queryset([])

        tasks.task_migrate_and_publish_journals_by_collection(collection_acron="scl")

        self.mock_apply_async.assert_not_called()
        self.mocks["get_api_data"].assert_not_called()

        task_tracker_mock = self.mocks["TaskTracker"].create.return_value
        self.assertEqual(task_tracker_mock.total_to_process, 0)
        task_tracker_mock.finish.assert_called_once()

    def test_journal_acron_filter_is_applied_to_journalproc_query(self):
        self.mocks["JournalProc"].objects.filter.return_value = _queryset([])

        tasks.task_migrate_and_publish_journals_by_collection(
            collection_acron="scl", journal_acron="rbt"
        )

        _, kwargs = self.mocks["JournalProc"].objects.filter.call_args
        self.assertEqual(kwargs.get("acron"), "rbt")
        self.assertEqual(kwargs.get("collection"), self.mock_collection)

    def test_happy_path_schedules_qa_and_public_publish(self):
        journal_proc = MagicMock(
            id=42, issn_electronic="1234-5678", issn_print="8765-4321"
        )
        self.mocks["JournalProc"].objects.filter.return_value = _queryset(
            [journal_proc]
        )
        self.mocks["get_api_data"].side_effect = [
            {"url": "qa"},
            {"url": "public"},
        ]

        tasks.task_migrate_and_publish_journals_by_collection(
            user_id=None,
            username=None,
            collection_acron="scl",
            force_update=False,
        )

        journal_proc.create_or_update_item.assert_called_once_with(
            None,
            False,
            self.mocks["migration_controller"].create_or_update_journal,
        )
        self.assertEqual(self.mock_apply_async.call_count, 2)
        self.mock_apply_async.assert_any_call(
            kwargs=dict(
                user_id=None,
                username=None,
                website_kind="QA",
                journal_proc_id=42,
                api_data={"url": "qa"},
                force_update=False,
            )
        )
        self.mock_apply_async.assert_any_call(
            kwargs=dict(
                user_id=None,
                username=None,
                website_kind="PUBLIC",
                journal_proc_id=42,
                api_data={"url": "public"},
                force_update=False,
            )
        )
        journal_proc.start.return_value.finish.assert_called_once_with(
            None,
            completed=True,
            detail={
                "journal_data_source": "classic website data",
                "task_publish_journal_on_qa_website": "scheduled",
                "task_publish_journal_on_public_website": "scheduled",
            },
        )
        task_tracker_mock = self.mocks["TaskTracker"].create.return_value
        self.assertEqual(task_tracker_mock.total_processed, 1)

    def test_qa_api_data_with_error_skips_qa_but_schedules_public(self):
        journal_proc = MagicMock(id=1)
        self.mocks["JournalProc"].objects.filter.return_value = _queryset(
            [journal_proc]
        )
        self.mocks["get_api_data"].side_effect = [
            {"error": "unreachable"},
            {"url": "public"},
        ]

        tasks.task_migrate_and_publish_journals_by_collection(collection_acron="scl")

        self.assertEqual(self.mock_apply_async.call_count, 1)
        called_kwargs = self.mock_apply_async.call_args.kwargs["kwargs"]
        self.assertEqual(called_kwargs["website_kind"], "PUBLIC")

    def test_falsy_api_data_skips_both_websites(self):
        journal_proc = MagicMock(id=1)
        self.mocks["JournalProc"].objects.filter.return_value = _queryset(
            [journal_proc]
        )
        self.mocks["get_api_data"].side_effect = [None, {}]

        tasks.task_migrate_and_publish_journals_by_collection(collection_acron="scl")

        self.mock_apply_async.assert_not_called()

    def test_force_core_sync_uses_fetch_and_create_journal(self):
        journal_proc = MagicMock(
            id=7, issn_electronic="1111-2222", issn_print="3333-4444"
        )
        self.mocks["JournalProc"].objects.filter.return_value = _queryset(
            [journal_proc]
        )
        self.mocks["get_api_data"].side_effect = [None, None]

        tasks.task_migrate_and_publish_journals_by_collection(
            user_id=None,
            username=None,
            collection_acron="scl",
            force_core_sync=True,
        )

        self.mocks["fetch_and_create_journal"].assert_called_once_with(
            None,
            collection_acron="scl",
            issn_electronic="1111-2222",
            issn_print="3333-4444",
            force_update=True,
        )
        journal_proc.create_or_update_item.assert_not_called()
        journal_proc.start.return_value.finish.assert_called_once_with(
            None,
            completed=True,
            detail={"journal_data_source": "core data"},
        )

    def test_per_item_exception_is_captured_and_loop_continues(self):
        failing = MagicMock(id=1)
        failing.create_or_update_item.side_effect = Exception("boom")
        succeeding = MagicMock(id=2)
        self.mocks["JournalProc"].objects.filter.return_value = _queryset(
            [failing, succeeding]
        )
        self.mocks["get_api_data"].side_effect = [None, None]

        tasks.task_migrate_and_publish_journals_by_collection(collection_acron="scl")

        failing.start.return_value.finish.assert_called_once()
        _, finish_kwargs = failing.start.return_value.finish.call_args
        self.assertFalse(finish_kwargs["completed"])
        self.assertIsInstance(finish_kwargs["exception"], Exception)
        self.assertEqual(finish_kwargs["detail"], {})

        succeeding.start.return_value.finish.assert_called_once_with(
            None,
            completed=True,
            detail={"journal_data_source": "classic website data"},
        )

        task_tracker_mock = self.mocks["TaskTracker"].create.return_value
        self.assertEqual(task_tracker_mock.total_processed, 1)

    def test_outer_exception_is_recorded_via_task_exec_finish(self):
        self.mocks["migration_controller"].get_classic_website.side_effect = Exception(
            "network down"
        )

        tasks.task_migrate_and_publish_journals_by_collection(collection_acron="scl")

        task_tracker_mock = self.mocks["TaskTracker"].create.return_value
        task_tracker_mock.finish.assert_called_once()
        _, kwargs = task_tracker_mock.finish.call_args
        self.assertFalse(kwargs["completed"])
        self.assertIsInstance(kwargs["exception"], Exception)


class TaskPublishJournalsTest(TestCase):
    """Testa task_publish_journals: para cada coleção x tipo de website (QA/PUBLIC)
    obtém os JournalProc pendentes via JournalProc.items_to_publish e agenda
    task_publish_journal para cada um."""

    def setUp(self):
        patcher = patch.multiple(
            "proc.tasks",
            TaskTracker=DEFAULT,
            JournalProc=DEFAULT,
            get_api_data=DEFAULT,
            fix_publication_status=DEFAULT,
            UnexpectedEvent=DEFAULT,
            _get_collections=DEFAULT,
        )
        self.mocks = patcher.start()
        self.addCleanup(patcher.stop)

        apply_async_patcher = patch.object(tasks.task_publish_journal, "apply_async")
        self.mock_apply_async = apply_async_patcher.start()
        self.addCleanup(apply_async_patcher.stop)

        self.created_trackers = []

        def _create_tracker(**kwargs):
            tracker_mock = MagicMock()
            self.created_trackers.append(tracker_mock)
            return tracker_mock

        self.mocks["TaskTracker"].create.side_effect = _create_tracker

    def test_schedules_publish_for_qa_and_public_pending_items(self):
        collection = MagicMock(acron="scl")
        self.mocks["_get_collections"].return_value = [collection]
        qa_item = MagicMock(id=1)
        public_item = MagicMock(id=2)
        self.mocks["get_api_data"].side_effect = [
            {"url": "qa"},
            {"url": "public"},
        ]
        self.mocks["JournalProc"].items_to_publish.side_effect = [
            _queryset([qa_item]),
            _queryset([public_item]),
        ]

        tasks.task_publish_journals(collection_acron="scl", verify=True)

        self.mocks["get_api_data"].assert_any_call(collection, "journal", "QA")
        self.mocks["get_api_data"].assert_any_call(collection, "journal", "PUBLIC")

        self.assertEqual(self.mock_apply_async.call_count, 2)
        self.mock_apply_async.assert_any_call(
            kwargs=dict(
                user_id=None,
                username=None,
                website_kind="QA",
                journal_proc_id=1,
                api_data={"url": "qa", "verify": True},
                force_update=False,
            )
        )
        self.mock_apply_async.assert_any_call(
            kwargs=dict(
                user_id=None,
                username=None,
                website_kind="PUBLIC",
                journal_proc_id=2,
                api_data={"url": "public", "verify": True},
                force_update=False,
            )
        )
        self.assertEqual(len(self.created_trackers), 2)
        for tracker_mock in self.created_trackers:
            self.assertEqual(tracker_mock.total_processed, 1)
            tracker_mock.finish.assert_called_once()

    def test_skips_website_kind_when_api_data_has_error_or_is_falsy(self):
        collection = MagicMock(acron="scl")
        self.mocks["_get_collections"].return_value = [collection]
        self.mocks["get_api_data"].side_effect = [
            {"error": "down"},
            None,
        ]

        tasks.task_publish_journals(collection_acron="scl")

        self.mocks["JournalProc"].items_to_publish.assert_not_called()
        self.mock_apply_async.assert_not_called()
        self.assertEqual(len(self.created_trackers), 0)

    def test_per_item_apply_async_exception_is_captured_and_loop_continues(self):
        collection = MagicMock(acron="scl")
        self.mocks["_get_collections"].return_value = [collection]
        item1 = MagicMock(id=1)
        item2 = MagicMock(id=2)
        self.mocks["get_api_data"].side_effect = [
            {"url": "qa"},
            {"error": "skip public"},
        ]
        self.mocks["JournalProc"].items_to_publish.return_value = _queryset(
            [item1, item2]
        )
        self.mock_apply_async.side_effect = [Exception("broker down"), None]

        tasks.task_publish_journals(collection_acron="scl")

        self.assertEqual(self.mock_apply_async.call_count, 2)
        self.mocks["UnexpectedEvent"].create.assert_called_once()
        self.assertEqual(len(self.created_trackers), 1)
        # somente item2 foi contabilizado (item1 lançou exceção no apply_async)
        self.assertEqual(self.created_trackers[0].total_processed, 1)

    def test_outer_exception_creates_unexpected_event(self):
        self.mocks["_get_collections"].side_effect = Exception("boom")

        tasks.task_publish_journals(collection_acron="scl", journal_acron="rbt")

        self.mocks["UnexpectedEvent"].create.assert_called_once()
        _, kwargs = self.mocks["UnexpectedEvent"].create.call_args
        self.assertEqual(kwargs["item"], "scl-rbt")
        self.assertEqual(kwargs["action"], "task_publish_journal")


class TaskPublishJournalTest(TestCase):
    """Testa task_publish_journal: publica um único JournalProc via JournalProc.publish
    e finaliza o evento de acompanhamento (ou cai para UnexpectedEvent se o próprio
    evento não pôde ser criado)."""

    @patch("proc.tasks.publish_journal")
    @patch("proc.tasks.JournalProc")
    def test_happy_path_publishes_and_finishes_event(
        self, mock_journal_proc_cls, mock_publish_journal
    ):
        journal_proc = MagicMock()
        mock_journal_proc_cls.objects.get.return_value = journal_proc

        tasks.task_publish_journal(
            user_id=None,
            username=None,
            website_kind="QA",
            journal_proc_id=10,
            api_data={"a": 1},
            force_update=True,
        )

        mock_journal_proc_cls.objects.get.assert_called_once_with(pk=10)
        journal_proc.publish.assert_called_once_with(
            None,
            mock_publish_journal,
            content_type="journal",
            website_kind="QA",
            api_data={"a": 1},
            force_update=True,
        )
        journal_proc.start.return_value.finish.assert_called_once_with(
            None, completed=True
        )

    @patch("proc.tasks.publish_journal")
    @patch("proc.tasks.JournalProc")
    def test_exception_during_publish_is_captured_via_event_finish(
        self, mock_journal_proc_cls, mock_publish_journal
    ):
        journal_proc = MagicMock()
        mock_journal_proc_cls.objects.get.return_value = journal_proc
        journal_proc.publish.side_effect = Exception("api error")

        tasks.task_publish_journal(
            user_id=None,
            username=None,
            website_kind="PUBLIC",
            journal_proc_id=11,
            api_data={},
            force_update=False,
        )

        finish_mock = journal_proc.start.return_value.finish
        finish_mock.assert_called_once()
        args, kwargs = finish_mock.call_args
        self.assertEqual(args[0], None)
        self.assertFalse(kwargs["completed"])
        self.assertIsInstance(kwargs["exception"], Exception)

    @patch("proc.tasks.UnexpectedEvent")
    @patch("proc.tasks.JournalProc")
    def test_exception_before_event_exists_falls_back_to_unexpected_event(
        self, mock_journal_proc_cls, mock_unexpected_event
    ):
        # JournalProc.objects.get falha ANTES de "event" ser atribuído: o
        # bloco except tenta event.finish(...), o que dispara
        # UnboundLocalError, capturado pelo except aninhado que cai para
        # UnexpectedEvent.create.
        mock_journal_proc_cls.objects.get.side_effect = Exception("db down")

        tasks.task_publish_journal(
            user_id=None,
            username=None,
            website_kind="QA",
            journal_proc_id=99,
            api_data={},
            force_update=False,
        )

        mock_unexpected_event.create.assert_called_once()
        _, kwargs = mock_unexpected_event.create.call_args
        self.assertEqual(kwargs["item"], "99")
        self.assertEqual(kwargs["action"], "proc.tasks.publish_journal")


if __name__ == "__main__":
    unittest.main()
