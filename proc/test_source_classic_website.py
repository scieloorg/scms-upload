import os
import tempfile
from unittest import TestCase
from unittest.mock import Mock, patch

from proc.source_classic_website import track_classic_website_article_pids


class TestTrackClassicWebsiteArticlePids(TestCase):
    def setUp(self):
        self.user = Mock()
        self.user.id = 1
        self.user.username = "testuser"
        self.collection = Mock()
        self.collection.acron = "scl"
        self.classic_website_config = Mock()

    @patch(
        "proc.source_classic_website.ClassicWebsiteArticlePidTracker._store_pid_list"
    )
    @patch(
        "proc.source_classic_website.ClassicWebsiteArticlePidTracker._get_stored_pid_list",
        return_value=set(),
    )
    @patch("proc.source_classic_website.MigratedArticle")
    @patch("proc.source_classic_website.ArticleProc")
    def test_returns_none_when_no_classic_pids(
        self, mock_article_proc, mock_migrated, mock_get_stored, mock_store
    ):
        self.classic_website_config.pid_list = set()
        result = track_classic_website_article_pids(
            self.user, self.collection, self.classic_website_config
        )
        self.assertIsNone(result)

    @patch(
        "proc.source_classic_website.ClassicWebsiteArticlePidTracker._store_pid_list"
    )
    @patch(
        "proc.source_classic_website.ClassicWebsiteArticlePidTracker._get_stored_pid_list",
        return_value=set(),
    )
    @patch("proc.source_classic_website.MigratedArticle")
    @patch("proc.source_classic_website.ArticleProc")
    def test_sets_missing_status_when_no_data(
        self, mock_article_proc, mock_migrated, mock_get_stored, mock_store
    ):
        """PIDs in classic list where MigratedArticle has no data → pid_status = missing."""
        classic_pids = {
            "S0001-37652000000100001",
            "S0001-37652000000100002",
        }
        self.classic_website_config.pid_list = classic_pids

        # MigratedArticle stubs with no data
        migrated_stub = Mock()
        migrated_stub.data = None
        mock_migrated.create_or_update_migrated_data.return_value = migrated_stub

        # ArticleProc stubs
        article_proc_stub = Mock()
        article_proc_stub.migrated_data = None
        mock_article_proc.get_or_create.return_value = article_proc_stub

        # No exceeding records
        mock_article_proc.objects.filter.return_value.only.return_value.iterator.return_value = iter([])
        mock_migrated.objects.filter.return_value.only.return_value.iterator.return_value = iter([])

        result = track_classic_website_article_pids(
            self.user, self.collection, self.classic_website_config
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["items"][0]["type"], "MISSING")
        self.assertEqual(result["items"][0]["total"], 2)
        self.assertEqual(result["items"][1]["type"], "MATCHED")
        self.assertEqual(result["items"][1]["total"], 0)
        # Verify bulk update was called for missing status
        mock_article_proc.objects.filter.return_value.update.assert_called()

    @patch(
        "proc.source_classic_website.ClassicWebsiteArticlePidTracker._store_pid_list"
    )
    @patch(
        "proc.source_classic_website.ClassicWebsiteArticlePidTracker._get_stored_pid_list",
        return_value=set(),
    )
    @patch("proc.source_classic_website.MigratedArticle")
    @patch("proc.source_classic_website.ArticleProc")
    def test_sets_matched_status_when_has_data(
        self, mock_article_proc, mock_migrated, mock_get_stored, mock_store
    ):
        """PIDs in classic list where MigratedArticle has data → pid_status = matched."""
        classic_pids = {
            "S0001-37652000000100001",
            "S0001-37652000000100002",
        }
        self.classic_website_config.pid_list = classic_pids

        # MigratedArticle with data
        migrated_with_data = Mock()
        migrated_with_data.data = {"some": "data"}
        mock_migrated.create_or_update_migrated_data.return_value = migrated_with_data

        article_proc_stub = Mock()
        article_proc_stub.migrated_data = migrated_with_data
        mock_article_proc.get_or_create.return_value = article_proc_stub

        # No exceeding records
        mock_article_proc.objects.filter.return_value.only.return_value.iterator.return_value = iter([])
        mock_migrated.objects.filter.return_value.only.return_value.iterator.return_value = iter([])

        result = track_classic_website_article_pids(
            self.user, self.collection, self.classic_website_config
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["items"][0]["type"], "MISSING")
        self.assertEqual(result["items"][0]["total"], 0)
        self.assertEqual(result["items"][1]["type"], "MATCHED")
        self.assertEqual(result["items"][1]["total"], 2)
        # Verify bulk update was called for matched status
        mock_article_proc.objects.filter.return_value.update.assert_called()

    @patch(
        "proc.source_classic_website.ClassicWebsiteArticlePidTracker._store_pid_list"
    )
    @patch(
        "proc.source_classic_website.ClassicWebsiteArticlePidTracker._get_stored_pid_list",
        return_value=set(),
    )
    @patch("proc.source_classic_website.UnexpectedEvent")
    @patch("proc.source_classic_website.MigratedArticle")
    @patch("proc.source_classic_website.ArticleProc")
    def test_sets_exceeding_status_and_creates_event(
        self, mock_article_proc, mock_migrated, mock_unexpected_event,
        mock_get_stored, mock_store
    ):
        """ArticleProc PIDs not in classic list → pid_status = exceeding + UnexpectedEvent."""
        classic_pids = {
            "S0001-37652000000100001",
        }
        self.classic_website_config.pid_list = classic_pids

        # MigratedArticle with data for classic PID
        migrated_with_data = Mock()
        migrated_with_data.data = {"some": "data"}
        mock_migrated.create_or_update_migrated_data.return_value = migrated_with_data

        article_proc_stub = Mock()
        article_proc_stub.migrated_data = migrated_with_data
        mock_article_proc.get_or_create.return_value = article_proc_stub

        # Exceeding ArticleProc (PID not in classic list)
        exceeding_article = Mock()
        exceeding_article.pid = "S0001-37652000000100099"
        mock_article_proc.objects.filter.return_value.only.return_value.iterator.return_value = iter(
            [exceeding_article]
        )

        # No exceeding MigratedArticles
        mock_migrated.objects.filter.return_value.only.return_value.iterator.return_value = iter([])

        result = track_classic_website_article_pids(
            self.user, self.collection, self.classic_website_config
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["items"][2]["type"], "EXCEEDING")
        self.assertEqual(result["items"][2]["total"], 1)
        # Verify UnexpectedEvent was created for exceeding PID
        mock_unexpected_event.create.assert_called()

    @patch(
        "proc.source_classic_website.ClassicWebsiteArticlePidTracker._store_pid_list"
    )
    @patch(
        "proc.source_classic_website.ClassicWebsiteArticlePidTracker._get_stored_pid_list",
        return_value=set(),
    )
    @patch("proc.source_classic_website.UnexpectedEvent")
    @patch("proc.source_classic_website.MigratedArticle")
    @patch("proc.source_classic_website.ArticleProc")
    def test_creates_event_for_exceeding_migrated_article(
        self, mock_article_proc, mock_migrated, mock_unexpected_event,
        mock_get_stored, mock_store
    ):
        """MigratedArticle PIDs not in classic list → UnexpectedEvent."""
        classic_pids = {
            "S0001-37652000000100001",
        }
        self.classic_website_config.pid_list = classic_pids

        migrated_with_data = Mock()
        migrated_with_data.data = {"some": "data"}
        mock_migrated.create_or_update_migrated_data.return_value = migrated_with_data

        article_proc_stub = Mock()
        article_proc_stub.migrated_data = migrated_with_data
        mock_article_proc.get_or_create.return_value = article_proc_stub

        # No exceeding ArticleProcs
        mock_article_proc.objects.filter.return_value.only.return_value.iterator.return_value = iter([])

        # Exceeding MigratedArticle
        exceeding_migrated = Mock()
        exceeding_migrated.pid = "S0001-37652000000100099"
        mock_migrated.objects.filter.return_value.only.return_value.iterator.return_value = iter(
            [exceeding_migrated]
        )

        result = track_classic_website_article_pids(
            self.user, self.collection, self.classic_website_config
        )

        self.assertIsNotNone(result)
        mock_unexpected_event.create.assert_called()

    @patch(
        "proc.source_classic_website.ClassicWebsiteArticlePidTracker._store_pid_list"
    )
    @patch(
        "proc.source_classic_website.ClassicWebsiteArticlePidTracker._get_stored_pid_list",
        return_value=set(),
    )
    @patch("proc.source_classic_website.MigratedArticle")
    @patch("proc.source_classic_website.ArticleProc")
    def test_links_migrated_data_to_article_proc(
        self, mock_article_proc, mock_migrated, mock_get_stored, mock_store
    ):
        """Verify ArticleProc.migrated_data is linked when not already set."""
        classic_pids = {"S0001-37652000000100001"}
        self.classic_website_config.pid_list = classic_pids

        migrated_stub = Mock()
        migrated_stub.data = {"some": "data"}
        mock_migrated.create_or_update_migrated_data.return_value = migrated_stub

        article_proc_stub = Mock()
        article_proc_stub.migrated_data = None
        mock_article_proc.get_or_create.return_value = article_proc_stub

        # No exceeding records
        mock_article_proc.objects.filter.return_value.only.return_value.iterator.return_value = iter([])
        mock_migrated.objects.filter.return_value.only.return_value.iterator.return_value = iter([])

        result = track_classic_website_article_pids(
            self.user, self.collection, self.classic_website_config
        )

        self.assertIsNotNone(result)
        # Verify migrated_data was linked
        self.assertEqual(article_proc_stub.migrated_data, migrated_stub)
        # save() is called to persist the migrated_data link
        article_proc_stub.save.assert_called_once()

    @patch(
        "proc.source_classic_website.ClassicWebsiteArticlePidTracker._store_pid_list"
    )
    @patch(
        "proc.source_classic_website.ClassicWebsiteArticlePidTracker._get_stored_pid_list",
        return_value=set(),
    )
    @patch("proc.source_classic_website.MigratedArticle")
    @patch("proc.source_classic_website.ArticleProc")
    def test_result_contains_collection_acron(
        self, mock_article_proc, mock_migrated, mock_get_stored, mock_store
    ):
        self.classic_website_config.pid_list = {"S0001-37652000000100001"}

        migrated_stub = Mock()
        migrated_stub.data = None
        mock_migrated.create_or_update_migrated_data.return_value = migrated_stub

        article_proc_stub = Mock()
        article_proc_stub.migrated_data = None
        mock_article_proc.get_or_create.return_value = article_proc_stub

        mock_article_proc.objects.filter.return_value.only.return_value.iterator.return_value = iter([])
        mock_migrated.objects.filter.return_value.only.return_value.iterator.return_value = iter([])

        result = track_classic_website_article_pids(
            self.user, self.collection, self.classic_website_config
        )
        self.assertEqual(result["collection"], "scl")

    @patch(
        "proc.source_classic_website.ClassicWebsiteArticlePidTracker._store_pid_list"
    )
    @patch(
        "proc.source_classic_website.ClassicWebsiteArticlePidTracker._get_stored_pid_list",
        return_value=set(),
    )
    @patch("proc.source_classic_website.MigratedArticle")
    @patch("proc.source_classic_website.ArticleProc")
    def test_result_has_three_items(
        self, mock_article_proc, mock_migrated, mock_get_stored, mock_store
    ):
        """Result should have MISSING, MATCHED, and EXCEEDING items."""
        self.classic_website_config.pid_list = {"S0001-37652000000100001"}

        migrated_stub = Mock()
        migrated_stub.data = {"some": "data"}
        mock_migrated.create_or_update_migrated_data.return_value = migrated_stub

        article_proc_stub = Mock()
        article_proc_stub.migrated_data = migrated_stub
        mock_article_proc.get_or_create.return_value = article_proc_stub

        mock_article_proc.objects.filter.return_value.only.return_value.iterator.return_value = iter([])
        mock_migrated.objects.filter.return_value.only.return_value.iterator.return_value = iter([])

        result = track_classic_website_article_pids(
            self.user, self.collection, self.classic_website_config
        )
        self.assertEqual(len(result["items"]), 3)
        types = [item["type"] for item in result["items"]]
        self.assertEqual(types, ["MISSING", "MATCHED", "EXCEEDING"])

    @patch(
        "proc.source_classic_website.ClassicWebsiteArticlePidTracker._store_pid_list"
    )
    @patch(
        "proc.source_classic_website.ClassicWebsiteArticlePidTracker._get_stored_pid_list",
        return_value=set(),
    )
    @patch("proc.source_classic_website.MigratedArticle")
    @patch("proc.source_classic_website.ArticleProc")
    def test_empty_data_dict_treated_as_missing(
        self, mock_article_proc, mock_migrated, mock_get_stored, mock_store
    ):
        """MigratedArticle with data={} should be treated as missing (not migrated)."""
        classic_pids = {"S0001-37652000000100001"}
        self.classic_website_config.pid_list = classic_pids

        migrated_stub = Mock()
        migrated_stub.data = {}
        mock_migrated.create_or_update_migrated_data.return_value = migrated_stub

        article_proc_stub = Mock()
        article_proc_stub.migrated_data = None
        mock_article_proc.get_or_create.return_value = article_proc_stub

        mock_article_proc.objects.filter.return_value.only.return_value.iterator.return_value = iter([])
        mock_migrated.objects.filter.return_value.only.return_value.iterator.return_value = iter([])

        result = track_classic_website_article_pids(
            self.user, self.collection, self.classic_website_config
        )

        self.assertEqual(result["items"][0]["total"], 1)  # missing
        self.assertEqual(result["items"][1]["total"], 0)  # matched


class TestTrackClassicWebsiteArticlePidsDiffMode(TestCase):
    """Tests for diff mode: only process PIDs added/removed since last run."""

    def setUp(self):
        self.user = Mock()
        self.user.id = 1
        self.user.username = "testuser"
        self.collection = Mock()
        self.collection.acron = "scl"
        self.classic_website_config = Mock()

    @patch(
        "proc.source_classic_website.ClassicWebsiteArticlePidTracker._store_pid_list"
    )
    @patch(
        "proc.source_classic_website.ClassicWebsiteArticlePidTracker._get_stored_pid_list"
    )
    @patch("proc.source_classic_website.MigratedArticle")
    @patch("proc.source_classic_website.ArticleProc")
    def test_diff_mode_processes_only_added_pids(
        self, mock_article_proc, mock_migrated, mock_get_stored, mock_store
    ):
        """In diff mode, only new PIDs (current - previous) should be processed."""
        previous_pids = {"S0001-37652000000100001"}
        current_pids = {
            "S0001-37652000000100001",
            "S0001-37652000000100002",
        }
        mock_get_stored.return_value = previous_pids
        self.classic_website_config.pid_list = current_pids

        migrated_stub = Mock()
        migrated_stub.data = None
        mock_migrated.create_or_update_migrated_data.return_value = migrated_stub

        article_proc_stub = Mock()
        article_proc_stub.migrated_data = None
        mock_article_proc.get_or_create.return_value = article_proc_stub

        result = track_classic_website_article_pids(
            self.user, self.collection, self.classic_website_config
        )

        self.assertIsNotNone(result)
        # Only the new PID (S0001-37652000000100002) should be processed
        self.assertEqual(result["items"][0]["total"], 1)  # missing
        # Only 1 call to create_or_update_migrated_data (for the new PID)
        self.assertEqual(
            mock_migrated.create_or_update_migrated_data.call_count, 1
        )

    @patch(
        "proc.source_classic_website.ClassicWebsiteArticlePidTracker._store_pid_list"
    )
    @patch(
        "proc.source_classic_website.ClassicWebsiteArticlePidTracker._get_stored_pid_list"
    )
    @patch("proc.source_classic_website.UnexpectedEvent")
    @patch("proc.source_classic_website.MigratedArticle")
    @patch("proc.source_classic_website.ArticleProc")
    def test_diff_mode_marks_removed_pids_as_exceeding(
        self, mock_article_proc, mock_migrated, mock_unexpected_event,
        mock_get_stored, mock_store
    ):
        """In diff mode, removed PIDs should be marked as exceeding."""
        previous_pids = {
            "S0001-37652000000100001",
            "S0001-37652000000100099",
        }
        current_pids = {"S0001-37652000000100001"}
        mock_get_stored.return_value = previous_pids
        self.classic_website_config.pid_list = current_pids

        migrated_stub = Mock()
        migrated_stub.data = {"some": "data"}
        mock_migrated.create_or_update_migrated_data.return_value = migrated_stub

        article_proc_stub = Mock()
        article_proc_stub.migrated_data = migrated_stub
        mock_article_proc.get_or_create.return_value = article_proc_stub

        result = track_classic_website_article_pids(
            self.user, self.collection, self.classic_website_config
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["items"][2]["total"], 1)  # exceeding
        # Verify bulk update was called for exceeding
        mock_article_proc.objects.filter.return_value.update.assert_called()
        # Verify UnexpectedEvent was created
        mock_unexpected_event.create.assert_called()

    @patch(
        "proc.source_classic_website.ClassicWebsiteArticlePidTracker._store_pid_list"
    )
    @patch(
        "proc.source_classic_website.ClassicWebsiteArticlePidTracker._get_stored_pid_list"
    )
    @patch("proc.source_classic_website.MigratedArticle")
    @patch("proc.source_classic_website.ArticleProc")
    def test_diff_mode_no_changes_returns_zero_counts(
        self, mock_article_proc, mock_migrated, mock_get_stored, mock_store
    ):
        """When previous = current (no diff), no PIDs should be processed."""
        same_pids = {"S0001-37652000000100001"}
        mock_get_stored.return_value = same_pids
        self.classic_website_config.pid_list = same_pids

        result = track_classic_website_article_pids(
            self.user, self.collection, self.classic_website_config
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["items"][0]["total"], 0)  # missing
        self.assertEqual(result["items"][1]["total"], 0)  # matched
        self.assertEqual(result["items"][2]["total"], 0)  # exceeding
        # No MigratedArticle creation should happen
        mock_migrated.create_or_update_migrated_data.assert_not_called()

    @patch(
        "proc.source_classic_website.ClassicWebsiteArticlePidTracker._store_pid_list"
    )
    @patch(
        "proc.source_classic_website.ClassicWebsiteArticlePidTracker._get_stored_pid_list"
    )
    @patch("proc.source_classic_website.MigratedArticle")
    @patch("proc.source_classic_website.ArticleProc")
    def test_force_update_processes_all_pids(
        self, mock_article_proc, mock_migrated, mock_get_stored, mock_store
    ):
        """With force_update=True, all PIDs should be processed regardless of previous version."""
        previous_pids = {"S0001-37652000000100001"}
        current_pids = {
            "S0001-37652000000100001",
            "S0001-37652000000100002",
        }
        mock_get_stored.return_value = previous_pids
        self.classic_website_config.pid_list = current_pids

        migrated_stub = Mock()
        migrated_stub.data = None
        mock_migrated.create_or_update_migrated_data.return_value = migrated_stub

        article_proc_stub = Mock()
        article_proc_stub.migrated_data = None
        mock_article_proc.get_or_create.return_value = article_proc_stub

        # No exceeding records
        mock_article_proc.objects.filter.return_value.only.return_value.iterator.return_value = iter([])
        mock_migrated.objects.filter.return_value.only.return_value.iterator.return_value = iter([])

        result = track_classic_website_article_pids(
            self.user, self.collection, self.classic_website_config,
            force_update=True,
        )

        self.assertIsNotNone(result)
        # All 2 PIDs should be processed (not just the diff)
        self.assertEqual(result["items"][0]["total"], 2)  # missing
        # _get_stored_pid_list should NOT be called with force_update=True
        mock_get_stored.assert_not_called()

    @patch(
        "proc.source_classic_website.ClassicWebsiteArticlePidTracker._store_pid_list"
    )
    @patch(
        "proc.source_classic_website.ClassicWebsiteArticlePidTracker._get_stored_pid_list",
        return_value=set(),
    )
    @patch("proc.source_classic_website.MigratedArticle")
    @patch("proc.source_classic_website.ArticleProc")
    def test_first_run_without_previous_processes_all(
        self, mock_article_proc, mock_migrated, mock_get_stored, mock_store
    ):
        """First run (no previous MigratedFile) should process all PIDs."""
        current_pids = {
            "S0001-37652000000100001",
            "S0001-37652000000100002",
        }
        self.classic_website_config.pid_list = current_pids

        migrated_stub = Mock()
        migrated_stub.data = {"some": "data"}
        mock_migrated.create_or_update_migrated_data.return_value = migrated_stub

        article_proc_stub = Mock()
        article_proc_stub.migrated_data = migrated_stub
        mock_article_proc.get_or_create.return_value = article_proc_stub

        # No exceeding records
        mock_article_proc.objects.filter.return_value.only.return_value.iterator.return_value = iter([])
        mock_migrated.objects.filter.return_value.only.return_value.iterator.return_value = iter([])

        result = track_classic_website_article_pids(
            self.user, self.collection, self.classic_website_config
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["items"][1]["total"], 2)  # matched
        self.assertEqual(
            mock_migrated.create_or_update_migrated_data.call_count, 2
        )


class TestClassicWebsiteConfigurationPidList(TestCase):
    def test_reads_pids_from_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("S0001-37652000000100001\n")
            f.write("S0001-37652000000100002\n")
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
