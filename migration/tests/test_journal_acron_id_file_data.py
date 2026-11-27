"""
Identificação dos fascículos com novidades a partir dos registros do
acron.id (IdFileRecord com todo=True).
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from collection.models import Collection
from migration.models import IdFileRecord, JournalAcronIdFile

User = get_user_model()

ISSUE_1 = "0034-891020040001"
ISSUE_2 = "0034-891020040002"


class JournalAcronIdFileDataTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tester")
        self.collection = Collection.get_or_create(
            acron="scl", name="SciELO Brasil", user=self.user
        )
        self.parent = JournalAcronIdFile.objects.create(
            collection=self.collection,
            journal_acron="abc",
            source_path="/bases-work/abc/abc.id",
            creator=self.user,
        )

    def create_record(self, item_pid, item_type="article", todo=False, data=None):
        return IdFileRecord.objects.create(
            parent=self.parent,
            item_type=item_type,
            item_pid=item_pid,
            data=data or {"v880": item_pid},
            todo=todo,
            creator=self.user,
        )

    def test_pending_issue_pids_are_issues_of_articles_with_todo(self):
        self.create_record(f"S{ISSUE_1}00001", todo=True)
        self.create_record(f"S{ISSUE_1}00002", todo=False)
        self.create_record(f"S{ISSUE_2}00001", todo=False)
        # registros de fascículo e de parágrafo não indicam artigos a migrar
        self.create_record(ISSUE_2, item_type="issue", todo=True)
        self.create_record(f"S{ISSUE_2}00001", item_type="paragraph", todo=True)

        data = self.parent.data

        self.assertEqual(data["issue_pids"], [ISSUE_1, ISSUE_2])
        self.assertEqual(data["pending_issue_pids"], [ISSUE_1])
        self.assertEqual(data["stats"]["total_id_file_records_to_migrate"], 1)

    def test_changed_record_becomes_todo(self):
        record = self.create_record(f"S{ISSUE_2}00001", todo=False)

        IdFileRecord.create_or_update(
            self.user, self.parent, "article", record.item_pid, {"v880": "novo"}
        )

        record.refresh_from_db()
        self.assertTrue(record.todo)
        self.assertEqual(self.parent.data["pending_issue_pids"], [ISSUE_2])

    def test_unchanged_record_keeps_todo_false(self):
        record = self.create_record(f"S{ISSUE_2}00001", todo=False)

        IdFileRecord.create_or_update(
            self.user, self.parent, "article", record.item_pid, dict(record.data)
        )

        record.refresh_from_db()
        self.assertFalse(record.todo)
        self.assertEqual(self.parent.data["pending_issue_pids"], [])

    def test_new_record_is_todo(self):
        IdFileRecord.create_or_update(
            self.user, self.parent, "article", f"S{ISSUE_1}00009", {"v880": "x"}
        )

        self.assertEqual(self.parent.data["pending_issue_pids"], [ISSUE_1])

    def test_document_records_to_migrate_filters_issue_and_todo(self):
        self.create_record(f"S{ISSUE_1}00001", todo=True)
        self.create_record(f"S{ISSUE_1}00002", todo=False)
        self.create_record(f"S{ISSUE_2}00001", todo=True)

        records = IdFileRecord.document_records_to_migrate(
            self.collection, ISSUE_1
        )
        self.assertEqual(records.count(), 2)
        self.assertEqual(
            list(records.filter(todo=True).values_list("item_pid", flat=True)),
            [f"S{ISSUE_1}00001"],
        )
