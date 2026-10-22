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
    def test_collection_schedules_unsynchronized_journals_and_forced_sync(self):
        user = get_user_model().objects.create_user(username="journal-tasks")
        collection = Collection.get_or_create(
            acron="scl", name="SciELO Brasil", user=user
        )
        records = []
        for synchronized in (False, True):
            journal = Journal.objects.create(
                creator=user, core_synchronized=synchronized
            )
            records.append(
                JournalProc.objects.create(
                    creator=user,
                    collection=collection,
                    journal=journal,
                    acron=f"journal-{synchronized}",
                    migration_status=choices.PROGRESS_STATUS_DONE,
                    qa_ws_status=choices.PROGRESS_STATUS_DONE,
                    public_ws_status=choices.PROGRESS_STATUS_DONE,
                ).pk
            )

        with patch.object(tasks, "_get_user", return_value=user), patch.object(
            tasks.controller, "get_classic_website", return_value="CLASSIC"
        ), patch.object(
            tasks, "create_or_update_migrated_journal"
        ) as import_journals, patch.object(
            tasks, "fix_publication_status"
        ), patch.object(
            tasks, "get_api_data", return_value={}
        ), patch.object(
            tasks.task_migrate_and_publish_journal, "apply_async"
        ) as schedule:
            for forced, acron, expected in (
                (False, None, records[:1]),
                (True, None, records),
                (True, "journal-True", records[1:]),
            ):
                with self.subTest(forced=forced, acron=acron):
                    schedule.reset_mock()
                    tasks.task_migrate_and_publish_journals_by_collection.run(
                        collection_acron="scl",
                        journal_acron=acron,
                        force_core_sync=forced,
                        force_import_acron_id_file=True,
                    )
                    self.assertCountEqual(
                        [
                            call.kwargs["kwargs"]["journal_proc_id"]
                            for call in schedule.call_args_list
                        ],
                        expected,
                    )
                    report = TaskTracker.objects.first()
                    self.assertTrue(report.completed)
                    self.assertEqual(report.total_processed, len(expected))
            import_journals.assert_called_with(user, collection, "CLASSIC", True)

    def test_individual_task_chooses_source_and_only_publishes_after_success(self):
        for forced, error in (
            (False, None),
            (True, None),
            (False, ValueError("migration failed")),
        ):
            with self.subTest(forced=forced, error=error), patch.object(
                tasks, "_get_user", return_value="USER"
            ), patch.object(tasks.JournalProc.objects, "get") as get_proc, patch.object(
                tasks, "fetch_and_create_journal"
            ) as core, patch.object(
                tasks.task_publish_journal, "apply_async"
            ) as publish:
                proc = MagicMock()
                proc.create_or_update_item.side_effect = error
                get_proc.return_value = proc

                result = tasks.task_migrate_and_publish_journal.run(
                    journal_proc_id=7,
                    collection_acron="scl",
                    force_core_sync=forced,
                    qa_api_data={"url": "QA"},
                    public_api_data={"error": "disabled"},
                )

                self.assertEqual(result, error is None)
                if forced:
                    core.assert_called_once_with(
                        "USER",
                        collection_acron="scl",
                        issn_electronic=proc.issn_electronic,
                        issn_print=proc.issn_print,
                        force_update=True,
                    )
                    proc.create_or_update_item.assert_not_called()
                else:
                    core.assert_not_called()
                    proc.create_or_update_item.assert_called_once_with(
                        "USER", False, tasks.controller.create_or_update_journal
                    )
                self.assertEqual(publish.call_count, int(error is None))
                self.assertEqual(
                    proc.start.return_value.finish.call_args.kwargs["completed"],
                    error is None,
                )

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
