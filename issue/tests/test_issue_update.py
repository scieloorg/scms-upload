from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from collection.models import Collection
from issue.models import Issue
from journal.models import Journal
from migration.controller import create_or_update_issue
from migration.models import MigratedIssue
from proc.models import IssueProc, JournalProc
from proc.source_core_api import process_issue_result


class IssueUpdateTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="issue-review")
        self.collection = Collection.get_or_create(
            acron="scl", name="SciELO Brasil", user=self.user
        )
        self.journal = Journal.objects.create(creator=self.user)
        self.journal_proc = JournalProc.objects.create(
            creator=self.user,
            collection=self.collection,
            journal=self.journal,
            pid="1234-5678",
        )

    def test_classic_remigration_updates_linked_issue_without_duplicates(self):
        issue = Issue.objects.create(
            creator=self.user,
            journal=self.journal,
            volume="10",
            number="1",
            supplement="2",
            publication_year="2024",
            order=7,
            issue_pid_suffix="0007",
        )
        migrated = MigratedIssue.objects.create(creator=self.user, data={})
        issue_proc = IssueProc.objects.create(
            creator=self.user,
            collection=self.collection,
            journal_proc=self.journal_proc,
            issue=issue,
            migrated_data=migrated,
        )
        classic = MagicMock(
            journal="1234-5678",
            publication_year="2024",
            volume="10",
            number=None,
            supplement=None,
            total_documents=0,
            order="0007",
            issue_label="v10",
            sections_by_code={},
        )

        with patch("migration.controller.classic_ws.Issue", return_value=classic):
            for _ in range(2):
                result = create_or_update_issue(
                    self.user, issue_proc, True, JournalProc
                )
                self.assertEqual(result.pk, issue.pk)

        issue.refresh_from_db()
        issue_proc.refresh_from_db()
        self.assertEqual(Issue.objects.count(), 1)
        self.assertEqual(issue_proc.issue_id, issue.pk)
        self.assertIsNone(issue.number)
        self.assertIsNone(issue.supplement)
        self.assertTrue(issue.is_continuous_publishing_model)
        self.assertEqual((issue.order, issue.issue_pid_suffix), (7, "0007"))

    def test_core_sync_updates_fields_and_preserves_identity_and_audit(self):
        data = dict(
            volume="10",
            number="1",
            supplement=None,
            year="2024",
            order=7,
            issue_pid_suffix="0007",
            total_documents=10,
            is_continuous_publishing_model=True,
        )
        process_issue_result(self.user, self.journal, data)
        issue = Issue.objects.get(journal=self.journal)
        self.assertEqual(issue.total_documents, 10)
        self.assertTrue(issue.is_continuous_publishing_model)
        editor = get_user_model().objects.create_user(username="issue-editor")
        data.update(
            order=None,
            issue_pid_suffix=None,
            total_documents=0,
            is_continuous_publishing_model=False,
        )

        process_issue_result(editor, self.journal, data)

        issue.refresh_from_db()
        self.assertEqual(Issue.objects.count(), 1)
        self.assertEqual(IssueProc.objects.get().issue_id, issue.pk)
        self.assertEqual(issue.total_documents, 0)
        self.assertFalse(issue.is_continuous_publishing_model)
        self.assertEqual((issue.order, issue.issue_pid_suffix), (7, "0007"))
        self.assertEqual(
            (issue.creator_id, issue.updated_by_id), (self.user.pk, editor.pk)
        )
