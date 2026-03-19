import unittest
from unittest.mock import MagicMock, Mock, patch

from article.models import Article


class ArticleHasValidPidV2TestCase(unittest.TestCase):
    """Test cases for Article.has_valid_pid_v2() static method."""

    def test_valid_pid_v2_matching_order(self):
        """pid_v2 last 5 digits match order zero-padded."""
        self.assertTrue(Article.has_valid_pid_v2("S0034-77442021000600036", "00036"))

    def test_valid_pid_v2_matching_order_without_leading_zeros(self):
        """pid_v2 last 5 digits match order even when order has no leading zeros."""
        self.assertTrue(Article.has_valid_pid_v2("S0034-77442021000600036", "36"))

    def test_invalid_pid_v2_not_matching_order(self):
        """pid_v2 last 5 digits don't match order."""
        self.assertFalse(Article.has_valid_pid_v2("S0034-77442021060626158", "36"))

    def test_valid_when_pid_v2_is_none(self):
        """Returns True when pid_v2 is None (can't validate)."""
        self.assertTrue(Article.has_valid_pid_v2(None, "36"))

    def test_valid_when_order_is_none(self):
        """Returns True when order is None (can't validate)."""
        self.assertTrue(Article.has_valid_pid_v2("S0034-77442021000600036", None))

    def test_valid_when_order_is_empty(self):
        """Returns True when order is empty string (can't validate)."""
        self.assertTrue(Article.has_valid_pid_v2("S0034-77442021000600036", ""))

    def test_valid_with_order_zero(self):
        """Order 0 matches suffix 00000."""
        self.assertTrue(Article.has_valid_pid_v2("S003477442021000600000", "0"))

    def test_invalid_with_order_1(self):
        """Order 1 should match suffix 00001, not 26158."""
        self.assertFalse(Article.has_valid_pid_v2("S0034-77442021060626158", "1"))

    def test_valid_when_pid_v2_too_short(self):
        """Returns True when pid_v2 has fewer than 5 chars."""
        self.assertTrue(Article.has_valid_pid_v2("S034", "36"))

    def test_valid_when_pid_v2_is_empty(self):
        """Returns True when pid_v2 is empty string."""
        self.assertTrue(Article.has_valid_pid_v2("", "36"))

    def test_valid_when_order_is_non_numeric(self):
        """Returns True when order is non-numeric (can't validate)."""
        self.assertTrue(Article.has_valid_pid_v2("S0034-77442021000600036", "abc"))


class ArticleExcludeArticlesWithInvalidPidV2TestCase(unittest.TestCase):
    """Test cases for Article.exclude_articles_with_invalid_pid_v2()."""

    def _make_article_proc(self, article_id, pid_v2, order, sps_pkg_id=1, pp_xml_id=1):
        mock_article = Mock()
        mock_article.id = article_id
        mock_article.pid_v2 = pid_v2
        mock_article.sps_pkg_id = sps_pkg_id
        mock_article.pp_xml_id = pp_xml_id

        mock_document = Mock()
        mock_document.order = order

        mock_migrated_data = Mock()
        mock_migrated_data.document = mock_document

        mock_article_proc = Mock()
        mock_article_proc.sps_pkg_id = sps_pkg_id
        mock_article_proc.migrated_data = mock_migrated_data
        return mock_article_proc, mock_article

    @patch("article.models.Article.objects")
    def test_no_invalid_articles(self, mock_objects):
        """No articles deleted when all have valid pid_v2."""
        mock_article_proc, mock_article = self._make_article_proc(
            article_id=1, pid_v2="S0034-77442021000600036", order="36"
        )

        mock_ap_qs = MagicMock()
        mock_ap_qs.filter.return_value = mock_ap_qs
        mock_ap_qs.select_related.return_value = [mock_article_proc]

        mock_article_qs = MagicMock()
        mock_article_qs.only.return_value = [mock_article]
        mock_objects.filter.return_value = mock_article_qs

        with patch("proc.models.ArticleProc.objects", mock_ap_qs):
            events = Article.exclude_articles_with_invalid_pid_v2()

        self.assertIn("No migrated articles with invalid pid_v2 found", events)

    @patch("article.models.transaction")
    @patch("article.models.PidProviderXML")
    @patch("article.models.SPSPkg")
    @patch("article.models.Article.objects")
    def test_deletes_invalid_article(self, mock_objects, mock_sps_pkg, mock_pp_xml, mock_transaction):
        """Deletes migrated article with invalid pid_v2."""
        mock_article_proc, mock_article = self._make_article_proc(
            article_id=42, pid_v2="S0034-77442021060626158", order="36",
            sps_pkg_id=10, pp_xml_id=20
        )

        mock_ap_qs = MagicMock()
        mock_ap_qs.filter.return_value = mock_ap_qs
        mock_ap_qs.select_related.return_value = [mock_article_proc]

        mock_article_qs = MagicMock()
        mock_article_qs.only.return_value = [mock_article]

        mock_delete_qs = MagicMock()
        mock_delete_qs.delete.return_value = (1, {})

        # First call: bulk fetch articles; subsequent calls: delete operations
        mock_objects.filter.side_effect = [mock_article_qs, mock_delete_qs]

        mock_sps_pkg_qs = MagicMock()
        mock_sps_pkg_qs.delete.return_value = (1, {})
        mock_sps_pkg.objects.filter.return_value = mock_sps_pkg_qs

        mock_pp_xml_qs = MagicMock()
        mock_pp_xml_qs.delete.return_value = (1, {})
        mock_pp_xml.objects.filter.return_value = mock_pp_xml_qs

        mock_transaction.atomic.return_value.__enter__ = Mock()
        mock_transaction.atomic.return_value.__exit__ = Mock(return_value=False)

        with patch("proc.models.ArticleProc.objects", mock_ap_qs):
            events = Article.exclude_articles_with_invalid_pid_v2()

        self.assertTrue(any("Invalid pid_v2" in e for e in events))
        self.assertTrue(any("Articles deletados" in e for e in events))

    def test_with_journal_filter(self):
        """Filters ArticleProc by journal when provided."""
        mock_journal = Mock()

        mock_ap_qs = MagicMock()
        mock_ap_qs.filter.return_value = mock_ap_qs
        mock_ap_qs.select_related.return_value = []

        with patch("proc.models.ArticleProc.objects", mock_ap_qs):
            events = Article.exclude_articles_with_invalid_pid_v2(journal=mock_journal)

        mock_ap_qs.filter.assert_called_once_with(
            migrated_data__isnull=False,
            sps_pkg__isnull=False,
            issue_proc__journal_proc__journal=mock_journal,
        )


class ArticleExcludeInconvenientArticlesTestCase(unittest.TestCase):
    """Test cases for Article.exclude_inconvenient_articles()."""

    @patch("article.models.Article.exclude_repetitions")
    @patch("article.models.Article.get_repeated_items")
    @patch("article.models.Article.exclude_articles_with_invalid_pid_v2")
    def test_calls_both_operations(self, mock_invalid, mock_repeated, mock_exclude_rep):
        """Calls both invalid pid_v2 and repetition removal."""
        mock_invalid.return_value = ["invalid pid_v2 event"]

        mock_repeated_qs = MagicMock()
        mock_repeated_qs.count.return_value = 0
        mock_repeated_qs.__iter__ = Mock(return_value=iter([]))
        mock_repeated.return_value = mock_repeated_qs

        mock_journal = Mock()
        mock_user = Mock()

        results = Article.exclude_inconvenient_articles(mock_journal, mock_user)

        mock_invalid.assert_called_once_with(mock_journal)
        self.assertEqual(mock_repeated.call_count, 2)
        self.assertIn("invalid pid_v2 event", results["events"])

    @patch("article.models.Article.exclude_repetitions")
    @patch("article.models.Article.get_repeated_items")
    @patch("article.models.Article.exclude_articles_with_invalid_pid_v2")
    def test_collects_repetition_events(self, mock_invalid, mock_repeated, mock_exclude_rep):
        """Collects events from repetition removal."""
        mock_invalid.return_value = []
        mock_exclude_rep.return_value = ["repetition event"]

        mock_repeated_qs = MagicMock()
        mock_repeated_qs.count.return_value = 1
        mock_repeated_qs.__iter__ = Mock(return_value=iter(["value1"]))
        mock_repeated.return_value = mock_repeated_qs

        results = Article.exclude_inconvenient_articles(Mock(), Mock())

        self.assertIn("repetition event", results["events"])

    @patch("article.models.Article.exclude_repetitions")
    @patch("article.models.Article.get_repeated_items")
    @patch("article.models.Article.exclude_articles_with_invalid_pid_v2")
    def test_captures_exceptions(self, mock_invalid, mock_repeated, mock_exclude_rep):
        """Captures exceptions without stopping execution."""
        mock_invalid.side_effect = Exception("test error")

        mock_repeated_qs = MagicMock()
        mock_repeated_qs.count.return_value = 0
        mock_repeated_qs.__iter__ = Mock(return_value=iter([]))
        mock_repeated.return_value = mock_repeated_qs

        results = Article.exclude_inconvenient_articles(Mock(), Mock())

        self.assertEqual(len(results["exceptions"]), 1)
        self.assertIn("test error", results["exceptions"][0]["exclude_articles_with_invalid_pid_v2"])


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
