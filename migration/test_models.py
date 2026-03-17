import unittest
from unittest.mock import MagicMock, Mock, patch

from migration.models import MigratedData


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
        mock_queryset.order_by.return_value.first.return_value = mock_recent
        mock_filter.return_value = mock_queryset

        mock_exclude_qs = MagicMock()
        mock_queryset.exclude.return_value = mock_exclude_qs

        result = MigratedData.create_or_update_migrated_data(
            user=mock_user,
            collection=mock_collection,
            pid="pid123",
            data={"key": "value"},
            migration_status="TODO",
            content_type="article",
            isis_created_date="20240101",
        )

        # Verify duplicates were deleted via filter().exclude().delete()
        mock_filter.assert_any_call(collection=mock_collection, pid="pid123")
        mock_queryset.order_by.assert_called_with("-updated")
        mock_queryset.exclude.assert_called_once_with(pk=mock_recent.pk)
        mock_exclude_qs.delete.assert_called_once()
        # Verify the most recent was kept and saved
        mock_recent.save.assert_called_once()
