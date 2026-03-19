import unittest
from unittest.mock import MagicMock, Mock, patch, call

from article.models import Article


class ArticleHasValidPidV2TestCase(unittest.TestCase):
    """Test cases for Article.has_valid_pid_v2() method."""

    def _make_article(self, pid_v2, position):
        article = Article.__new__(Article)
        article.pid_v2 = pid_v2
        article.position = position
        return article

    def test_valid_pid_v2_matching_position(self):
        """pid_v2 last 5 digits match position zero-padded."""
        article = self._make_article("S0034-77442021000600036", 36)
        self.assertTrue(article.has_valid_pid_v2())

    def test_invalid_pid_v2_not_matching_position(self):
        """pid_v2 last 5 digits don't match position."""
        article = self._make_article("S0034-77442021060626158", 36)
        self.assertFalse(article.has_valid_pid_v2())

    def test_valid_when_pid_v2_is_none(self):
        """Returns True when pid_v2 is None (can't validate)."""
        article = self._make_article(None, 36)
        self.assertTrue(article.has_valid_pid_v2())

    def test_valid_when_position_is_none(self):
        """Returns True when position is None (can't validate)."""
        article = self._make_article("S0034-77442021000600036", None)
        self.assertTrue(article.has_valid_pid_v2())

    def test_valid_when_position_exceeds_5_digits(self):
        """Returns True when position > 99999 (can't fit in 5 digits)."""
        article = self._make_article("S0034-77442021000600036", 100000)
        self.assertTrue(article.has_valid_pid_v2())

    def test_valid_with_position_zero(self):
        """Position 0 matches suffix 00000."""
        article = self._make_article("S003477442021000600000", 0)
        self.assertTrue(article.has_valid_pid_v2())

    def test_valid_with_large_position(self):
        """Position 99999 matches suffix 99999."""
        article = self._make_article("S003477442021000699999", 99999)
        self.assertTrue(article.has_valid_pid_v2())

    def test_invalid_with_position_1(self):
        """Position 1 should match suffix 00001, not 26158."""
        article = self._make_article("S0034-77442021060626158", 1)
        self.assertFalse(article.has_valid_pid_v2())

    def test_valid_when_pid_v2_too_short(self):
        """Returns True when pid_v2 has fewer than 5 chars."""
        article = self._make_article("S034", 36)
        self.assertTrue(article.has_valid_pid_v2())

    def test_valid_when_pid_v2_is_empty(self):
        """Returns True when pid_v2 is empty string."""
        article = self._make_article("", 36)
        self.assertTrue(article.has_valid_pid_v2())


class ArticleExcludeArticlesWithInvalidPidV2TestCase(unittest.TestCase):
    """Test cases for Article.exclude_articles_with_invalid_pid_v2()."""

    @patch("article.models.PidProviderXML")
    @patch("article.models.SPSPkg")
    @patch("article.models.Article.objects")
    def test_no_invalid_articles(self, mock_objects, mock_sps_pkg, mock_pp_xml):
        """No articles deleted when all have valid pid_v2."""
        mock_article = Mock()
        mock_article.pid_v2 = "S0034-77442021000600036"
        mock_article.position = 36
        mock_article.sps_pkg_id = 1
        mock_article.pp_xml_id = 1
        mock_article.has_valid_pid_v2 = Article.has_valid_pid_v2.__get__(mock_article)

        mock_qs = MagicMock()
        mock_qs.filter.return_value = mock_qs
        mock_qs.select_related.return_value = [mock_article]
        mock_objects.filter.return_value = mock_qs
        mock_objects.all.return_value = mock_qs

        events = Article.exclude_articles_with_invalid_pid_v2()

        self.assertIn("No migrated articles with invalid pid_v2 found", events)

    @patch("article.models.transaction")
    @patch("article.models.PidProviderXML")
    @patch("article.models.SPSPkg")
    @patch("article.models.Article.objects")
    def test_deletes_invalid_article(self, mock_objects, mock_sps_pkg, mock_pp_xml, mock_transaction):
        """Deletes migrated article with invalid pid_v2."""
        mock_article = Mock()
        mock_article.id = 42
        mock_article.pid_v2 = "S0034-77442021060626158"
        mock_article.position = 36
        mock_article.sps_pkg_id = 10
        mock_article.pp_xml_id = 20
        mock_article.has_valid_pid_v2 = Article.has_valid_pid_v2.__get__(mock_article)

        mock_qs = MagicMock()
        mock_qs.filter.return_value = mock_qs
        mock_qs.select_related.return_value = [mock_article]
        mock_objects.filter.return_value = mock_qs
        mock_objects.all.return_value = mock_qs

        mock_delete_qs = MagicMock()
        mock_delete_qs.delete.return_value = (1, {})
        mock_objects.filter.return_value = mock_delete_qs

        mock_sps_pkg_qs = MagicMock()
        mock_sps_pkg_qs.delete.return_value = (1, {})
        mock_sps_pkg.objects.filter.return_value = mock_sps_pkg_qs

        mock_pp_xml_qs = MagicMock()
        mock_pp_xml_qs.delete.return_value = (1, {})
        mock_pp_xml.objects.filter.return_value = mock_pp_xml_qs

        mock_transaction.atomic.return_value.__enter__ = Mock()
        mock_transaction.atomic.return_value.__exit__ = Mock(return_value=False)

        events = Article.exclude_articles_with_invalid_pid_v2()

        self.assertTrue(any("Invalid pid_v2" in e for e in events))
        self.assertTrue(any("Articles deletados" in e for e in events))

    @patch("article.models.Article.objects")
    def test_with_journal_filter(self, mock_objects):
        """Filters by journal when provided."""
        mock_journal = Mock()

        mock_qs = MagicMock()
        mock_qs.filter.return_value = mock_qs
        mock_qs.select_related.return_value = []
        mock_objects.filter.return_value = mock_qs

        events = Article.exclude_articles_with_invalid_pid_v2(journal=mock_journal)

        mock_objects.filter.assert_any_call(journal=mock_journal)


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
