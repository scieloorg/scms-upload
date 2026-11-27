"""
Testes unitários para as tasks Celery de periódicos (JOURNALS) em proc/tasks.py.

Cobre: task_migrate_and_publish (stub obsoleto), task_migrate_and_publish_journals,
task_migrate_and_publish_journals_by_collection, task_migrate_and_publish_journal,
task_publish_journals e task_publish_journal.

Toda a camada de persistência (TaskTracker, Collection, JournalProc,
UnexpectedEvent, migration_controller, get_api_data, JournalProc.fix_publication_status)
é mockada, já que o objetivo é validar a lógica de orquestração das tasks
(o que é agendado, com quais kwargs, e como exceções são capturadas) e não
o comportamento real dos modelos. Chamadas ``.delay``/``.apply_async`` para
tasks filhas também são sempre mockadas para não depender de um broker real.
"""

import unittest
from unittest.mock import DEFAULT, MagicMock, patch

from django.test import TestCase

import proc.tasks as tasks
from proc.models import BaseProc


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
    """Testa task_migrate_and_publish_journals_by_collection: registra os dados
    do site clássico, seleciona separadamente os JournalProc a migrar e a
    publicar e agenda task_migrate_and_publish_journal para cada um."""

    def setUp(self):
        patcher = patch.multiple(
            "proc.tasks",
            TaskTracker=DEFAULT,
            Collection=DEFAULT,
            get_api_data=DEFAULT,
            migration_controller=DEFAULT,
            create_or_update_migrated_journal=DEFAULT,
            JournalProc=DEFAULT,
            UnexpectedEvent=DEFAULT,
        )
        self.mocks = patcher.start()
        self.addCleanup(patcher.stop)

        apply_async_patcher = patch.object(
            tasks.task_migrate_and_publish_journal, "apply_async"
        )
        self.mock_apply_async = apply_async_patcher.start()
        self.addCleanup(apply_async_patcher.stop)

        self.mock_collection = MagicMock(acron="scl")
        self.mocks["Collection"].objects.get.return_value = self.mock_collection
        self.mocks["migration_controller"].get_classic_website.return_value = MagicMock()
        self.mocks["JournalProc"].select_items_to_process.return_value = set()

    def test_nothing_to_process_finishes_early_without_scheduling(self):
        tasks.task_migrate_and_publish_journals_by_collection(collection_acron="scl")

        self.mock_apply_async.assert_not_called()
        self.mocks["get_api_data"].assert_not_called()

        task_tracker_mock = self.mocks["TaskTracker"].create.return_value
        self.assertEqual(task_tracker_mock.total_to_process, 0)
        task_tracker_mock.finish.assert_called_once()

    def test_journal_acron_filter_and_status_are_used_in_selection(self):
        tasks.task_migrate_and_publish_journals_by_collection(
            collection_acron="scl", journal_acron="rbt"
        )

        self.mocks["JournalProc"].select_items_to_process.assert_called_once_with(
            self.mock_collection,
            ["REPROC", "TODO"],
            params={"acron": "rbt"},
            include_core_sync_demand=True,
        )

    def test_explicit_status_is_used_in_selection(self):
        tasks.task_migrate_and_publish_journals_by_collection(
            collection_acron="scl", status=["BLOCKED"]
        )

        # com status explícito, a demanda de sincronização não é incluída
        self.mocks["JournalProc"].select_items_to_process.assert_called_once_with(
            self.mock_collection,
            ["BLOCKED"],
            params={},
            include_core_sync_demand=False,
        )

    def test_collection_without_classic_website_skips_classic_reading(self):
        self.mocks["migration_controller"].get_classic_website.return_value = None

        tasks.task_migrate_and_publish_journals_by_collection(collection_acron="scl")

        self.mocks["create_or_update_migrated_journal"].assert_not_called()
        self.mocks["JournalProc"].select_items_to_process.assert_called_once()

    def test_force_update_forces_reading_title_records(self):
        tasks.task_migrate_and_publish_journals_by_collection(
            collection_acron="scl", force_update=True
        )
        args, _ = self.mocks["create_or_update_migrated_journal"].call_args
        self.assertTrue(args[3])

    def test_schedules_each_selected_item(self):
        self.mocks["JournalProc"].select_items_to_process.return_value = {3, 1, 2}
        self.mocks["get_api_data"].side_effect = [{"url": "qa"}, {"url": "public"}]

        tasks.task_migrate_and_publish_journals_by_collection(collection_acron="scl")

        self.assertEqual(self.mock_apply_async.call_count, 3)
        scheduled = [
            c.kwargs["kwargs"] for c in self.mock_apply_async.call_args_list
        ]
        self.assertEqual([k["journal_proc_id"] for k in scheduled], [1, 2, 3])
        # a decisão de migrar/publicar é tomada por item, na execução
        self.assertEqual(
            scheduled[2],
            dict(
                user_id=None,
                username=None,
                journal_proc_id=3,
                force_update=False,
                force_core_sync=False,
                collection_acron="scl",
                qa_api_data={"url": "qa"},
                public_api_data={"url": "public"},
                status=["REPROC", "TODO"],
            ),
        )
        task_tracker_mock = self.mocks["TaskTracker"].create.return_value
        self.assertEqual(task_tracker_mock.total_processed, 3)

    def test_force_core_sync_schedules_all_journals(self):
        self.mocks["JournalProc"].objects.filter.return_value.values_list.return_value = [5, 4]

        tasks.task_migrate_and_publish_journals_by_collection(
            collection_acron="scl", force_core_sync=True
        )

        self.mocks["JournalProc"].select_items_to_process.assert_not_called()
        ids = [
            c.kwargs["kwargs"]["journal_proc_id"]
            for c in self.mock_apply_async.call_args_list
        ]
        self.assertEqual(ids, [4, 5])

    def test_apply_async_exception_aborts_processing_and_records_exception(self):
        self.mocks["JournalProc"].select_items_to_process.return_value = {1, 2}
        self.mock_apply_async.side_effect = Exception("broker down")

        tasks.task_migrate_and_publish_journals_by_collection(collection_acron="scl")

        self.assertEqual(self.mock_apply_async.call_count, 1)
        task_tracker_mock = self.mocks["TaskTracker"].create.return_value
        task_tracker_mock.finish.assert_called_once()
        _, kwargs = task_tracker_mock.finish.call_args
        self.assertFalse(kwargs["completed"])
        self.assertIsInstance(kwargs["exception"], Exception)

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


def _journal_proc_mock(
    migration_status="DONE", qa_ws_status="TODO", public_ws_status="TODO", **kwargs
):
    kwargs.setdefault("needs_core_sync", False)
    journal_proc = MagicMock(
        migration_status=migration_status,
        qa_ws_status=qa_ws_status,
        public_ws_status=public_ws_status,
        **kwargs,
    )

    def publish(user, api_publish_callable, website_kind=None, **kw):
        # simula publicação bem-sucedida, como BaseProc.publish
        if website_kind == "QA":
            journal_proc.qa_ws_status = "DONE"
        else:
            journal_proc.public_ws_status = "DONE"
        return {"completed": True}

    journal_proc.publish.side_effect = publish

    def migrate(*args, **kw):
        # simula migração bem-sucedida
        journal_proc.migration_status = "DONE"

    journal_proc.create_or_update_item.side_effect = migrate
    # usa a lógica real de publicação em sequência (QA, depois PUBLIC)
    journal_proc.publish_on_websites.side_effect = (
        lambda *args, **kw: BaseProc.publish_on_websites(journal_proc, *args, **kw)
    )
    return journal_proc


class TaskMigrateAndPublishJournalTest(TestCase):
    """Testa task_migrate_and_publish_journal: migra um único JournalProc (site
    clássico ou core) e publica em sequência no QA e no PUBLIC."""

    def setUp(self):
        patcher = patch.multiple(
            "proc.tasks",
            JournalProc=DEFAULT,
            migration_controller=DEFAULT,
            fetch_and_create_journal=DEFAULT,
            UnexpectedEvent=DEFAULT,
        )
        self.mocks = patcher.start()
        self.addCleanup(patcher.stop)
        self.mocks["JournalProc"].get_status_to_publish.side_effect = (
            BaseProc.get_status_to_publish
        )

    def _run(self, journal_proc, **kwargs):
        self.mocks["JournalProc"].objects.get.return_value = journal_proc
        params = dict(
            journal_proc_id=1,
            collection_acron="scl",
            qa_api_data={"url": "qa"},
            public_api_data={"url": "public"},
        )
        params.update(kwargs)
        return tasks.task_migrate_and_publish_journal(**params)

    def test_migrates_from_classic_website_and_publishes_qa_then_public(self):
        journal_proc = _journal_proc_mock(migration_status="TODO")

        result = self._run(journal_proc)

        self.assertTrue(result)
        journal_proc.create_or_update_item.assert_called_once_with(
            None, False, self.mocks["migration_controller"].create_or_update_journal
        )
        self.mocks["fetch_and_create_journal"].assert_not_called()
        kinds = [c.kwargs["website_kind"] for c in journal_proc.publish.call_args_list]
        self.assertEqual(kinds, ["QA", "PUBLIC"])
        _, kwargs = journal_proc.start.return_value.finish.call_args
        self.assertTrue(kwargs["completed"])
        self.assertEqual(
            kwargs["detail"]["journal_data_source"], "classic website data"
        )

    def test_migrated_journal_is_only_published(self):
        journal_proc = _journal_proc_mock(qa_ws_status="REPROC", public_ws_status="DONE")

        result = self._run(journal_proc)

        self.assertTrue(result)
        journal_proc.create_or_update_item.assert_not_called()
        self.mocks["fetch_and_create_journal"].assert_not_called()
        kinds = [c.kwargs["website_kind"] for c in journal_proc.publish.call_args_list]
        # PUBLIC já está DONE e QA não altera public_ws_status neste mock
        self.assertEqual(kinds, ["QA"])

    def test_public_is_not_published_if_qa_fails(self):
        journal_proc = _journal_proc_mock()
        journal_proc.publish.side_effect = lambda *a, **kw: {"completed": False}

        result = self._run(journal_proc)

        self.assertFalse(result)
        kinds = [c.kwargs["website_kind"] for c in journal_proc.publish.call_args_list]
        self.assertEqual(kinds, ["QA"])
        _, kwargs = journal_proc.start.return_value.finish.call_args
        self.assertFalse(kwargs["completed"])
        self.assertEqual(
            kwargs["detail"]["publication"]["PUBLIC"], {"skipped": "qa_ws_status=TODO"}
        )

    def test_public_is_published_if_qa_is_ignored(self):
        journal_proc = _journal_proc_mock(qa_ws_status="IGNORED")

        self._run(journal_proc)

        kinds = [c.kwargs["website_kind"] for c in journal_proc.publish.call_args_list]
        self.assertEqual(kinds, ["PUBLIC"])

    def test_does_not_publish_when_status_does_not_require(self):
        journal_proc = _journal_proc_mock(qa_ws_status="DONE", public_ws_status="DONE")

        result = self._run(journal_proc)

        self.assertTrue(result)
        journal_proc.publish.assert_not_called()

    def test_force_update_republishes_done(self):
        journal_proc = _journal_proc_mock(qa_ws_status="DONE", public_ws_status="DONE")

        self._run(journal_proc, force_update=True)

        kinds = [c.kwargs["website_kind"] for c in journal_proc.publish.call_args_list]
        self.assertEqual(kinds, ["QA", "PUBLIC"])

    def test_does_not_publish_when_migration_is_not_done(self):
        journal_proc = _journal_proc_mock(migration_status="BLOCKED")

        result = self._run(journal_proc)

        self.assertFalse(result)
        journal_proc.publish.assert_not_called()
        _, kwargs = journal_proc.start.return_value.finish.call_args
        self.assertFalse(kwargs["completed"])
        self.assertEqual(kwargs["detail"]["migration_status"], "BLOCKED")

    def test_missing_api_data_skips_website(self):
        journal_proc = _journal_proc_mock()

        self._run(journal_proc, qa_api_data={"error": "unreachable"}, public_api_data=None)

        journal_proc.publish.assert_not_called()

    def test_force_core_sync_uses_fetch_and_create_journal(self):
        journal_proc = _journal_proc_mock(
            issn_electronic="1111-2222", issn_print="3333-4444"
        )

        self._run(journal_proc, force_core_sync=True)

        self.mocks["fetch_and_create_journal"].assert_called_once_with(
            None,
            collection_acron="scl",
            issn_electronic="1111-2222",
            issn_print="3333-4444",
            force_update=True,
        )
        journal_proc.create_or_update_item.assert_not_called()
        _, kwargs = journal_proc.start.return_value.finish.call_args
        self.assertEqual(kwargs["detail"]["journal_data_source"], "core data")

    def test_status_blocked_migrates_and_publishes_in_same_execution(self):
        # migração bem-sucedida deixa qa_ws_status=TODO, que não está em
        # status=["BLOCKED"], mas deve ser publicado na mesma execução
        journal_proc = _journal_proc_mock(
            migration_status="BLOCKED", qa_ws_status="DONE", public_ws_status="DONE"
        )

        def migrate(*args, **kwargs):
            journal_proc.migration_status = "DONE"
            journal_proc.qa_ws_status = "TODO"
            journal_proc.public_ws_status = "TODO"

        journal_proc.create_or_update_item.side_effect = migrate

        result = self._run(journal_proc, status=["BLOCKED"])

        self.assertTrue(result)
        kinds = [c.kwargs["website_kind"] for c in journal_proc.publish.call_args_list]
        self.assertEqual(kinds, ["QA", "PUBLIC"])

    def test_status_blocked_does_not_republish_done(self):
        journal_proc = _journal_proc_mock(
            migration_status="DONE", qa_ws_status="BLOCKED", public_ws_status="DONE"
        )

        self._run(journal_proc, status=["BLOCKED"])

        kinds = [c.kwargs["website_kind"] for c in journal_proc.publish.call_args_list]
        # QA bloqueado é republicado; PUBLIC (DONE) só porque QA o marca TODO
        # em BaseProc.publish, o que este mock não simula
        self.assertEqual(kinds, ["QA"])

    def test_journal_whose_status_changed_after_selection_is_not_migrated(self):
        # selecionado como TODO, mas já migrado (DONE) quando a tarefa executa
        journal_proc = _journal_proc_mock(qa_ws_status="DONE", public_ws_status="DONE")

        result = self._run(journal_proc)

        self.assertTrue(result)
        journal_proc.create_or_update_item.assert_not_called()
        journal_proc.publish.assert_not_called()

    def test_core_sync_demand_with_classic_data_migrates_from_classic(self):
        # por ora os dados do site clássico são os mais atuais
        journal_proc = _journal_proc_mock(
            needs_core_sync=True, issn_electronic="1111-2222", issn_print=None
        )

        self._run(journal_proc)

        journal_proc.create_or_update_item.assert_called_once()
        self.mocks["fetch_and_create_journal"].assert_not_called()

    def test_core_sync_demand_without_classic_data_fetches_core(self):
        journal_proc = _journal_proc_mock(
            needs_core_sync=True,
            migrated_data=None,
            issn_electronic="1111-2222",
            issn_print=None,
        )

        def fetched(*args, **kwargs):
            journal_proc.needs_core_sync = False

        self.mocks["fetch_and_create_journal"].side_effect = fetched

        result = self._run(journal_proc)

        self.assertTrue(result)
        self.mocks["fetch_and_create_journal"].assert_called_once()
        self.assertEqual(journal_proc.migration_status, "DONE")

    def test_journal_still_not_synchronized_after_core_fetch_becomes_blocked(self):
        journal_proc = _journal_proc_mock(
            needs_core_sync=True,
            migrated_data=None,
            issn_electronic="1111-2222",
            issn_print=None,
        )

        result = self._run(journal_proc)

        self.assertFalse(result)
        self.assertEqual(journal_proc.migration_status, "BLOCKED")
        journal_proc.publish.assert_not_called()

    def test_without_classic_website_data_and_issn_does_not_fetch_core(self):
        # sem ISSN, fetch_and_create_journal buscaria todos os periódicos da coleção
        journal_proc = _journal_proc_mock(
            migration_status="TODO",
            migrated_data=None,
            issn_electronic=None,
            issn_print=None,
        )

        result = self._run(journal_proc)

        self.assertFalse(result)
        self.mocks["fetch_and_create_journal"].assert_not_called()
        journal_proc.create_or_update_item.assert_not_called()
        self.assertEqual(journal_proc.migration_status, "PENDING")
        journal_proc.save.assert_called_once()
        journal_proc.publish.assert_not_called()

    def test_force_core_sync_without_issn_migrates_from_classic_website(self):
        journal_proc = _journal_proc_mock(issn_electronic=None, issn_print=None)

        self._run(journal_proc, force_core_sync=True)

        self.mocks["fetch_and_create_journal"].assert_not_called()
        journal_proc.create_or_update_item.assert_called_once()

    def test_journal_without_classic_website_data_is_migrated_from_core(self):
        journal_proc = _journal_proc_mock(
            migration_status="TODO",
            migrated_data=None,
            issn_electronic="1111-2222",
            issn_print=None,
        )

        self._run(journal_proc)

        self.mocks["fetch_and_create_journal"].assert_called_once()
        journal_proc.create_or_update_item.assert_not_called()

    def test_exception_during_migration_is_captured_via_event_finish(self):
        journal_proc = _journal_proc_mock(migration_status="TODO")
        journal_proc.create_or_update_item.side_effect = Exception("boom")

        result = self._run(journal_proc)

        self.assertFalse(result)
        finish_mock = journal_proc.start.return_value.finish
        finish_mock.assert_called_once()
        args, kwargs = finish_mock.call_args
        self.assertEqual(args[0], None)
        self.assertFalse(kwargs["completed"])
        self.assertIsInstance(kwargs["exception"], Exception)

    def test_exception_before_event_exists_falls_back_to_unexpected_event(self):
        self.mocks["JournalProc"].objects.get.side_effect = Exception("db down")

        result = tasks.task_migrate_and_publish_journal(journal_proc_id=99)

        self.assertFalse(result)
        self.mocks["UnexpectedEvent"].create.assert_called_once()
        _, kwargs = self.mocks["UnexpectedEvent"].create.call_args
        self.assertEqual(kwargs["item"], "99")
        self.assertEqual(
            kwargs["action"], "proc.tasks.task_migrate_and_publish_journal"
        )


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
