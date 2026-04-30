import unittest
from unittest.mock import MagicMock, Mock, patch

from article.models import Article
from migration.models import MigratedArticle


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


class ArticleExcludeArticlesWithInvalidPidV2TestCase(unittest.TestCase):
    """Test cases for Article.exclude_articles_with_invalid_pid_v2()."""

    def _make_article_proc(self, article_id, pid_v2, sps_pkg_id=1, pp_xml_id=1):
        mock_article = Mock()
        mock_article.id = article_id
        mock_article.pid_v2 = pid_v2
        mock_article.sps_pkg_id = sps_pkg_id
        mock_article.pp_xml_id = pp_xml_id

        mock_article_proc = Mock()
        mock_article_proc.sps_pkg_id = sps_pkg_id
        return mock_article_proc, mock_article

    @patch("migration.models.MigratedArticle.valid_pid", return_value=True)
    @patch("article.models.Article.objects")
    def test_no_invalid_articles(self, mock_article_objects, mock_valid_pid):
        """No articles deleted when all have valid pid_v2."""
        mock_article_proc, mock_article = self._make_article_proc(
            article_id=1, pid_v2="S0034-77442021000600036"
        )

        mock_ap_qs = MagicMock()
        mock_ap_qs.filter.return_value = mock_ap_qs
        mock_ap_qs.select_related.return_value = [mock_article_proc]

        # Article.objects.select_related(...).filter(...).only(...) chain
        mock_article_filter_qs = MagicMock()
        mock_article_filter_qs.only.return_value = [mock_article]
        mock_article_select_qs = MagicMock()
        mock_article_select_qs.filter.return_value = mock_article_filter_qs
        mock_article_objects.select_related.return_value = mock_article_select_qs

        with patch("proc.models.ArticleProc.objects", mock_ap_qs):
            events = Article.exclude_articles_with_invalid_pid_v2()

        self.assertIn("No migrated articles with invalid pid_v2 found", events)

    @patch("article.models.transaction")
    @patch("article.models.PidProviderXML")
    @patch("article.models.SPSPkg")
    @patch("migration.models.MigratedArticle.valid_pid", return_value=False)
    @patch("article.models.Article.objects")
    def test_deletes_invalid_article(self, mock_article_objects, mock_valid_pid, mock_sps_pkg, mock_pp_xml, mock_transaction):
        """Deletes migrated article with invalid pid_v2."""
        mock_article_proc, mock_article = self._make_article_proc(
            article_id=42, pid_v2="S0034-77442021060626158",
            sps_pkg_id=10, pp_xml_id=20
        )

        mock_ap_qs = MagicMock()
        mock_ap_qs.filter.return_value = mock_ap_qs
        mock_ap_qs.select_related.return_value = [mock_article_proc]

        # Article.objects.select_related(...).filter(...).only(...) — bulk-fetch articles
        mock_article_filter_qs = MagicMock()
        mock_article_filter_qs.only.return_value = [mock_article]
        mock_article_select_qs = MagicMock()
        mock_article_select_qs.filter.return_value = mock_article_filter_qs
        mock_article_objects.select_related.return_value = mock_article_select_qs

        # Article.objects.filter(id__in=...).delete() — delete invalid articles
        mock_delete_qs = MagicMock()
        mock_delete_qs.delete.return_value = (1, {})
        mock_article_objects.filter.return_value = mock_delete_qs

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

        self.assertTrue(any("Articles deletados" in e for e in events))

    def test_with_issue_filter(self):
        """Filters ArticleProc by issue when provided."""
        mock_issue = Mock()

        mock_ap_qs = MagicMock()
        mock_ap_qs.filter.return_value = mock_ap_qs
        mock_ap_qs.select_related.return_value = []

        with patch("proc.models.ArticleProc.objects", mock_ap_qs):
            events = Article.exclude_articles_with_invalid_pid_v2(issue=mock_issue)

        mock_ap_qs.filter.assert_called_once_with(
            pid__isnull=False,
            migrated_data__isnull=False,
            sps_pkg__isnull=False,
            issue_proc__issue=mock_issue,
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

        mock_issue = Mock()
        mock_user = Mock()

        results = Article.exclude_inconvenient_articles(mock_issue, mock_user)

        mock_invalid.assert_called_once_with(mock_issue)
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
