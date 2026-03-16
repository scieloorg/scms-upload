import os
import tempfile
from unittest import TestCase
from unittest.mock import MagicMock, Mock, patch, PropertyMock

from proc.source_classic_website import track_classic_website_article_pids


class TestTrackClassicWebsiteArticlePids(TestCase):
    def setUp(self):
        self.user = Mock()
        self.user.id = 1
        self.user.username = "testuser"
        self.collection = Mock()
        self.collection.acron = "scl"
        self.classic_website_config = Mock()

    @patch("proc.source_classic_website.ArticleProc")
    def test_returns_none_when_no_classic_pids(self, mock_article_proc):
        self.classic_website_config.pid_list = set()
        result = track_classic_website_article_pids(
            self.user, self.collection, self.classic_website_config
        )
        self.assertIsNone(result)

    @patch("proc.source_classic_website.ArticleProc")
    def test_identifies_missing_pids(self, mock_article_proc):
        classic_pids = {
            "S0001-37652000000100001",
            "S0001-37652000000100002",
            "S0001-37652000000100003",
        }
        self.classic_website_config.pid_list = classic_pids

        mock_article_proc.objects.filter.return_value.values_list.return_value = [
            "S0001-37652000000100001",
        ]

        result = track_classic_website_article_pids(
            self.user, self.collection, self.classic_website_config
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["classic_website_total"], 3)
        self.assertEqual(result["migrated_total"], 1)

        missing_item = result["items"][0]
        self.assertEqual(missing_item["type"], "MISSING")
        self.assertEqual(missing_item["criticality"], "CRITICAL")
        self.assertEqual(missing_item["total"], 2)
        self.assertIn("S0001-37652000000100002", missing_item["pids"])
        self.assertIn("S0001-37652000000100003", missing_item["pids"])

    @patch("proc.source_classic_website.ArticleProc")
    def test_identifies_excess_pids(self, mock_article_proc):
        classic_pids = {
            "S0001-37652000000100001",
        }
        self.classic_website_config.pid_list = classic_pids

        mock_article_proc.objects.filter.return_value.values_list.return_value = [
            "S0001-37652000000100001",
            "S0001-37652000000100099",
        ]

        result = track_classic_website_article_pids(
            self.user, self.collection, self.classic_website_config
        )

        self.assertIsNotNone(result)
        excess_item = result["items"][1]
        self.assertEqual(excess_item["type"], "EXCESS")
        self.assertEqual(excess_item["criticality"], "WARNING")
        self.assertEqual(excess_item["total"], 1)
        self.assertIn("S0001-37652000000100099", excess_item["pids"])

    @patch("proc.source_classic_website.ArticleProc")
    def test_all_pids_match(self, mock_article_proc):
        classic_pids = {
            "S0001-37652000000100001",
            "S0001-37652000000100002",
        }
        self.classic_website_config.pid_list = classic_pids

        mock_article_proc.objects.filter.return_value.values_list.return_value = [
            "S0001-37652000000100001",
            "S0001-37652000000100002",
        ]

        result = track_classic_website_article_pids(
            self.user, self.collection, self.classic_website_config
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["classic_website_total"], 2)
        self.assertEqual(result["migrated_total"], 2)
        self.assertEqual(result["items"][0]["total"], 0)
        self.assertEqual(result["items"][1]["total"], 0)

    @patch("proc.source_classic_website.ArticleProc")
    def test_identifies_both_missing_and_excess(self, mock_article_proc):
        classic_pids = {
            "S0001-37652000000100001",
            "S0001-37652000000100002",
        }
        self.classic_website_config.pid_list = classic_pids

        mock_article_proc.objects.filter.return_value.values_list.return_value = [
            "S0001-37652000000100001",
            "S0001-37652000000100099",
        ]

        result = track_classic_website_article_pids(
            self.user, self.collection, self.classic_website_config
        )

        self.assertIsNotNone(result)
        missing_item = result["items"][0]
        excess_item = result["items"][1]

        self.assertEqual(missing_item["total"], 1)
        self.assertIn("S0001-37652000000100002", missing_item["pids"])

        self.assertEqual(excess_item["total"], 1)
        self.assertIn("S0001-37652000000100099", excess_item["pids"])

    @patch("proc.source_classic_website.ArticleProc")
    def test_result_contains_collection_acron(self, mock_article_proc):
        self.classic_website_config.pid_list = {"S0001-37652000000100001"}
        mock_article_proc.objects.filter.return_value.values_list.return_value = []

        result = track_classic_website_article_pids(
            self.user, self.collection, self.classic_website_config
        )
        self.assertEqual(result["collection"], "scl")


class TestClassicWebsiteConfigurationPidList(TestCase):
    def test_reads_pids_from_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("S0001-37652000000100001\n")
            f.write("S0001-37652000000100002\n")
            f.write("short\n")
            f.write("S0001-37652000000100003\n")
            temp_path = f.name
        try:
            from migration.models import ClassicWebsiteConfiguration
            config_instance = Mock(spec=ClassicWebsiteConfiguration)
            config_instance.pid_list_path = temp_path

            pids = ClassicWebsiteConfiguration.get_pid_list(config_instance)
            self.assertEqual(len(pids), 3)
            self.assertIn("S0001-37652000000100001", pids)
            self.assertIn("S0001-37652000000100002", pids)
            self.assertIn("S0001-37652000000100003", pids)
        finally:
            os.unlink(temp_path)

    def test_returns_empty_set_when_no_path(self):
        from migration.models import ClassicWebsiteConfiguration
        config_instance = Mock(spec=ClassicWebsiteConfiguration)
        config_instance.pid_list_path = None

        pids = ClassicWebsiteConfiguration.get_pid_list(config_instance)
        self.assertEqual(pids, set())

    def test_returns_empty_set_when_file_not_found(self):
        from migration.models import ClassicWebsiteConfiguration
        config_instance = Mock(spec=ClassicWebsiteConfiguration)
        config_instance.pid_list_path = "/nonexistent/path/to/file.txt"

        pids = ClassicWebsiteConfiguration.get_pid_list(config_instance)
        self.assertEqual(pids, set())
