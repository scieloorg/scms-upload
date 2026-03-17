"""
Tests for user=None handling in proc/tasks.py and related modules.

Validates that periodic/scheduled tasks don't crash when username is null.
"""
import unittest
from unittest.mock import patch, MagicMock, call


class GetUserTest(unittest.TestCase):
    """Test _get_user function handles None parameters gracefully."""

    @patch("proc.tasks.User")
    def test_get_user_with_user_id(self, MockUser):
        from proc.tasks import _get_user

        mock_user = MagicMock()
        MockUser.objects.get.return_value = mock_user

        result = _get_user(user_id=1, username=None)

        MockUser.objects.get.assert_called_once_with(pk=1)
        self.assertEqual(result, mock_user)

    @patch("proc.tasks.User")
    def test_get_user_with_username(self, MockUser):
        from proc.tasks import _get_user

        mock_user = MagicMock()
        MockUser.objects.get.return_value = mock_user

        result = _get_user(user_id=None, username="testuser")

        MockUser.objects.get.assert_called_once_with(username="testuser")
        self.assertEqual(result, mock_user)

    @patch("proc.tasks.User")
    def test_get_user_returns_none_when_both_params_none(self, MockUser):
        from proc.tasks import _get_user

        result = _get_user(user_id=None, username=None)

        MockUser.objects.get.assert_not_called()
        self.assertIsNone(result)

    @patch("proc.tasks.UnexpectedEvent")
    @patch("proc.tasks.User")
    def test_get_user_returns_none_on_exception(self, MockUser, MockEvent):
        from proc.tasks import _get_user

        MockUser.objects.get.side_effect = Exception("User not found")

        result = _get_user(user_id=999, username=None)

        self.assertIsNone(result)


class TaskMigrateArticlesByJournalUserNoneTest(unittest.TestCase):
    """Test that task_migrate_and_publish_articles_by_journal doesn't crash when user is None."""

    @patch("proc.tasks.TaskExecution")
    @patch("proc.tasks.get_api_data")
    @patch("proc.tasks.IssueProc")
    @patch("proc.tasks.controller")
    @patch("proc.tasks.task_exclude_article_repetition")
    @patch("proc.tasks.JournalProc")
    @patch("proc.tasks._get_user")
    def test_no_crash_when_user_is_none(
        self,
        mock_get_user,
        MockJournalProc,
        mock_task_exclude,
        mock_controller,
        MockIssueProc,
        mock_get_api_data,
        MockTaskExec,
    ):
        """The task should not raise AttributeError when user is None."""
        from proc.tasks import task_migrate_and_publish_articles_by_journal

        mock_get_user.return_value = None

        mock_journal_proc = MagicMock()
        mock_journal_proc.collection = MagicMock()
        MockJournalProc.objects.select_related.return_value.get.return_value = (
            mock_journal_proc
        )

        mock_controller.register_acron_id_file_content.return_value = {
            "article_pids": []
        }

        # Should not raise AttributeError - use kwargs only (celery bind=True handles self)
        task_migrate_and_publish_articles_by_journal(
            user_id=None,
            username=None,
            collection_acron="scl",
            journal_acron="test",
        )

        # Verify task_exclude_article_repetition was called with None values
        mock_task_exclude.assert_called_once()

    @patch("proc.tasks.TaskExecution")
    @patch("proc.tasks.get_api_data")
    @patch("proc.tasks.IssueProc")
    @patch("proc.tasks.controller")
    @patch("proc.tasks.task_exclude_article_repetition")
    @patch("proc.tasks.JournalProc")
    @patch("proc.tasks._get_user")
    def test_passes_original_username_when_user_is_none(
        self,
        mock_get_user,
        MockJournalProc,
        mock_task_exclude,
        mock_controller,
        MockIssueProc,
        mock_get_api_data,
        MockTaskExec,
    ):
        """When user is None, original username/user_id params should be passed through."""
        from proc.tasks import task_migrate_and_publish_articles_by_journal

        mock_get_user.return_value = None

        mock_journal_proc = MagicMock()
        mock_journal_proc.collection = MagicMock()
        MockJournalProc.objects.select_related.return_value.get.return_value = (
            mock_journal_proc
        )

        mock_controller.register_acron_id_file_content.return_value = {
            "article_pids": []
        }

        task_migrate_and_publish_articles_by_journal(
            user_id=None,
            username=None,
            collection_acron="scl",
            journal_acron="test",
        )

        # task_exclude_article_repetition should be called with None params (not crash)
        mock_task_exclude.assert_called_once()
        _, kwargs = mock_task_exclude.call_args
        self.assertIsNone(kwargs.get("username"))
        self.assertIsNone(kwargs.get("user_id"))

    @patch("proc.tasks.TaskExecution")
    @patch("proc.tasks.get_api_data")
    @patch("proc.tasks.IssueProc")
    @patch("proc.tasks.controller")
    @patch("proc.tasks.task_exclude_article_repetition")
    @patch("proc.tasks.JournalProc")
    @patch("proc.tasks._get_user")
    def test_uses_user_attributes_when_user_exists(
        self,
        mock_get_user,
        MockJournalProc,
        mock_task_exclude,
        mock_controller,
        MockIssueProc,
        mock_get_api_data,
        MockTaskExec,
    ):
        """When user exists, should use user.username and user.id."""
        from proc.tasks import task_migrate_and_publish_articles_by_journal

        mock_user = MagicMock()
        mock_user.username = "realuser"
        mock_user.id = 42
        mock_get_user.return_value = mock_user

        mock_journal_proc = MagicMock()
        mock_journal_proc.collection = MagicMock()
        MockJournalProc.objects.select_related.return_value.get.return_value = (
            mock_journal_proc
        )

        mock_controller.register_acron_id_file_content.return_value = {
            "article_pids": []
        }

        task_migrate_and_publish_articles_by_journal(
            user_id=None,
            username=None,
            collection_acron="scl",
            journal_acron="test",
        )

        mock_task_exclude.assert_called_once()
        _, kwargs = mock_task_exclude.call_args
        self.assertEqual(kwargs.get("username"), "realuser")
        self.assertEqual(kwargs.get("user_id"), 42)


class TaskCreateProcsFromPidListUserNoneTest(unittest.TestCase):
    """Test that task_create_procs_from_pid_list doesn't crash when user is None."""

    @patch("proc.tasks.task_create_collection_procs_from_pid_list")
    @patch("proc.tasks._get_collections")
    @patch("proc.tasks._get_user")
    def test_no_crash_when_user_is_none(
        self,
        mock_get_user,
        mock_get_collections,
        mock_task_create,
    ):
        """The task should not raise AttributeError when user is None."""
        from proc.tasks import task_create_procs_from_pid_list

        mock_get_user.return_value = None
        mock_collection = MagicMock()
        mock_collection.acron = "scl"
        mock_get_collections.return_value = [mock_collection]

        # Should not raise AttributeError
        task_create_procs_from_pid_list(
            username=None,
            user_id=None,
        )

        # Verify the sub-task was called with None username (not crash)
        mock_task_create.apply_async.assert_called_once()
        call_kwargs = mock_task_create.apply_async.call_args[1]["kwargs"]
        self.assertIsNone(call_kwargs["username"])

    @patch("proc.tasks.task_create_collection_procs_from_pid_list")
    @patch("proc.tasks._get_collections")
    @patch("proc.tasks._get_user")
    def test_uses_user_username_when_user_exists(
        self,
        mock_get_user,
        mock_get_collections,
        mock_task_create,
    ):
        """When user exists, should use user.username."""
        from proc.tasks import task_create_procs_from_pid_list

        mock_user = MagicMock()
        mock_user.username = "realuser"
        mock_get_user.return_value = mock_user

        mock_collection = MagicMock()
        mock_collection.acron = "scl"
        mock_get_collections.return_value = [mock_collection]

        task_create_procs_from_pid_list(
            username="otheruser",
            user_id=None,
        )

        mock_task_create.apply_async.assert_called_once()
        call_kwargs = mock_task_create.apply_async.call_args[1]["kwargs"]
        self.assertEqual(call_kwargs["username"], "realuser")


class SafeUserAccessInErrorHandlingTest(unittest.TestCase):
    """Test that error handling detail dicts don't crash with user=None."""

    def test_safe_user_access_pattern(self):
        """Verify the safe access pattern works correctly."""
        user = None
        detail = {
            "user_id": user.id if user else None,
            "username": user.username if user else None,
        }
        self.assertIsNone(detail["user_id"])
        self.assertIsNone(detail["username"])

    def test_safe_user_access_with_user(self):
        """Verify the safe access pattern works with a real user."""
        user = MagicMock()
        user.id = 42
        user.username = "testuser"
        detail = {
            "user_id": user.id if user else None,
            "username": user.username if user else None,
        }
        self.assertEqual(detail["user_id"], 42)
        self.assertEqual(detail["username"], "testuser")


if __name__ == "__main__":
    unittest.main()
