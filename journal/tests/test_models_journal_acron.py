"""
Testes para Journal.update_journal_acron e Journal.get_acron.

Journal.journal_acron só é preenchido quando o acrônimo é o mesmo em
todas as coleções (JournalProc); caso contrário, fica vazio e o acrônimo
deve ser obtido de JournalProc, a depender da coleção.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from collection.models import Collection
from journal.models import Journal
from proc.models import JournalProc


class JournalAcronTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="user")
        self.scl = Collection.objects.create(creator=self.user, acron="scl")
        self.psi = Collection.objects.create(creator=self.user, acron="psi")
        self.journal = Journal.objects.create(creator=self.user)

    def create_journal_proc(self, collection, acron):
        journal_proc = JournalProc.objects.create(
            creator=self.user, collection=collection, pid=f"{collection.acron}-pid"
        )
        journal_proc.update(user=self.user, journal=self.journal, acron=acron)
        return journal_proc

    def test_one_collection_fills_journal_acron(self):
        self.create_journal_proc(self.scl, "pusp")

        self.journal.refresh_from_db()
        self.assertEqual(self.journal.journal_acron, "pusp")
        self.assertEqual(self.journal.get_acron(), "pusp")
        self.assertEqual(self.journal.get_acron(self.scl), "pusp")

    def test_collections_with_same_acron_fill_journal_acron(self):
        self.create_journal_proc(self.scl, "rsp")
        self.create_journal_proc(self.psi, "rsp")

        self.journal.refresh_from_db()
        self.assertEqual(self.journal.journal_acron, "rsp")

    def test_collections_with_different_acrons_empty_journal_acron(self):
        self.create_journal_proc(self.scl, "pusp")
        self.create_journal_proc(self.psi, "psicousp")

        self.journal.refresh_from_db()
        self.assertIsNone(self.journal.journal_acron)
        self.assertEqual(self.journal.get_acron(self.scl), "pusp")
        self.assertEqual(self.journal.get_acron(self.psi), "psicousp")

    def test_missing_fields_does_not_report_acron_if_found_in_journal_proc(self):
        self.create_journal_proc(self.scl, "pusp")
        self.create_journal_proc(self.psi, "psicousp")

        self.journal.refresh_from_db()
        self.assertNotIn("Journal Acronym", [str(i) for i in self.journal.missing_fields])
