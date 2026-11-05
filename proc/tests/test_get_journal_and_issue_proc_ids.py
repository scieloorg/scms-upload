from django.contrib.auth import get_user_model
from django.test import TestCase

from collection.models import Collection
from proc.models import ArticleProc, IssueProc, JournalProc
from tracker import choices as tracker_choices

User = get_user_model()


class GetJournalAndIssueProcIdsTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tester")
        self.collection = Collection.get_or_create(
            acron="scl", name="SciELO Brasil", user=self.user
        )

    def create_journal_proc(self, pid, acron=None):
        return JournalProc.objects.create(
            collection=self.collection,
            pid=pid,
            acron=acron,
            creator=self.user,
            updated_by=self.user,
        )

    def create_issue_proc(self, pid, journal_proc=None):
        return IssueProc.objects.create(
            collection=self.collection,
            pid=pid,
            journal_proc=journal_proc,
            issue_folder=pid,
            creator=self.user,
            updated_by=self.user,
        )

    def create_article_proc(self, pid, issue_proc=None):
        return ArticleProc.objects.create(
            collection=self.collection,
            pid=pid,
            issue_proc=issue_proc,
            creator=self.user,
            updated_by=self.user,
        )

    def get_items(self):
        return ArticleProc.get_journal_and_issue_proc_ids(
            collection_acron_list=["scl"],
            status_list=[tracker_choices.PROGRESS_STATUS_TODO],
        )

    def test_ignores_records_without_journal_proc(self):
        journal = self.create_journal_proc("J1", acron="abc")
        issue = self.create_issue_proc("I1", journal_proc=journal)
        self.create_article_proc("A1", issue_proc=issue)
        self.create_article_proc("A2")  # issue_proc=None
        self.create_issue_proc("I2")  # journal_proc=None

        items = self.get_items()

        self.assertEqual(list(items.keys()), [(journal.id, "abc")])
        self.assertEqual(items[(journal.id, "abc")]["issue_proc_id_list"], {issue.id})

    def test_includes_journals_without_pending_items(self):
        # outro periódico com item pendente não pode impedir que este seja
        # visitado: as novidades do acron.id só são identificadas em
        # task_migrate_and_publish_articles_by_journal
        pending_journal = self.create_journal_proc("J1", acron="abc")
        pending_issue = self.create_issue_proc("I1", journal_proc=pending_journal)
        self.create_article_proc("A1", issue_proc=pending_issue)

        journal = self.create_journal_proc("J2", acron="xyz")
        issue = self.create_issue_proc("I2", journal_proc=journal)
        IssueProc.objects.filter(id=issue.id).update(
            docs_status=tracker_choices.PROGRESS_STATUS_DONE,
            files_status=tracker_choices.PROGRESS_STATUS_DONE,
        )

        items = self.get_items()

        self.assertEqual(
            items[(pending_journal.id, "abc")]["issue_proc_id_list"],
            {pending_issue.id},
        )
        self.assertEqual(items[(journal.id, "xyz")]["issue_proc_id_list"], set())

    def test_issue_filter_does_not_include_other_journals(self):
        pending_journal = self.create_journal_proc("J1", acron="abc")
        pending_issue = self.create_issue_proc("I1", journal_proc=pending_journal)
        self.create_article_proc("A1", issue_proc=pending_issue)

        journal = self.create_journal_proc("J2", acron="xyz")
        issue = self.create_issue_proc("I2", journal_proc=journal)
        IssueProc.objects.filter(id=issue.id).update(
            docs_status=tracker_choices.PROGRESS_STATUS_DONE,
            files_status=tracker_choices.PROGRESS_STATUS_DONE,
        )

        items = ArticleProc.get_journal_and_issue_proc_ids(
            collection_acron_list=["scl"],
            issue_folder="I1",
            status_list=[tracker_choices.PROGRESS_STATUS_TODO],
        )

        self.assertEqual(list(items.keys()), [(pending_journal.id, "abc")])
