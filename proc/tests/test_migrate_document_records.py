"""
Seleção dos registros do acron.id (IdFileRecord) processados por
IssueProc.migrate_document_records: novidades, registros sem ArticleProc e
retomada pedida pelo usuário (status BLOCKED/PENDING).
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from collection.models import Collection
from migration.models import IdFileRecord, JournalAcronIdFile
from proc.models import ArticleProc, IssueProc, JournalProc
from tracker import choices as tracker_choices

User = get_user_model()

TODO = tracker_choices.PROGRESS_STATUS_TODO
REPROC = tracker_choices.PROGRESS_STATUS_REPROC
DONE = tracker_choices.PROGRESS_STATUS_DONE
BLOCKED = tracker_choices.PROGRESS_STATUS_BLOCKED
PENDING = tracker_choices.PROGRESS_STATUS_PENDING
IGNORED = tracker_choices.PROGRESS_STATUS_IGNORED

ISSUE_PID = "0034-891020040001"


def article_pid(order):
    return f"S{ISSUE_PID}{order:05d}"


class MigrateDocumentRecordsTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tester")
        self.collection = Collection.get_or_create(
            acron="scl", name="SciELO Brasil", user=self.user
        )
        self.journal_proc = JournalProc.objects.create(
            collection=self.collection, pid="0034-8910", acron="abc",
            creator=self.user,
        )
        self.issue_proc = IssueProc.objects.create(
            collection=self.collection, pid=ISSUE_PID,
            journal_proc=self.journal_proc, issue_folder="v1n1",
            docs_status=DONE, creator=self.user,
        )
        self.parent = JournalAcronIdFile.objects.create(
            collection=self.collection, journal_acron="abc",
            source_path="/bases-work/abc/abc.id", creator=self.user,
        )

    def create_record(self, order, todo=False):
        return IdFileRecord.objects.create(
            parent=self.parent, item_type="article", item_pid=article_pid(order),
            data={"v880": article_pid(order)}, todo=todo, creator=self.user,
        )

    def create_article_proc(self, order, migration_status=DONE):
        return ArticleProc.objects.create(
            collection=self.collection, pid=article_pid(order),
            issue_proc=self.issue_proc, migration_status=migration_status,
            creator=self.user,
        )

    def migrate(self, status=None, status_after_registration=None):
        """
        Executa migrate_document_records simulando o registro
        (ArticleProc.create_or_update): devolve o ArticleProc com o
        migration_status de ``status_after_registration`` (por pid) ou o
        atual.
        """
        processed_pids = []
        status_after_registration = status_after_registration or {}

        def create_or_update(issue_proc, user, pid, data, force_update):
            processed_pids.append(pid)
            obj, _ = ArticleProc.objects.get_or_create(
                collection=self.collection, pid=pid,
                defaults={"issue_proc": issue_proc, "creator": user},
            )
            if pid in status_after_registration:
                obj.migration_status = status_after_registration[pid]
                obj.save()
            return obj

        with patch.object(
            ArticleProc, "create_or_update", side_effect=create_or_update
        ), patch.object(
            JournalProc, "get_migrated_data", return_value={}
        ), patch.object(
            IssueProc, "get_migrated_data", return_value={}
        ), patch.object(
            IdFileRecord, "get_record_data", return_value={"data": {}}
        ):
            response = self.issue_proc.migrate_document_records(
                self.user, status=status
            )
        return response, processed_pids

    def test_routine_processes_records_with_news_and_without_article_proc(self):
        self.create_record(1, todo=True)
        self.create_article_proc(1)
        self.create_record(2, todo=False)
        self.create_article_proc(2)
        # sem ArticleProc (ex.: excluído por task_fix_issue_articles)
        self.create_record(3, todo=False)
        # registro anterior falhou: BLOCKED não é retomado pela rotina
        self.create_record(4, todo=False)
        self.create_article_proc(4, migration_status=BLOCKED)

        response, processed = self.migrate(status=[TODO, REPROC])

        self.assertIsNone(response["exception"])
        self.assertCountEqual(processed, [article_pid(1), article_pid(3)])
        self.assertFalse(
            IdFileRecord.objects.filter(todo=True).exists()
        )

    def test_explicit_status_retries_article_procs_with_that_status(self):
        self.create_record(1, todo=False)
        self.create_article_proc(1, migration_status=BLOCKED)
        self.create_record(2, todo=False)
        self.create_article_proc(2, migration_status=PENDING)
        self.create_record(3, todo=False)
        self.create_article_proc(3)

        _, processed = self.migrate(status=[BLOCKED])
        self.assertEqual(processed, [article_pid(1)])

        _, processed = self.migrate(status=[PENDING])
        self.assertEqual(processed, [article_pid(2)])

    def test_explicit_status_rereads_any_status(self):
        self.create_record(1, todo=False)
        self.create_article_proc(1, migration_status=DONE)
        self.create_record(2, todo=False)
        self.create_article_proc(2, migration_status=IGNORED)

        _, processed = self.migrate(status=[DONE])
        self.assertEqual(processed, [article_pid(1)])

        _, processed = self.migrate(status=[IGNORED])
        self.assertEqual(processed, [article_pid(2)])

    def test_todo_without_news_is_not_reread(self):
        # relê-lo resetaria as fases já concluídas
        self.create_record(1, todo=False)
        self.create_article_proc(1, migration_status=TODO)
        self.create_record(2, todo=False)
        self.create_article_proc(2, migration_status=REPROC)

        _, processed = self.migrate(status=[TODO, REPROC])

        self.assertEqual(processed, [])

    def test_returns_article_procs_reset_in_this_execution(self):
        self.create_record(1, todo=False)
        blocked = self.create_article_proc(1, migration_status=BLOCKED)
        self.create_record(2, todo=False)
        still_blocked = self.create_article_proc(2, migration_status=BLOCKED)

        response, _ = self.migrate(
            status=[BLOCKED],
            # registro retomado com sucesso: dados novos, processo resetado
            status_after_registration={article_pid(1): TODO},
        )

        self.assertEqual(response["reset_article_proc_ids"], [blocked.id])
        self.assertNotIn(still_blocked.id, response["reset_article_proc_ids"])

    def test_failed_record_keeps_todo(self):
        record = self.create_record(1, todo=True)

        with patch.object(
            ArticleProc, "create_or_update", side_effect=ValueError("falha")
        ), patch.object(
            JournalProc, "get_migrated_data", return_value={}
        ), patch.object(
            IssueProc, "get_migrated_data", return_value={}
        ), patch.object(
            IdFileRecord, "get_record_data", return_value={"data": {}}
        ):
            response = self.issue_proc.migrate_document_records(self.user)

        self.assertIn(article_pid(1), response["output"]["exceptions"])
        record.refresh_from_db()
        self.assertTrue(record.todo)

    def test_record_changed_during_processing_keeps_todo(self):
        record = self.create_record(1, todo=True)
        self.create_article_proc(1)

        def create_or_update(issue_proc, user, pid, data, force_update):
            # acron.id relido em paralelo: registro alterado
            IdFileRecord.create_or_update(
                user, self.parent, "article", pid, {"v880": "novo"}
            )
            return ArticleProc.objects.get(pid=pid)

        with patch.object(
            ArticleProc, "create_or_update", side_effect=create_or_update
        ), patch.object(
            JournalProc, "get_migrated_data", return_value={}
        ), patch.object(
            IssueProc, "get_migrated_data", return_value={}
        ), patch.object(
            IdFileRecord, "get_record_data", return_value={"data": {}}
        ):
            self.issue_proc.migrate_document_records(self.user)

        record.refresh_from_db()
        self.assertTrue(record.todo)
