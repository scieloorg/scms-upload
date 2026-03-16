import os
import tempfile
from unittest import TestCase
from unittest.mock import MagicMock, Mock, patch, PropertyMock

from proc.source_classic_website import track_classic_website_article_pids, BATCH_SIZE


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

        # Mock for missing check: only one PID exists in DB
        mock_filter = mock_article_proc.objects.filter
        mock_filter.return_value.values_list.return_value = (
            Mock(iterator=Mock(return_value=iter(["S0001-37652000000100001"])))
        )
        # For the batch query (pid__in), return existing PIDs
        def filter_side_effect(**kwargs):
            result_mock = Mock()
            if "pid__in" in kwargs:
                batch = kwargs["pid__in"]
                existing = [p for p in batch if p == "S0001-37652000000100001"]
                result_mock.values_list.return_value = existing
            else:
                vl_mock = Mock()
                vl_mock.iterator.return_value = iter(["S0001-37652000000100001"])
                result_mock.values_list.return_value = vl_mock
            return result_mock

        mock_filter.side_effect = filter_side_effect

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

    @patch("proc.source_classic_website.ArticleProc")
    def test_identifies_excess_pids(self, mock_article_proc):
        classic_pids = {
            "S0001-37652000000100001",
        }
        self.classic_website_config.pid_list = classic_pids

        def filter_side_effect(**kwargs):
            result_mock = Mock()
            if "pid__in" in kwargs:
                batch = kwargs["pid__in"]
                existing = [p for p in batch if p in classic_pids]
                result_mock.values_list.return_value = existing
            else:
                vl_mock = Mock()
                vl_mock.iterator.return_value = iter([
                    "S0001-37652000000100001",
                    "S0001-37652000000100099",
                ])
                result_mock.values_list.return_value = vl_mock
            return result_mock

        mock_article_proc.objects.filter.side_effect = filter_side_effect

        result = track_classic_website_article_pids(
            self.user, self.collection, self.classic_website_config
        )

        self.assertIsNotNone(result)
        excess_item = result["items"][1]
        self.assertEqual(excess_item["type"], "EXCESS")
        self.assertEqual(excess_item["criticality"], "WARNING")
        self.assertEqual(excess_item["total"], 1)

    @patch("proc.source_classic_website.ArticleProc")
    def test_all_pids_match(self, mock_article_proc):
        classic_pids = {
            "S0001-37652000000100001",
            "S0001-37652000000100002",
        }
        self.classic_website_config.pid_list = classic_pids

        def filter_side_effect(**kwargs):
            result_mock = Mock()
            if "pid__in" in kwargs:
                batch = kwargs["pid__in"]
                existing = [p for p in batch if p in classic_pids]
                result_mock.values_list.return_value = existing
            else:
                vl_mock = Mock()
                vl_mock.iterator.return_value = iter([
                    "S0001-37652000000100001",
                    "S0001-37652000000100002",
                ])
                result_mock.values_list.return_value = vl_mock
            return result_mock

        mock_article_proc.objects.filter.side_effect = filter_side_effect

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

        def filter_side_effect(**kwargs):
            result_mock = Mock()
            if "pid__in" in kwargs:
                batch = kwargs["pid__in"]
                # Only pid001 exists in DB
                existing = [p for p in batch if p == "S0001-37652000000100001"]
                result_mock.values_list.return_value = existing
            else:
                vl_mock = Mock()
                vl_mock.iterator.return_value = iter([
                    "S0001-37652000000100001",
                    "S0001-37652000000100099",
                ])
                result_mock.values_list.return_value = vl_mock
            return result_mock

        mock_article_proc.objects.filter.side_effect = filter_side_effect

        result = track_classic_website_article_pids(
            self.user, self.collection, self.classic_website_config
        )

        self.assertIsNotNone(result)
        missing_item = result["items"][0]
        excess_item = result["items"][1]

        self.assertEqual(missing_item["total"], 1)
        self.assertEqual(excess_item["total"], 1)

    @patch("proc.source_classic_website.ArticleProc")
    def test_result_contains_collection_acron(self, mock_article_proc):
        self.classic_website_config.pid_list = {"S0001-37652000000100001"}

        def filter_side_effect(**kwargs):
            result_mock = Mock()
            if "pid__in" in kwargs:
                result_mock.values_list.return_value = []
            else:
                vl_mock = Mock()
                vl_mock.iterator.return_value = iter([])
                result_mock.values_list.return_value = vl_mock
            return result_mock

        mock_article_proc.objects.filter.side_effect = filter_side_effect

        result = track_classic_website_article_pids(
            self.user, self.collection, self.classic_website_config
        )
        self.assertEqual(result["collection"], "scl")

    @patch("proc.source_classic_website.ArticleProc")
    def test_result_does_not_contain_pid_lists(self, mock_article_proc):
        """Verify result only contains totals, not full PID lists (memory safety)."""
        classic_pids = {
            "S0001-37652000000100001",
            "S0001-37652000000100002",
        }
        self.classic_website_config.pid_list = classic_pids

        def filter_side_effect(**kwargs):
            result_mock = Mock()
            if "pid__in" in kwargs:
                result_mock.values_list.return_value = []
            else:
                vl_mock = Mock()
                vl_mock.iterator.return_value = iter(["S0001-37652000000100099"])
                result_mock.values_list.return_value = vl_mock
            return result_mock

        mock_article_proc.objects.filter.side_effect = filter_side_effect

        result = track_classic_website_article_pids(
            self.user, self.collection, self.classic_website_config
        )

        self.assertNotIn("pids", result["items"][0])
        self.assertNotIn("pids", result["items"][1])

    @patch("proc.source_classic_website.ArticleProc")
    def test_processes_multiple_batches(self, mock_article_proc):
        """Verify correct results when PIDs exceed BATCH_SIZE requiring multiple batches."""
        # Create PIDs exceeding BATCH_SIZE (2.5x to ensure multiple batches)
        total_pids = int(BATCH_SIZE * 2.5)
        classic_pids = {f"S0001-3765200000{i:07d}" for i in range(total_pids)}
        # Half of them exist in DB
        existing_in_db = {f"S0001-3765200000{i:07d}" for i in range(0, total_pids, 2)}
        # Some extra PIDs only in DB
        extra_db_pids = {f"S0001-3765200000{i:07d}" for i in range(total_pids, total_pids + 100)}

        self.classic_website_config.pid_list = classic_pids

        def filter_side_effect(**kwargs):
            result_mock = Mock()
            if "pid__in" in kwargs:
                batch = kwargs["pid__in"]
                found = [p for p in batch if p in existing_in_db]
                result_mock.values_list.return_value = found
            else:
                all_db_pids = list(existing_in_db | extra_db_pids)
                vl_mock = Mock()
                vl_mock.iterator.return_value = iter(all_db_pids)
                result_mock.values_list.return_value = vl_mock
            return result_mock

        mock_article_proc.objects.filter.side_effect = filter_side_effect

        result = track_classic_website_article_pids(
            self.user, self.collection, self.classic_website_config
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["classic_website_total"], total_pids)
        expected_missing = total_pids - len(existing_in_db)
        self.assertEqual(result["items"][0]["total"], expected_missing)
        self.assertEqual(result["items"][1]["total"], 100)  # extra DB PIDs


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
