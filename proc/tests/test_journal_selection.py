"""
Testes da seleção de periódicos (JournalProc) para migrar e publicar e da
detecção de dados novos ou alterados na base title do site clássico.
"""

from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from collection.models import Collection
from migration.models import MigratedFile, MigratedJournal
from proc import source_classic_website
from proc.models import IssueProc, JournalProc
from tracker import choices as tracker_choices

User = get_user_model()

TODO = tracker_choices.PROGRESS_STATUS_TODO
REPROC = tracker_choices.PROGRESS_STATUS_REPROC
DONE = tracker_choices.PROGRESS_STATUS_DONE
PENDING = tracker_choices.PROGRESS_STATUS_PENDING
BLOCKED = tracker_choices.PROGRESS_STATUS_BLOCKED
IGNORED = tracker_choices.PROGRESS_STATUS_IGNORED


class SelectItemsToProcessTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tester")
        self.collection = Collection.get_or_create(
            acron="scl", name="SciELO Brasil", user=self.user
        )

    def _create(self, pid, migration_status, qa=TODO, public=TODO, acron=None):
        return JournalProc.objects.create(
            collection=self.collection,
            pid=pid,
            acron=acron,
            migration_status=migration_status,
            qa_ws_status=qa,
            public_ws_status=public,
            creator=self.user,
        )

    def _select(self, status=None, force_update=False, journal_filter=None):
        return JournalProc.select_items_to_process(
            self.collection,
            tracker_choices.get_valid_status(status, force_update),
            params=journal_filter,
        )

    def test_routine_selection(self):
        new = self._create("0000-0001", TODO)
        reproc = self._create("0000-0002", REPROC)
        pending = self._create("0000-0003", PENDING)
        blocked = self._create("0000-0004", BLOCKED)
        done = self._create("0000-0005", DONE, qa=DONE, public=DONE)
        done_to_publish = self._create("0000-0006", DONE, qa=REPROC, public=DONE)
        ignored = self._create("0000-0007", IGNORED)

        selected = self._select()

        self.assertEqual(selected, {new.id, reproc.id, done_to_publish.id})
        # PENDING e BLOCKED aguardam ação do usuário ou dados novos
        self.assertNotIn(pending.id, selected)
        self.assertNotIn(blocked.id, selected)
        self.assertNotIn(done.id, selected)
        self.assertNotIn(ignored.id, selected)

    def test_not_migrated_item_is_not_selected_by_publication_status(self):
        item = self._create("0000-0001", BLOCKED, qa=TODO, public=TODO)
        self.assertNotIn(item.id, self._select())

    def test_explicit_status_list_selects_only_those_status(self):
        blocked = self._create("0000-0001", BLOCKED)
        todo = self._create("0000-0002", TODO)
        self._create("0000-0003", PENDING)
        self._create("0000-0004", REPROC)
        self._create("0000-0005", DONE, qa=DONE, public=DONE)
        publish_blocked = self._create("0000-0006", DONE, qa=BLOCKED, public=DONE)
        self._create("0000-0007", DONE, qa=REPROC, public=DONE)

        selected = self._select(status=["BLOCKED", "TODO"])

        self.assertEqual(selected, {blocked.id, todo.id, publish_blocked.id})

    def test_core_sync_demand(self):
        from journal.models import Journal

        def create(pid, migration_status, core_synchronized):
            journal = Journal.objects.create(
                title=f"Journal {pid}",
                core_synchronized=core_synchronized,
                creator=self.user,
            )
            item = self._create(pid, migration_status, qa=DONE, public=DONE)
            item.journal = journal
            item.save()
            return item

        not_synced = create("0000-0001", DONE, False)
        synced = create("0000-0002", DONE, True)
        blocked = create("0000-0003", BLOCKED, False)

        with_demand = JournalProc.select_items_to_process(
            self.collection,
            tracker_choices.get_valid_status(None, False),
            include_core_sync_demand=True,
        )
        self.assertEqual(with_demand, {not_synced.id})
        self.assertNotIn(synced.id, with_demand)
        # BLOCKED aguarda ação do usuário
        self.assertNotIn(blocked.id, with_demand)

        without_demand = JournalProc.select_items_to_process(
            self.collection, tracker_choices.get_valid_status(None, False)
        )
        self.assertEqual(without_demand, set())

    def test_issue_proc_selection_uses_only_given_status(self):
        def create(pid, migration_status, qa=TODO, public=TODO):
            return IssueProc.objects.create(
                collection=self.collection,
                pid=pid,
                migration_status=migration_status,
                qa_ws_status=qa,
                public_ws_status=public,
                creator=self.user,
            )

        blocked = create("0000-000120200001", BLOCKED)
        create("0000-000120200002", PENDING)
        create("0000-000120200003", REPROC)
        publish_todo = create("0000-000120200004", DONE, qa=TODO, public=DONE)
        create("0000-000120200005", DONE, qa=REPROC, public=DONE)

        selected = IssueProc.select_items_to_process(
            self.collection, ["BLOCKED", "TODO"]
        )

        self.assertEqual(selected, {blocked.id, publish_todo.id})

    def test_force_update_selects_done(self):
        done = self._create("0000-0005", DONE, qa=DONE, public=DONE)
        self.assertIn(done.id, self._select(force_update=True))

    def test_journal_filter(self):
        self._create("0000-0001", TODO, acron="abc")
        other = self._create("0000-0002", TODO, acron="xyz")
        self.assertEqual(
            self._select(journal_filter={"acron": "xyz"}), {other.id}
        )


class RegisterClassicWebsiteDataTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tester")
        self.collection = Collection.get_or_create(
            acron="scl", name="SciELO Brasil", user=self.user
        )

    def _create(self, pid, migration_status, data):
        migrated_data = MigratedJournal.objects.create(
            collection=self.collection,
            pid=pid,
            content_type="journal",
            migration_status=TODO,
            data=data,
            creator=self.user,
        )
        return JournalProc.objects.create(
            collection=self.collection,
            pid=pid,
            migration_status=migration_status,
            migrated_data=migrated_data,
            creator=self.user,
        )

    def _register(self, pid, data):
        with patch.object(
            MigratedJournal,
            "get_data_from_classic_website",
            return_value=MagicMock(
                isis_created_date="20200101",
                isis_updated_date="20200102",
                is_press_release=False,
            ),
        ):
            return JournalProc.register_classic_website_data(
                self.user, self.collection, pid, data, "journal", False
            )

    def test_unchanged_data_keeps_status(self):
        for i, status in enumerate((DONE, BLOCKED, PENDING, IGNORED)):
            with self.subTest(status=status):
                pid = f"0000-000{i}"
                self._create(pid, status, {"v100": [{"_": "x"}]})
                obj = self._register(pid, {"v100": [{"_": "x"}]})
                self.assertEqual(obj.migration_status, status)

    def test_changed_data_adopts_status_of_migrated_data(self):
        # dados alterados: o proc adota o status do MigratedJournal (TODO),
        # inclusive se estava IGNORED pelo usuário
        for i, status in enumerate((DONE, BLOCKED, PENDING, IGNORED)):
            with self.subTest(status=status):
                pid = f"0001-000{i}"
                self._create(pid, status, {"v100": [{"_": "old"}]})
                obj = self._register(pid, {"v100": [{"_": "new"}]})
                obj.refresh_from_db()
                self.assertEqual(obj.migration_status, TODO)
                self.assertEqual(obj.migrated_data.data, {"v100": [{"_": "new"}]})

    def test_new_journal_is_todo(self):
        obj = self._register("0003-0001", {"v100": [{"_": "new"}]})
        self.assertEqual(obj.migration_status, TODO)

    def test_done_without_migrated_data_is_migrated_from_classic_website(self):
        # ex.: JournalProc criado a partir do core
        JournalProc.objects.create(
            collection=self.collection,
            pid="0004-0001",
            migration_status=DONE,
            creator=self.user,
        )
        obj = self._register("0004-0001", {"v100": [{"_": "x"}]})
        obj.refresh_from_db()
        self.assertEqual(obj.migration_status, TODO)
        self.assertEqual(obj.migrated_data.data, {"v100": [{"_": "x"}]})

    def test_nothing_to_migrate_is_done(self):
        self._create("0005-0001", TODO, {"v100": [{"_": "x"}]})
        obj = JournalProc.register_classic_website_data(
            self.user, self.collection, "0005-0001", None, "journal", True
        )
        self.assertEqual(obj.migration_status, DONE)

    def test_no_data_without_force_update_keeps_status(self):
        self._create("0006-0001", TODO, {"v100": [{"_": "x"}]})
        obj = JournalProc.register_classic_website_data(
            self.user, self.collection, "0006-0001", None, "journal", False
        )
        self.assertEqual(obj.migration_status, TODO)

    def test_failure_after_proc_creation_blocks_proc(self):
        self._create("0007-0001", DONE, {"v100": [{"_": "old"}]})
        with patch.object(
            MigratedJournal,
            "register_classic_website_data",
            side_effect=Exception("erro"),
        ):
            obj = JournalProc.register_classic_website_data(
                self.user, self.collection, "0007-0001", {"v100": [{"_": "new"}]},
                "journal", False,
            )
        obj.refresh_from_db()
        self.assertEqual(obj.migration_status, BLOCKED)


def id_file_item(pid, data):
    # item de ClassicIdFile.items(): pid e data (registro convertido para JSON)
    return MagicMock(pid=pid, data=data)


class CreateOrUpdateMigratedJournalTest(TestCase):
    def setUp(self):
        self.user = MagicMock()
        self.collection = MagicMock()
        self.classic_website = MagicMock()
        self.classic_website.classic_website_paths.title_path = "/bases/title.id"
        self.journals_id_file = self.classic_website.get_journals_id_file.return_value
        self.journals_id_file.items.return_value = [
            id_file_item("0001-0001", {"v100": "a"}),
            id_file_item("0002-0002", {"v100": "b"}),
        ]
        for name in ("MigratedFile", "MigratedData", "JournalProc", "UnexpectedEvent"):
            patcher = patch.object(source_classic_website, name)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        patcher = patch.object(
            source_classic_website, "modified_date", return_value="v1"
        )
        self.modified_date = patcher.start()
        self.addCleanup(patcher.stop)
        self.MigratedFile.has_changes.return_value = True
        self.MigratedData.objects.filter.return_value.aggregate.return_value = {
            "d": "20200101"
        }

    def _run(self, force_update=False):
        source_classic_website.create_or_update_migrated_journal(
            self.user, self.collection, self.classic_website, force_update
        )

    def assert_marked_as_read(self, path="/bases/title.id"):
        self.MigratedFile.create_or_update.assert_called_once_with(
            user=self.user,
            collection=self.collection,
            original_path=path,
            source_path=path,
            component_type="id_file",
            force_update=False,
            file_datetime_iso="v1",
        )

    def test_already_read_file_is_skipped(self):
        self.MigratedFile.has_changes.return_value = False
        self._run()
        self.JournalProc.register_classic_website_data.assert_not_called()
        self.MigratedFile.create_or_update.assert_not_called()

    def test_marks_as_read_when_file_is_completely_read(self):
        self._run()
        self.assertEqual(self.JournalProc.register_classic_website_data.call_count, 2)
        self.MigratedFile.has_changes.assert_called_once_with(
            self.collection, "/bases/title.id", False
        )
        self.assert_marked_as_read()

    def test_marks_as_read_with_version_identified_before_reading(self):
        def register(*args, **kwargs):
            # arquivo modificado durante a leitura
            self.modified_date.return_value = "v2"
            return MagicMock()

        self.JournalProc.register_classic_website_data.side_effect = register
        self._run()
        self.assert_marked_as_read()

    def test_marks_as_read_when_a_record_fails(self):
        # falha em registro individual fica registrada no proc (BLOCKED)
        self.JournalProc.register_classic_website_data.side_effect = [
            MagicMock(migration_status=BLOCKED),
            None,
        ]
        self._run()
        self.assert_marked_as_read()

    def test_marks_as_read_when_a_record_raises(self):
        self.JournalProc.register_classic_website_data.side_effect = [
            Exception("erro"),
            MagicMock(),
        ]
        self._run()
        self.assertEqual(self.JournalProc.register_classic_website_data.call_count, 2)
        self.UnexpectedEvent.create.assert_called_once()
        self.assert_marked_as_read()

    def test_reads_only_records_since_most_recent_registered_date(self):
        self._run()
        self.MigratedData.objects.filter.assert_called_once_with(
            collection=self.collection, content_type="journal"
        )
        self.journals_id_file.items.assert_called_once_with(since="20200101")

    def test_force_update_reads_all_records(self):
        self._run(force_update=True)
        self.MigratedData.objects.filter.assert_not_called()
        self.journals_id_file.items.assert_called_once_with(since=None)
        self.assertEqual(self.JournalProc.register_classic_website_data.call_count, 2)

    def test_does_not_mark_as_read_when_reading_is_incomplete(self):
        def records(since=None):
            yield id_file_item("0001-0001", {"v100": "a"})
            raise IOError("leitura interrompida")

        self.journals_id_file.items.side_effect = records
        self._run()
        self.assertEqual(self.JournalProc.register_classic_website_data.call_count, 1)
        self.UnexpectedEvent.create.assert_called_once()
        self.MigratedFile.create_or_update.assert_not_called()

    def test_issue_file_uses_same_reading(self):
        self.classic_website.classic_website_paths.issue_path = "/bases/issue.id"
        self.classic_website.get_issues_id_file.return_value.items.return_value = [
            id_file_item("0001-000120200001", {"v30": "a"}),
        ]
        with patch.object(source_classic_website, "IssueProc") as mock_issue_proc:
            mock_issue_proc.register_classic_website_data.return_value = MagicMock()
            source_classic_website.create_or_update_migrated_issue(
                self.user, self.collection, self.classic_website, False
            )
        mock_issue_proc.register_classic_website_data.assert_called_once_with(
            self.user, self.collection, "0001-000120200001", {"v30": "a"}, "issue", False
        )
        self.JournalProc.register_classic_website_data.assert_not_called()
        self.MigratedData.objects.filter.assert_called_once_with(
            collection=self.collection, content_type="issue"
        )
        self.MigratedFile.has_changes.assert_called_once_with(
            self.collection, "/bases/issue.id", False
        )
        self.assert_marked_as_read("/bases/issue.id")


class MigratedFileHasChangesTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tester")
        self.collection = Collection.get_or_create(
            acron="scl", name="SciELO Brasil", user=self.user
        )
        MigratedFile.objects.create(
            collection=self.collection,
            original_path="/bases/title.id",
            file_datetime_iso="v1",
            creator=self.user,
        )
        patcher = patch("migration.models.modified_date", return_value="v2")
        self.modified_date = patcher.start()
        self.addCleanup(patcher.stop)

    def _has_changes(self, path="/bases/title.id", force_update=False):
        return MigratedFile.has_changes(self.collection, path, force_update)

    def test_modified_file_has_changes(self):
        self.assertTrue(self._has_changes())

    def test_new_file_has_changes(self):
        self.assertTrue(self._has_changes("/bases/issue.id"))

    def test_file_already_read_has_no_changes(self):
        self.modified_date.return_value = "v1"
        self.assertFalse(self._has_changes())

    def test_force_update_has_changes(self):
        self.modified_date.return_value = "v1"
        self.assertTrue(self._has_changes(force_update=True))

    def test_does_not_register_file(self):
        self._has_changes()
        self._has_changes("/bases/issue.id")
        self.assertEqual(
            MigratedFile.objects.get(original_path="/bases/title.id").file_datetime_iso,
            "v1",
        )
        self.assertFalse(
            MigratedFile.objects.filter(original_path="/bases/issue.id").exists()
        )
