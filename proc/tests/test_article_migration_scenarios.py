"""
Cenários da migração de artigos executada pelas tarefas agendadas
(task_migrate_and_publish_articles → task_migrate_and_publish_articles_by_journal
→ task_migrate_and_publish_articles_by_issue), com banco real e as tarefas
encadeadas de forma síncrona.

Cobre:

- rotina (sem ``status``): percebe novidades do acron.id (registro alterado
  ou novo) e os itens marcados TODO/REPROC manualmente; não retoma itens
  BLOCKED/PENDING
- ``status`` explícito: processa somente os itens com os status pedidos
  (BLOCKED, PENDING ou outro, como DONE); os de status diferentes não são
  processados

São simulados somente o acesso ao site clássico (leitura do acron.id), o
registro dos dados do site clássico (``ArticleProc.create_or_update``) e as
fases pesadas da migração (``ArticleProc.migrate_article``).
"""

import json
import os
import shutil
import tempfile
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from collection.models import Collection
from migration import controller as migration_controller
from migration.models import IdFileRecord, JournalAcronIdFile
from proc import tasks
from proc.models import ArticleProc, IssueProc, JournalProc
from tracker import choices as tracker_choices

User = get_user_model()

TODO = tracker_choices.PROGRESS_STATUS_TODO
REPROC = tracker_choices.PROGRESS_STATUS_REPROC
DONE = tracker_choices.PROGRESS_STATUS_DONE
BLOCKED = tracker_choices.PROGRESS_STATUS_BLOCKED
PENDING = tracker_choices.PROGRESS_STATUS_PENDING
IGNORED = tracker_choices.PROGRESS_STATUS_IGNORED

COLLECTION_ACRON = "scl"
JOURNAL_ACRON = "abc"
JOURNAL_PID = "0034-8910"
ISSUE_PID = f"{JOURNAL_PID}20040001"


def article_pid(order):
    return f"S{ISSUE_PID}{order:05d}"


# migration_status dos artigos já registrados (xml_status e sps_pkg_status
# DONE): 1 e 2 migrados; 3 falhou (aguarda o usuário); 4 tem pendência
INITIAL_MIGRATION_STATUS = {
    1: DONE,
    2: DONE,
    3: BLOCKED,
    4: PENDING,
}


def fake_get_bases_work_acron_id_file_records(
    source_path, classic_website, registered=None
):
    """Lê o acron.id simulado: JSON {pid: registro}."""
    with open(source_path) as fp:
        records = json.load(fp)
    for pid, data in records.items():
        yield dict(item_type="article", item_pid=pid, data=data)


class ArticleMigrationScenariosTest(TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)
        media_root = os.path.join(self.tmpdir, "media")
        settings_override = override_settings(MEDIA_ROOT=media_root)
        settings_override.enable()
        self.addCleanup(settings_override.disable)

        bases_work_path = os.path.join(self.tmpdir, "bases-work")
        os.makedirs(os.path.join(bases_work_path, JOURNAL_ACRON))
        self.acron_id_path = os.path.join(
            bases_work_path, JOURNAL_ACRON, f"{JOURNAL_ACRON}.id"
        )
        self.classic_website = SimpleNamespace(
            classic_website_paths=SimpleNamespace(bases_work_path=bases_work_path)
        )

        self.user = User.objects.create_user(username="tester")
        self.collection = Collection.get_or_create(
            acron=COLLECTION_ACRON, name="SciELO Brasil", user=self.user
        )
        self.journal_proc = JournalProc.objects.create(
            collection=self.collection, pid=JOURNAL_PID, acron=JOURNAL_ACRON,
            creator=self.user,
        )
        self.issue_proc = IssueProc.objects.create(
            collection=self.collection, pid=ISSUE_PID,
            journal_proc=self.journal_proc, issue_folder="v1n1",
            docs_status=DONE, files_status=DONE,
            migration_status=DONE, qa_ws_status=IGNORED,
            public_ws_status=IGNORED, creator=self.user,
        )

        # acron.id já lido e registros já processados em execuções anteriores
        self.acron_id_records = {
            article_pid(order): {"v880": article_pid(order), "v12": "título"}
            for order in INITIAL_MIGRATION_STATUS
        }
        self.write_acron_id()
        with self.classic_website_patches():
            migration_controller.import_journal_acron_id_records(
                self.user, self.journal_proc, force_update=False
            )
        IdFileRecord.objects.update(todo=False)

        # dados do site clássico já registrados por pid (ver create_or_update)
        self.registered_data = dict(self.acron_id_records)
        for order, migration_status in INITIAL_MIGRATION_STATUS.items():
            ArticleProc.objects.create(
                collection=self.collection, pid=article_pid(order),
                issue_proc=self.issue_proc,
                xml_status=DONE, sps_pkg_status=DONE,
                migration_status=migration_status,
                qa_ws_status=IGNORED, public_ws_status=IGNORED,
                creator=self.user,
            )

    # ── simulações ──

    def write_acron_id(self):
        with open(self.acron_id_path, "w") as fp:
            json.dump(self.acron_id_records, fp, sort_keys=True)

    def change_acron_id_record(self, order):
        self.acron_id_records[article_pid(order)] = {
            "v880": article_pid(order), "v12": "título corrigido",
        }
        self.write_acron_id()

    def add_acron_id_record(self, order):
        self.acron_id_records[article_pid(order)] = {
            "v880": article_pid(order), "v12": "artigo novo",
        }
        self.write_acron_id()

    def classic_website_patches(self):
        stack = patch.multiple(
            migration_controller,
            get_classic_website=MagicMock(return_value=self.classic_website),
            get_bases_work_acron_id_file_records=MagicMock(
                side_effect=fake_get_bases_work_acron_id_file_records
            ),
        )
        return stack

    def create_or_update(self, issue_proc, user, pid, data, force_update):
        """
        Simula ArticleProc.create_or_update (register_classic_website_data):
        dados novos ou alterados resetam o processo (todas as fases TODO);
        dados inalterados mantêm os status.
        """
        obj, _ = ArticleProc.objects.get_or_create(
            collection=self.collection, pid=pid,
            defaults={
                "issue_proc": issue_proc, "creator": user,
                "qa_ws_status": IGNORED, "public_ws_status": IGNORED,
            },
        )
        if force_update or self.registered_data.get(pid) != data["article"]:
            self.registered_data[pid] = data["article"]
            obj.xml_status = TODO
            obj.sps_pkg_status = TODO
            obj.migration_status = TODO
            obj.save()
        return obj

    def run_migration(self, status=None):
        """
        Executa task_migrate_and_publish_articles com as subtarefas
        encadeadas de forma síncrona. Retorna os pids migrados
        (migrate_article) e os ids informados à publicação.
        """
        migrated_pids = []

        def migrate_article(article_proc, user, force_update):
            migrated_pids.append(article_proc.pid)
            article_proc.xml_status = DONE
            article_proc.sps_pkg_status = DONE
            article_proc.migration_status = DONE
            article_proc.save()
            return True

        def run_by_journal(**kwargs):
            return tasks.task_migrate_and_publish_articles_by_journal(**kwargs)

        def run_by_issue(**kwargs):
            return tasks.task_migrate_and_publish_articles_by_issue(**kwargs)

        record_data = (
            lambda record, journal_data=None, issue_data=None: {
                "data": {"article": record.data},
                "pid": record.item_pid,
                "todo": record.todo,
            }
        )

        with self.classic_website_patches(), patch(
            "proc.tasks.TaskTracker"
        ) as mock_task_tracker, patch(
            "proc.tasks.get_total_status_data", return_value={}
        ), patch(
            "proc.tasks.get_api_data", return_value={}
        ), patch(
            "proc.tasks.task_fix_issue_articles", return_value={}
        ), patch(
            "proc.tasks.task_publish_issue_articles"
        ) as mock_publish, patch.object(
            tasks.task_migrate_and_publish_articles_by_journal, "delay",
            side_effect=run_by_journal,
        ), patch.object(
            tasks.task_migrate_and_publish_articles_by_issue, "delay",
            side_effect=run_by_issue,
        ), patch.object(
            ArticleProc, "create_or_update", side_effect=self.create_or_update
        ), patch.object(
            ArticleProc, "migrate_article", autospec=True,
            side_effect=migrate_article,
        ), patch.object(
            IdFileRecord, "get_record_data", autospec=True,
            side_effect=record_data,
        ), patch.object(
            JournalProc, "get_migrated_data", return_value={}
        ), patch.object(
            IssueProc, "get_migrated_data", return_value={}
        ), patch.object(
            IssueProc, "migrate_document_files", return_value={}
        ):
            tasks.task_migrate_and_publish_articles(
                username=self.user.username,
                collection_acron=COLLECTION_ACRON,
                status=status,
            )

        # nenhuma tarefa foi interrompida
        tracker = mock_task_tracker.create.return_value
        for finish_call in tracker.finish.call_args_list:
            self.assertIsNone(finish_call.kwargs.get("exception"))
            self.assertTrue(finish_call.kwargs.get("completed"))

        migrated_ids_to_publish = []
        for publish_call in mock_publish.delay.call_args_list:
            migrated_ids_to_publish.extend(
                publish_call.kwargs["migrated_articleprocs_id_list"]
            )
        return migrated_pids, migrated_ids_to_publish

    def set_migration_status(self, order, **status):
        """Simula a alteração manual dos status na interface administrativa."""
        ArticleProc.objects.filter(pid=article_pid(order)).update(**status)

    def get_article_proc(self, order):
        return ArticleProc.objects.get(pid=article_pid(order))

    def assert_migrated(self, migrated_pids, orders):
        self.assertCountEqual(
            migrated_pids, [article_pid(order) for order in orders]
        )

    # ── rotina (status TODO/REPROC) ──

    def test_routine_without_news_processes_nothing(self):
        migrated_pids, migrated_ids = self.run_migration()

        # BLOCKED (3) e PENDING (4) não são retomados pela rotina
        self.assertEqual(migrated_pids, [])
        self.assertEqual(migrated_ids, [])
        self.assertEqual(self.get_article_proc(3).migration_status, BLOCKED)
        self.assertEqual(self.get_article_proc(4).migration_status, PENDING)

    def test_routine_perceives_changed_record_in_acron_id(self):
        self.change_acron_id_record(2)

        migrated_pids, migrated_ids = self.run_migration()

        self.assert_migrated(migrated_pids, [2])
        self.assertEqual(migrated_ids, [self.get_article_proc(2).id])
        self.assertEqual(self.get_article_proc(2).migration_status, DONE)
        self.assertFalse(IdFileRecord.objects.filter(todo=True).exists())
        self.assertEqual(self.get_article_proc(3).migration_status, BLOCKED)
        self.assertEqual(self.get_article_proc(4).migration_status, PENDING)

    def test_routine_perceives_new_record_in_acron_id(self):
        self.add_acron_id_record(5)

        migrated_pids, _ = self.run_migration()

        self.assert_migrated(migrated_pids, [5])
        self.assertEqual(self.get_article_proc(5).migration_status, DONE)
        self.assertFalse(IdFileRecord.objects.filter(todo=True).exists())

    def test_routine_perceives_changed_record_of_blocked_article(self):
        # registro corrigido no site clássico: o artigo BLOCKED volta a TODO
        self.change_acron_id_record(3)

        migrated_pids, _ = self.run_migration()

        self.assert_migrated(migrated_pids, [3])
        self.assertEqual(self.get_article_proc(3).migration_status, DONE)
        self.assertEqual(self.get_article_proc(4).migration_status, PENDING)

    def test_unchanged_acron_id_is_not_reread(self):
        self.run_migration()
        record = IdFileRecord.objects.get(item_pid=article_pid(1))

        migrated_pids, _ = self.run_migration()

        self.assertEqual(migrated_pids, [])
        record.refresh_from_db()
        self.assertFalse(record.todo)

    def test_routine_processes_article_marked_todo_manually(self):
        self.set_migration_status(1, migration_status=TODO)

        migrated_pids, migrated_ids = self.run_migration()

        self.assert_migrated(migrated_pids, [1])
        self.assertEqual(migrated_ids, [self.get_article_proc(1).id])
        self.assertEqual(self.get_article_proc(1).migration_status, DONE)

    def test_routine_processes_article_marked_reproc_manually(self):
        self.set_migration_status(
            2, xml_status=REPROC, sps_pkg_status=REPROC, migration_status=REPROC
        )

        migrated_pids, _ = self.run_migration()

        self.assert_migrated(migrated_pids, [2])
        self.assertEqual(self.get_article_proc(2).migration_status, DONE)

    def test_routine_processes_article_with_phase_marked_reproc_manually(self):
        # somente a fase do XML marcada para reprocessar
        self.set_migration_status(1, xml_status=REPROC)

        migrated_pids, _ = self.run_migration()

        self.assert_migrated(migrated_pids, [1])

    def test_routine_processes_todo_and_reproc_together(self):
        self.set_migration_status(1, migration_status=TODO)
        self.set_migration_status(2, migration_status=REPROC)

        migrated_pids, _ = self.run_migration()

        self.assert_migrated(migrated_pids, [1, 2])

    # ── status explícito ──

    def test_explicit_status_blocked_processes_only_blocked(self):
        # TODO manual (1) e PENDING (4) têm status diferente do pedido
        self.set_migration_status(1, migration_status=TODO)

        migrated_pids, migrated_ids = self.run_migration(status=[BLOCKED])

        self.assert_migrated(migrated_pids, [3])
        self.assertEqual(migrated_ids, [self.get_article_proc(3).id])
        self.assertEqual(self.get_article_proc(3).migration_status, DONE)
        self.assertEqual(self.get_article_proc(1).migration_status, TODO)
        self.assertEqual(self.get_article_proc(4).migration_status, PENDING)

    def test_explicit_status_pending_processes_only_pending(self):
        self.set_migration_status(2, migration_status=REPROC)

        migrated_pids, _ = self.run_migration(status=[PENDING])

        self.assert_migrated(migrated_pids, [4])
        self.assertEqual(self.get_article_proc(4).migration_status, DONE)
        self.assertEqual(self.get_article_proc(2).migration_status, REPROC)
        self.assertEqual(self.get_article_proc(3).migration_status, BLOCKED)

    def test_explicit_status_list_processes_all_listed_status(self):
        self.set_migration_status(1, migration_status=TODO)

        migrated_pids, _ = self.run_migration(status=[BLOCKED, PENDING])

        self.assert_migrated(migrated_pids, [3, 4])
        self.assertEqual(self.get_article_proc(1).migration_status, TODO)

    def test_explicit_other_status_processes_only_that_status(self):
        # DONE: refaz os já migrados; BLOCKED, PENDING e TODO ficam como estão
        self.set_migration_status(4, migration_status=TODO)

        migrated_pids, _ = self.run_migration(status=[DONE])

        self.assert_migrated(migrated_pids, [1, 2])
        self.assertEqual(self.get_article_proc(3).migration_status, BLOCKED)
        self.assertEqual(self.get_article_proc(4).migration_status, TODO)

    def test_explicit_status_resumes_from_phase_with_that_status(self):
        # falha na fase do pacote SPS: retomada com status=["BLOCKED"]
        self.set_migration_status(1, sps_pkg_status=BLOCKED, migration_status=TODO)

        migrated_pids, _ = self.run_migration(status=[BLOCKED])

        self.assert_migrated(migrated_pids, [1, 3])

    def test_explicit_status_without_matching_items_processes_nothing(self):
        migrated_pids, _ = self.run_migration(status=[REPROC])

        self.assertEqual(migrated_pids, [])
        self.assertEqual(self.get_article_proc(3).migration_status, BLOCKED)
        self.assertEqual(self.get_article_proc(4).migration_status, PENDING)

    def test_explicit_status_also_perceives_news_in_acron_id(self):
        # novidades do acron.id são migradas em toda execução, mesmo com
        # status explícito (o processo do artigo é resetado nesta execução)
        self.change_acron_id_record(1)

        migrated_pids, _ = self.run_migration(status=[PENDING])

        self.assert_migrated(migrated_pids, [1, 4])
        self.assertEqual(self.get_article_proc(3).migration_status, BLOCKED)
