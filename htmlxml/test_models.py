import logging
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from htmlxml.models import HTMLXML
from migration.models import MigratedArticle

User = get_user_model()


class HTMLXMLMultipleObjectsReturnedTestCase(TestCase):
    """Test cases for HTMLXML handling of duplicate records."""

    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username="testuser",
            email="test@test.com",
            password="testpass123"
        )
        
    @patch('htmlxml.models.HTMLXML.objects')
    def test_get_returns_most_recent_when_duplicates_exist(self, mock_objects):
        """Test that get() returns the most recently updated record when duplicates exist."""
        # Create mock migrated article
        mock_article = Mock(spec=MigratedArticle)
        mock_article.n_paragraphs = 10
        
        # Create mock HTMLXML objects
        mock_old = Mock(spec=HTMLXML)
        mock_old.pk = 1
        mock_old.updated = "2023-01-01"
        
        mock_recent = Mock(spec=HTMLXML)
        mock_recent.pk = 2
        mock_recent.updated = "2023-12-31"
        
        # Configure mock to raise MultipleObjectsReturned on first call
        mock_objects.get.side_effect = HTMLXML.MultipleObjectsReturned()
        
        # Configure filter to return queryset mock
        mock_queryset = Mock()
        mock_queryset.order_by.return_value.first.return_value = mock_recent
        mock_objects.filter.return_value = mock_queryset
        
        # Call the method
        result = HTMLXML.get(migrated_article=mock_article)
        
        # Verify it returns the most recent
        assert result == mock_recent
        mock_objects.filter.assert_called_once_with(migrated_article=mock_article)
        mock_queryset.order_by.assert_called_once_with("-updated")

    @patch('htmlxml.models.logging')
    def test_create_or_update_cleans_up_duplicates(self, mock_logging):
        """Test that create_or_update() deletes duplicate records."""
        # Create a real migrated article (or mock if dependencies are complex)
        mock_article = Mock(spec=MigratedArticle)
        mock_article.n_paragraphs = 10
        
        # Create first HTMLXML record
        with patch.object(HTMLXML, 'get') as mock_get, \
             patch.object(HTMLXML.objects, 'filter') as mock_filter:
            
            # Mock the main object
            mock_obj = Mock(spec=HTMLXML)
            mock_obj.pk = 1
            mock_obj.html2xml_status = 'TODO'
            mock_obj.quality = 'NOT_EVALUATED'
            mock_obj.n_references = 0
            mock_obj.record_types = None
            mock_obj.save = Mock()
            mock_get.return_value = mock_obj
            
            # Mock duplicates
            mock_duplicate1 = Mock(spec=HTMLXML)
            mock_duplicate1.pk = 2
            mock_duplicate2 = Mock(spec=HTMLXML)
            mock_duplicate2.pk = 3
            
            mock_duplicates = Mock()
            mock_duplicates.exists.return_value = True
            mock_duplicates.count.return_value = 2
            mock_duplicates.delete = Mock()
            
            mock_queryset = Mock()
            mock_queryset.exclude.return_value = mock_duplicates
            mock_filter.return_value = mock_queryset
            
            # Call create_or_update
            result = HTMLXML.create_or_update(
                user=self.user,
                migrated_article=mock_article
            )
            
            # Verify duplicates were deleted
            mock_duplicates.delete.assert_called_once()
            mock_logging.warning.assert_called()
            
            # Verify the object was saved
            mock_obj.save.assert_called_once()

    def test_get_raises_value_error_without_migrated_article(self):
        """Test that get() raises ValueError when migrated_article is not provided."""
        with self.assertRaises(ValueError) as context:
            HTMLXML.get()
        
        assert "HTMLXML.get requires migrated_article" in str(context.exception)

    def test_get_raises_does_not_exist_when_no_record_found(self):
        """Test that get() raises DoesNotExist when no record is found."""
        mock_article = Mock(spec=MigratedArticle)
        
        with self.assertRaises(HTMLXML.DoesNotExist):
            HTMLXML.get(migrated_article=mock_article)
