from unittest.mock import patch

from django.test import TestCase

from proc.models import ArticleProc, IssueProc, JournalProc
from proc.tasks import TaskExecution
from tracker.models import TaskTracker, UnexpectedEvent


class TaskExecutionTests(TestCase):
    def test_execution_distinguishes_running_success_and_failure(self):
        for error in (None, ValueError("migration failed")):
            with self.subTest(error=error):
                execution = TaskExecution("migration", "journal", {})
                execution.task_tracker.refresh_from_db()
                self.assertIsNone(execution.task_tracker.completed)

                execution.finish(exception=error, data={"scheduled": [7]})

                execution.task_tracker.refresh_from_db()
                self.assertEqual(execution.task_tracker.completed, error is None)
                self.assertEqual(
                    execution.task_tracker.detail["data"], {"scheduled": [7]}
                )

    def test_unchanged_totals_keep_events_without_repeating_snapshots(self):
        execution = TaskExecution("migration", "journal", {})
        execution.journal_proc_id = 7
        initial = [{"total": 2, "status": {"migration_status": "TODO"}}]
        changed = [{"total": 2, "status": {"migration_status": "DONE"}}]

        with patch.object(
            JournalProc, "get_total_status", return_value=[]
        ), patch.object(IssueProc, "get_total_status", return_value=[]), patch.object(
            ArticleProc, "get_total_status", side_effect=[initial, initial, changed]
        ):
            for label in ("start", "checked", "migrated"):
                execution.update_total_status(label)
        execution.finish()

        execution.task_tracker.refresh_from_db()
        changes = execution.task_tracker.detail["status_changes"]
        self.assertEqual(
            changes["article"],
            [
                {"events": ["start", "checked"], "total_status": initial},
                {"events": ["migrated"], "total_status": changed},
            ],
        )
        self.assertEqual(
            changes["issue"],
            [{"events": ["start", "checked", "migrated"], "total_status": []}],
        )

    def test_finish_failure_records_action_and_item(self):
        execution = TaskExecution("migration", "journal-7", {})

        with patch.object(TaskTracker, "finish", side_effect=ValueError("cannot save")):
            execution.finish()

        event = UnexpectedEvent.objects.get()
        self.assertEqual(event.action, "proc.tasks.TaskExecution.finish")
        self.assertEqual(event.item, "journal-7")
        self.assertEqual(event.exception_msg, "cannot save")
