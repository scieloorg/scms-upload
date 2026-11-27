from unittest.mock import patch

from django.test import TestCase

from proc.models import ArticleProc, IssueProc, JournalProc
from proc.tasks import TaskExecution
from tracker.models import TaskTracker, UnexpectedEvent


class TaskExecutionTests(TestCase):


    def test_finish_failure_records_action_and_item(self):
        execution = TaskExecution("migration", "journal-7", {})

        with patch.object(TaskTracker, "finish", side_effect=ValueError("cannot save")):
            execution.finish()

        event = UnexpectedEvent.objects.get()
        self.assertEqual(event.action, "proc.tasks.TaskExecution.finish")
        self.assertEqual(event.item, "journal-7")
        self.assertEqual(event.exception_msg, "cannot save")
