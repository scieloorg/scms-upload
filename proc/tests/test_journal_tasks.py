from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from collection.models import Collection
from journal.models import Journal
from proc import tasks
from proc.models import JournalProc
from tracker import choices
from tracker.models import TaskTracker


class JournalTaskTests(TestCase):


    def test_entry_task_forwards_independent_sync_controls(self):
        collection = MagicMock(acron="scl")
        with patch.object(
            tasks, "_get_collections", return_value=[collection]
        ), patch.object(
            tasks.task_migrate_and_publish_journals_by_collection, "delay"
        ) as schedule:
            tasks.task_migrate_and_publish_journals.run(force_core_sync=True)

        self.assertTrue(schedule.call_args.kwargs["force_core_sync"])
        self.assertFalse(schedule.call_args.kwargs["force_update"])
