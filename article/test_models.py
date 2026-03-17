import unittest
from unittest.mock import MagicMock, Mock, patch

from article.models import Article


class ArticleGetTestCase(unittest.TestCase):
    """Test cases for Article.get() handling of duplicate records."""

    def test_get_raises_value_error_without_pid_v3(self):
        """Test that get() raises ValueError when pid_v3 is not provided."""
        with self.assertRaises(ValueError):
            Article.get(None)

    def test_get_raises_value_error_with_empty_pid_v3(self):
        """Test that get() raises ValueError when pid_v3 is empty string."""
        with self.assertRaises(ValueError):
            Article.get("")

    @patch("article.models.Article.objects")
    def test_get_returns_single_article(self, mock_objects):
        """Test that get() returns the article when exactly one match exists."""
        mock_article = Mock(spec=Article)
        mock_objects.get.return_value = mock_article

        result = Article.get("pid123")

        self.assertEqual(result, mock_article)
        mock_objects.get.assert_called_once_with(pid_v3="pid123")

    @patch("article.models.Article.objects")
    def test_get_raises_does_not_exist(self, mock_objects):
        """Test that get() raises DoesNotExist when no article is found."""
        mock_objects.get.side_effect = Article.DoesNotExist()

        with self.assertRaises(Article.DoesNotExist):
            Article.get("pid123")

    @patch("article.models.Article.objects")
    def test_get_handles_multiple_objects_returned(self, mock_objects):
        """Test that get() handles duplicates by keeping the most recent and deleting others."""
        mock_objects.get.side_effect = Article.MultipleObjectsReturned()

        mock_recent = Mock(spec=Article)
        mock_recent.pk = 1

        mock_queryset = MagicMock()
        mock_ordered_qs = MagicMock()
        mock_ordered_qs.first.return_value = mock_recent
        mock_queryset.order_by.return_value = mock_ordered_qs

        mock_exclude_qs = MagicMock()
        mock_ordered_qs.exclude.return_value = mock_exclude_qs

        mock_objects.filter.return_value = mock_queryset

        result = Article.get("pid123")

        self.assertEqual(result, mock_recent)
        mock_objects.filter.assert_any_call(pid_v3="pid123")
        mock_queryset.order_by.assert_called_with("-updated")
        mock_ordered_qs.exclude.assert_called_once_with(pk=mock_recent.pk)
        mock_exclude_qs.delete.assert_called_once()
