import unittest
from unittest.mock import MagicMock, Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from collection.models import Collection
from migration.models import (
    IdFileRecord,
    JournalAcronIdFile,
    MigratedArticle,
    MigratedData,
)


class MigratedDataCreateOrUpdateTestCase(unittest.TestCase):
    """Test cases for MigratedData.create_or_update_migrated_data() handling of duplicates."""

    @patch("migration.models.now")
    @patch.object(MigratedData.objects, "get")
    def test_create_or_update_returns_existing_when_up_to_date(self, mock_get, mock_now):
        """Test that an existing up-to-date record is returned without changes."""
        mock_now.return_value = "2024-01-01"
        mock_obj = Mock(spec=MigratedData)
        mock_obj.is_up_to_date.return_value = True
        mock_get.return_value = mock_obj

        result = MigratedData.create_or_update_migrated_data(
            user=Mock(),
            collection=Mock(),
            pid="pid123",
            data={"key": "value"},
            isis_updated_date="20240101",
        )

        self.assertEqual(result, mock_obj)

    @patch("migration.models.now")
    @patch.object(MigratedData.objects, "filter")
    @patch.object(MigratedData.objects, "get")
    def test_create_or_update_handles_multiple_objects_returned(
        self, mock_get, mock_filter, mock_now
    ):
        """Test that duplicates are resolved by keeping the most recent and deleting others."""
        mock_now.return_value = "2024-01-01"
        mock_collection = Mock()
        mock_user = Mock()

        mock_get.side_effect = MigratedData.MultipleObjectsReturned()

        mock_recent = MagicMock(spec=MigratedData)
        mock_recent.pk = 1
        mock_recent.content_type = "article"
        mock_recent.collection = mock_collection
        mock_recent.pid = "pid123"
        mock_recent.migration_status = "TODO"
        mock_recent.data = None
        mock_recent.isis_created_date = "20240101"
        mock_recent.isis_updated_date = None

        mock_queryset = MagicMock()
        mock_ordered_qs = MagicMock()
        mock_ordered_qs.first.return_value = mock_recent
        mock_queryset.order_by.return_value = mock_ordered_qs
        mock_filter.return_value = mock_queryset

        mock_exclude_qs = MagicMock()
        mock_ordered_qs.exclude.return_value = mock_exclude_qs

        result = MigratedData.create_or_update_migrated_data(
            user=mock_user,
            collection=mock_collection,
            pid="pid123",
            data={"key": "value"},
            migration_status="TODO",
            content_type="article",
            isis_created_date="20240101",
        )

        # Verify the returned object is the most recent one
        self.assertEqual(result, mock_recent)
        # Verify duplicates were deleted via filter().exclude().delete()
        mock_filter.assert_any_call(collection=mock_collection, pid="pid123")
        mock_queryset.order_by.assert_called_with("-updated")
        mock_ordered_qs.exclude.assert_called_once_with(pk=mock_recent.pk)
        mock_exclude_qs.delete.assert_called_once()
        # Verify the most recent was kept and saved
        mock_recent.save.assert_called_once()


class JournalAcronIdFileDataTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="migration-user")
        self.collection = Collection.objects.create(
            creator=self.user,
            acron="scl",
            name="SciELO",
        )
        self.journal_id_file = JournalAcronIdFile.objects.create(
            creator=self.user,
            collection=self.collection,
            journal_acron="rsp",
            source_path="/bases-work/rsp/rsp.id",
        )

    def create_article_record(self, item_pid, todo):
        return IdFileRecord.objects.create(
            creator=self.user,
            parent=self.journal_id_file,
            item_type="article",
            item_pid=item_pid,
            data={},
            todo=todo,
        )

    def test_separates_all_issue_pids_from_pending_issue_pids(self):
        self.create_article_record("S0034-89102004000200001", todo=True)
        self.create_article_record("S0034-89102004000300001", todo=False)

        data = self.journal_id_file.data

        self.assertEqual(
            data["issue_pids"],
            ["0034-891020040002", "0034-891020040003"],
        )
        self.assertEqual(
            data["pending_issue_pids"],
            ["0034-891020040002"],
        )
        self.assertEqual(data["stats"]["total_id_file_records"], 2)
        self.assertEqual(data["stats"]["total_id_file_records_to_migrate"], 1)
        self.assertEqual(data["stats"]["total_issues"], 2)


class MigratedArticleValidPidTestCase(unittest.TestCase):
    """Test cases for MigratedArticle.valid_pid() class method.

    A PID é válido se, e somente se, tem exatamente 23 caracteres e existe
    um registro MigratedArticle correspondente no banco de dados.
    """

    PID_23 = "S0034-77442021000600036"  # exatamente 23 caracteres

    @patch("migration.models.MigratedArticle.objects")
    def test_valid_pid_length_23_exists_in_db(self, mock_objects):
        """Returns True when pid has 23 chars and exists in DB."""
        mock_objects.filter.return_value.exists.return_value = True
        self.assertTrue(MigratedArticle.valid_pid(self.PID_23))

    @patch("migration.models.MigratedArticle.objects")
    def test_invalid_pid_not_in_db(self, mock_objects):
        """Returns False when pid has 23 chars but does not exist in DB."""
        mock_objects.filter.return_value.exists.return_value = False
        self.assertFalse(MigratedArticle.valid_pid(self.PID_23))

    def test_invalid_when_pid_is_none(self):
        """Returns False when pid is None (falsy)."""
        self.assertFalse(MigratedArticle.valid_pid(None))

    def test_invalid_when_pid_is_empty(self):
        """Returns False when pid is empty string (falsy)."""
        self.assertFalse(MigratedArticle.valid_pid(""))

    def test_invalid_when_pid_too_short(self):
        """Returns False when pid has fewer than 23 chars."""
        self.assertFalse(MigratedArticle.valid_pid(self.PID_23[:-1]))  # 22 chars

    def test_invalid_when_pid_too_long(self):
        """Returns False when pid has more than 23 chars."""
        self.assertFalse(MigratedArticle.valid_pid(self.PID_23 + "0"))  # 24 chars
