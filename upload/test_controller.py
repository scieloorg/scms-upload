import sys
import unittest
from unittest.mock import MagicMock, Mock, patch, call

# Mock modules that cannot be imported in test environment
# (upload app is not in INSTALLED_APPS, and zip_pkg module doesn't exist)
_mock_upload_models = MagicMock()
_mock_upload_models.choices = MagicMock()
_mock_upload_models.choices.VAL_CAT_PACKAGE_FILE = "package-file"
_mock_upload_models.choices.PS_ENQUEUED_FOR_VALIDATION = "enqueued-for-validation"
_mock_upload_models.choices.PS_PENDING_CORRECTION = "pending-correction"
_mock_upload_models.choices.PS_UNEXPECTED = "unexpected"
_mock_upload_models.choices.VALIDATION_RESULT_BLOCKING = "BLOCKING"
_mock_upload_models.choices.PS_WIP = ("submitted",)
_mock_upload_models.choices.PC_NEW_DOCUMENT = "new-document"
sys.modules.setdefault("upload.utils.zip_pkg", MagicMock())
sys.modules.setdefault("upload.models", _mock_upload_models)
sys.modules.setdefault("pid_provider.requester", MagicMock())

from upload.controller import (
    PackageDataError,
    JournalDataChecker,
    IssueDataChecker,
    _check_xml_and_registered_data_compability,
)


class JournalDoesNotExist(Exception):
    """Fake DoesNotExist exception for Journal model testing."""

    pass


class IssueDoesNotExist(Exception):
    """Fake DoesNotExist exception for Issue model testing."""

    pass


class JournalDataCheckerTestCase(unittest.TestCase):
    """Test cases for JournalDataChecker local-first lookup with core fallback."""

    @patch("upload.controller.ISSN")
    @patch("upload.controller.Title")
    @patch("upload.controller.Journal")
    def test_check_returns_journal_from_local_data(
        self, mock_journal_cls, mock_title, mock_issn
    ):
        """Test that local data is used first without querying core API."""
        mock_title_instance = Mock()
        mock_title_instance.journal_title = "Test Journal"
        mock_title.return_value = mock_title_instance

        mock_issn_instance = Mock()
        mock_issn_instance.epub = "1234-5678"
        mock_issn_instance.ppub = "8765-4321"
        mock_issn.return_value = mock_issn_instance

        mock_journal = Mock()
        mock_journal_cls.get_registered.return_value = mock_journal

        response = {}
        xmltree = Mock()
        user = Mock()

        checker = JournalDataChecker(xmltree, user)
        checker.check(response)

        self.assertEqual(response["journal"], mock_journal)
        mock_journal_cls.get_registered.assert_called_once_with(
            "Test Journal", "1234-5678", "8765-4321"
        )

    @patch("upload.controller.fetch_and_create_journal")
    @patch("upload.controller.ISSN")
    @patch("upload.controller.Title")
    @patch("upload.controller.Journal")
    def test_check_fetches_from_core_when_local_not_found(
        self, mock_journal_cls, mock_title, mock_issn, mock_fetch
    ):
        """Test that core API is queried when local data doesn't exist."""
        mock_title_instance = Mock()
        mock_title_instance.journal_title = "Test Journal"
        mock_title.return_value = mock_title_instance

        mock_issn_instance = Mock()
        mock_issn_instance.epub = "1234-5678"
        mock_issn_instance.ppub = "8765-4321"
        mock_issn.return_value = mock_issn_instance

        mock_journal = Mock()
        mock_journal_cls.DoesNotExist = JournalDoesNotExist
        # First call: DoesNotExist, second call after core fetch: returns journal
        mock_journal_cls.get_registered.side_effect = [
            JournalDoesNotExist(),
            mock_journal,
        ]

        response = {}
        xmltree = Mock()
        user = Mock()

        checker = JournalDataChecker(xmltree, user)
        checker.check(response)

        self.assertEqual(response["journal"], mock_journal)
        mock_fetch.assert_called_once_with(
            user,
            issn_electronic="1234-5678",
            issn_print="8765-4321",
            force_update=True,
        )

    @patch("upload.controller.fetch_and_create_journal")
    @patch("upload.controller.ISSN")
    @patch("upload.controller.Title")
    @patch("upload.controller.Journal")
    def test_check_raises_error_with_core_failure_message_when_core_unreachable(
        self, mock_journal_cls, mock_title, mock_issn, mock_fetch
    ):
        """Test that core communication failure is reported when core is unreachable."""
        from upload.controller import FetchJournalDataException

        mock_title_instance = Mock()
        mock_title_instance.journal_title = "Test Journal"
        mock_title.return_value = mock_title_instance

        mock_issn_instance = Mock()
        mock_issn_instance.epub = "1234-5678"
        mock_issn_instance.ppub = "8765-4321"
        mock_issn.return_value = mock_issn_instance

        mock_journal_cls.DoesNotExist = JournalDoesNotExist
        mock_journal_cls.get_registered.side_effect = JournalDoesNotExist()
        mock_journal_cls.get_similar_items.return_value = []
        mock_fetch.side_effect = FetchJournalDataException("Connection refused")

        response = {}
        xmltree = Mock()
        user = Mock()

        checker = JournalDataChecker(xmltree, user)
        with self.assertRaises(PackageDataError) as context:
            checker.check(response)

        self.assertIn("CORE COMMUNICATION FAILURE", str(context.exception))
        self.assertTrue(response.get("core_communication_error"))

    @patch("upload.controller.fetch_and_create_journal")
    @patch("upload.controller.ISSN")
    @patch("upload.controller.Title")
    @patch("upload.controller.Journal")
    def test_check_raises_error_without_core_failure_when_journal_not_registered(
        self, mock_journal_cls, mock_title, mock_issn, mock_fetch
    ):
        """Test that a normal error is raised when journal is not registered (core works fine)."""
        mock_title_instance = Mock()
        mock_title_instance.journal_title = "Test Journal"
        mock_title.return_value = mock_title_instance

        mock_issn_instance = Mock()
        mock_issn_instance.epub = "1234-5678"
        mock_issn_instance.ppub = "8765-4321"
        mock_issn.return_value = mock_issn_instance

        mock_journal_cls.DoesNotExist = JournalDoesNotExist
        mock_journal_cls.get_registered.side_effect = JournalDoesNotExist()
        mock_journal_cls.get_similar_items.return_value = []

        response = {}
        xmltree = Mock()
        user = Mock()

        checker = JournalDataChecker(xmltree, user)
        with self.assertRaises(PackageDataError) as context:
            checker.check(response)

        self.assertNotIn("CORE COMMUNICATION FAILURE", str(context.exception))
        self.assertIn("registered journal", str(context.exception))
        self.assertFalse(response.get("core_communication_error"))

    @patch("upload.controller.ISSN")
    @patch("upload.controller.Title")
    @patch("upload.controller.Journal")
    def test_check_does_not_call_core_when_local_found(
        self, mock_journal_cls, mock_title, mock_issn
    ):
        """Test that core API is NOT called when local data exists."""
        mock_title_instance = Mock()
        mock_title_instance.journal_title = "Test Journal"
        mock_title.return_value = mock_title_instance

        mock_issn_instance = Mock()
        mock_issn_instance.epub = "1234-5678"
        mock_issn_instance.ppub = "8765-4321"
        mock_issn.return_value = mock_issn_instance

        mock_journal = Mock()
        mock_journal_cls.get_registered.return_value = mock_journal

        response = {}
        xmltree = Mock()
        user = Mock()

        with patch("upload.controller.fetch_and_create_journal") as mock_fetch:
            checker = JournalDataChecker(xmltree, user)
            checker.check(response)
            mock_fetch.assert_not_called()

    @patch("upload.controller.Journal")
    @patch("upload.controller.fetch_and_create_journal")
    @patch("upload.controller.ISSN")
    @patch("upload.controller.Title")
    def test_refresh_updates_response_on_success(
        self, mock_title, mock_issn, mock_fetch, mock_journal_cls
    ):
        """Test that successful core fetch updates the journal in response."""
        mock_title_instance = Mock()
        mock_title_instance.journal_title = "Test Journal"
        mock_title.return_value = mock_title_instance

        mock_issn_instance = Mock()
        mock_issn_instance.epub = "1234-5678"
        mock_issn_instance.ppub = "8765-4321"
        mock_issn.return_value = mock_issn_instance

        mock_journal = Mock()
        mock_journal_cls.get_registered.return_value = mock_journal

        response = {"journal": None}
        xmltree = Mock()
        user = Mock()

        checker = JournalDataChecker(xmltree, user)
        checker.refresh(response)

        self.assertEqual(response["journal"], mock_journal)
        self.assertFalse(response.get("core_communication_error"))

    @patch("upload.controller.fetch_and_create_journal")
    @patch("upload.controller.ISSN")
    @patch("upload.controller.Title")
    def test_refresh_sets_error_flag_on_core_failure(
        self, mock_title, mock_issn, mock_fetch
    ):
        """Test that core API failure sets the core_communication_error flag."""
        from upload.controller import FetchJournalDataException

        mock_title_instance = Mock()
        mock_title_instance.journal_title = "Test Journal"
        mock_title.return_value = mock_title_instance

        mock_issn_instance = Mock()
        mock_issn_instance.epub = "1234-5678"
        mock_issn_instance.ppub = "8765-4321"
        mock_issn.return_value = mock_issn_instance

        mock_fetch.side_effect = FetchJournalDataException("Timeout")

        response = {"journal": None}
        xmltree = Mock()
        user = Mock()

        checker = JournalDataChecker(xmltree, user)
        checker.refresh(response)

        self.assertTrue(response.get("core_communication_error"))

    @patch("upload.controller.ISSN")
    @patch("upload.controller.Title")
    @patch("upload.controller.Journal")
    def test_get_or_fetch_returns_local_journal(
        self, mock_journal_cls, mock_title, mock_issn
    ):
        """Test get_or_fetch returns journal from local data."""
        mock_title_instance = Mock()
        mock_title_instance.journal_title = "Test Journal"
        mock_title.return_value = mock_title_instance

        mock_issn_instance = Mock()
        mock_issn_instance.epub = "1234-5678"
        mock_issn_instance.ppub = "8765-4321"
        mock_issn.return_value = mock_issn_instance

        mock_journal = Mock()
        mock_journal_cls.get_registered.return_value = mock_journal

        xmltree = Mock()
        user = Mock()

        checker = JournalDataChecker(xmltree, user)
        result = checker.get_or_fetch()

        self.assertEqual(result, mock_journal)


class IssueDataCheckerTestCase(unittest.TestCase):
    """Test cases for IssueDataChecker local-first lookup with core fallback."""

    @patch("upload.controller.ArticleMetaIssue")
    @patch("upload.controller.ArticleDates")
    @patch("upload.controller.Issue")
    def test_check_returns_issue_from_local_data(
        self, mock_issue_cls, mock_dates, mock_meta_issue
    ):
        """Test that local data is used first without querying core API."""
        mock_dates_instance = Mock()
        mock_dates_instance.collection_date = {"year": "2024"}
        mock_dates.return_value = mock_dates_instance

        mock_meta = Mock()
        mock_meta.volume = "10"
        mock_meta.suppl = None
        mock_meta.number = "1"
        mock_meta_issue.return_value = mock_meta

        mock_issue = Mock()
        mock_issue_cls.get.return_value = mock_issue

        mock_journal = Mock()
        response = {"journal": mock_journal}
        xmltree = Mock()
        user = Mock()

        checker = IssueDataChecker(xmltree, user, mock_journal)
        checker.check(response)

        self.assertEqual(response["issue"], mock_issue)
        mock_issue_cls.get.assert_called_once_with(
            journal=mock_journal,
            volume="10",
            supplement=None,
            number="1",
        )

    @patch("upload.controller.fetch_and_create_issues")
    @patch("upload.controller.ArticleMetaIssue")
    @patch("upload.controller.ArticleDates")
    @patch("upload.controller.Issue")
    def test_check_fetches_from_core_when_local_not_found(
        self, mock_issue_cls, mock_dates, mock_meta_issue, mock_fetch
    ):
        """Test that core API is queried when local data doesn't exist."""
        mock_dates_instance = Mock()
        mock_dates_instance.collection_date = {"year": "2024"}
        mock_dates.return_value = mock_dates_instance

        mock_meta = Mock()
        mock_meta.volume = "10"
        mock_meta.suppl = None
        mock_meta.number = "1"
        mock_meta_issue.return_value = mock_meta

        mock_issue = Mock()
        mock_issue_cls.DoesNotExist = IssueDoesNotExist
        # First call: DoesNotExist, second call after core fetch: returns issue
        mock_issue_cls.get.side_effect = [
            IssueDoesNotExist(),
            mock_issue,
        ]

        mock_journal = Mock()
        response = {"journal": mock_journal}
        xmltree = Mock()
        user = Mock()

        checker = IssueDataChecker(xmltree, user, mock_journal)
        checker.check(response)

        self.assertEqual(response["issue"], mock_issue)
        mock_fetch.assert_called_once_with(
            mock_journal, "2024", "10", None, "1", user
        )

    @patch("upload.controller.fetch_and_create_issues")
    @patch("upload.controller.ArticleMetaIssue")
    @patch("upload.controller.ArticleDates")
    @patch("upload.controller.Issue")
    def test_check_raises_error_with_core_failure_message_when_core_unreachable(
        self, mock_issue_cls, mock_dates, mock_meta_issue, mock_fetch
    ):
        """Test that core communication failure is reported when core is unreachable."""
        from upload.controller import FetchIssueDataException

        mock_dates_instance = Mock()
        mock_dates_instance.collection_date = {"year": "2024"}
        mock_dates.return_value = mock_dates_instance

        mock_meta = Mock()
        mock_meta.volume = "10"
        mock_meta.suppl = None
        mock_meta.number = "1"
        mock_meta_issue.return_value = mock_meta

        mock_issue_cls.DoesNotExist = IssueDoesNotExist
        mock_issue_cls.get.side_effect = IssueDoesNotExist()
        mock_fetch.side_effect = FetchIssueDataException("Connection refused")

        mock_journal = Mock()
        mock_qs = MagicMock()
        mock_qs.count.return_value = 0
        mock_qs.order_by.return_value = []
        mock_issue_cls.objects.filter.return_value = mock_qs

        response = {"journal": mock_journal}
        xmltree = Mock()
        user = Mock()

        checker = IssueDataChecker(xmltree, user, mock_journal)
        with self.assertRaises(PackageDataError) as context:
            checker.check(response)

        self.assertIn("CORE COMMUNICATION FAILURE", str(context.exception))
        self.assertTrue(response.get("core_communication_error"))

    @patch("upload.controller.ArticleMetaIssue")
    @patch("upload.controller.ArticleDates")
    @patch("upload.controller.Issue")
    def test_check_does_not_call_core_when_local_found(
        self, mock_issue_cls, mock_dates, mock_meta_issue
    ):
        """Test that core API is NOT called when local data exists."""
        mock_dates_instance = Mock()
        mock_dates_instance.collection_date = {"year": "2024"}
        mock_dates.return_value = mock_dates_instance

        mock_meta = Mock()
        mock_meta.volume = "10"
        mock_meta.suppl = None
        mock_meta.number = "1"
        mock_meta_issue.return_value = mock_meta

        mock_issue = Mock()
        mock_issue_cls.get.return_value = mock_issue

        mock_journal = Mock()
        response = {"journal": mock_journal}
        xmltree = Mock()
        user = Mock()

        with patch("upload.controller.fetch_and_create_issues") as mock_fetch:
            checker = IssueDataChecker(xmltree, user, mock_journal)
            checker.check(response)
            mock_fetch.assert_not_called()

    @patch("upload.controller.Issue")
    @patch("upload.controller.fetch_and_create_issues")
    @patch("upload.controller.ArticleMetaIssue")
    @patch("upload.controller.ArticleDates")
    def test_refresh_updates_response_on_success(
        self, mock_dates, mock_meta_issue, mock_fetch, mock_issue_cls
    ):
        """Test that successful core fetch updates the issue in response."""
        mock_dates_instance = Mock()
        mock_dates_instance.collection_date = {"year": "2024"}
        mock_dates.return_value = mock_dates_instance

        mock_meta = Mock()
        mock_meta.volume = "10"
        mock_meta.suppl = None
        mock_meta.number = "1"
        mock_meta_issue.return_value = mock_meta

        mock_issue = Mock()
        mock_issue_cls.get.return_value = mock_issue

        mock_journal = Mock()
        response = {"journal": mock_journal, "issue": None}
        xmltree = Mock()
        user = Mock()

        checker = IssueDataChecker(xmltree, user, mock_journal)
        checker.refresh(response)

        self.assertEqual(response["issue"], mock_issue)
        self.assertFalse(response.get("core_communication_error"))

    @patch("upload.controller.fetch_and_create_issues")
    @patch("upload.controller.ArticleMetaIssue")
    @patch("upload.controller.ArticleDates")
    def test_refresh_sets_error_flag_on_core_failure(
        self, mock_dates, mock_meta_issue, mock_fetch
    ):
        """Test that core API failure sets the core_communication_error flag."""
        from upload.controller import FetchIssueDataException

        mock_dates_instance = Mock()
        mock_dates_instance.collection_date = {"year": "2024"}
        mock_dates.return_value = mock_dates_instance

        mock_meta = Mock()
        mock_meta.volume = "10"
        mock_meta.suppl = None
        mock_meta.number = "1"
        mock_meta_issue.return_value = mock_meta

        mock_fetch.side_effect = FetchIssueDataException("Timeout")

        mock_journal = Mock()
        response = {"journal": mock_journal, "issue": None}
        xmltree = Mock()
        user = Mock()

        checker = IssueDataChecker(xmltree, user, mock_journal)
        checker.refresh(response)

        self.assertTrue(response.get("core_communication_error"))


class CheckXmlAndRegisteredDataCompabilityTestCase(unittest.TestCase):
    """Test cases for _check_xml_and_registered_data_compability()."""

    def test_no_article_does_nothing(self):
        """Test that function returns without error when there is no article."""
        response = {"article": None, "journal": Mock(), "issue": Mock()}
        journal_checker = Mock()
        issue_checker = Mock()

        _check_xml_and_registered_data_compability(
            response, journal_checker, issue_checker
        )

    def test_matching_journal_and_issue_passes(self):
        """Test that function passes when journal and issue match."""
        mock_journal = Mock()
        mock_issue = Mock()
        mock_article = Mock()
        mock_article.journal = mock_journal
        mock_article.issue = mock_issue

        response = {
            "article": mock_article,
            "journal": mock_journal,
            "issue": mock_issue,
        }
        journal_checker = Mock()
        issue_checker = Mock()

        _check_xml_and_registered_data_compability(
            response, journal_checker, issue_checker
        )

    def test_journal_divergence_triggers_core_refresh(self):
        """Test that journal divergence triggers a refresh from core."""
        mock_journal_xml = Mock()
        mock_journal_article = Mock()
        mock_issue = Mock()
        mock_article = Mock()
        mock_article.journal = mock_journal_article
        mock_article.issue = mock_issue

        response = {
            "article": mock_article,
            "journal": mock_journal_xml,
            "issue": mock_issue,
        }

        journal_checker = Mock()
        issue_checker = Mock()

        with self.assertRaises(PackageDataError):
            _check_xml_and_registered_data_compability(
                response, journal_checker, issue_checker
            )

        journal_checker.refresh.assert_called_once()

    def test_journal_divergence_resolved_after_refresh(self):
        """Test that no error is raised when divergence is resolved after refresh."""
        mock_journal = Mock()
        mock_issue = Mock()
        mock_article = Mock()
        mock_article.journal = mock_journal
        mock_article.issue = mock_issue

        # Initially journal differs
        mock_journal_xml = Mock()
        response = {
            "article": mock_article,
            "journal": mock_journal_xml,
            "issue": mock_issue,
        }

        journal_checker = Mock()
        issue_checker = Mock()

        # After refresh, journal matches
        def refresh_side_effect(response):
            response["journal"] = mock_journal

        journal_checker.refresh.side_effect = refresh_side_effect

        _check_xml_and_registered_data_compability(
            response, journal_checker, issue_checker
        )

    def test_journal_divergence_with_core_failure_includes_core_error_message(self):
        """Test that core communication failure is mentioned when divergence persists and core failed."""
        mock_journal_xml = Mock()
        mock_journal_article = Mock()
        mock_issue = Mock()
        mock_article = Mock()
        mock_article.journal = mock_journal_article
        mock_article.issue = mock_issue

        response = {
            "article": mock_article,
            "journal": mock_journal_xml,
            "issue": mock_issue,
        }

        journal_checker = Mock()
        issue_checker = Mock()

        def refresh_side_effect(response):
            response["core_communication_error"] = True

        journal_checker.refresh.side_effect = refresh_side_effect

        with self.assertRaises(PackageDataError) as context:
            _check_xml_and_registered_data_compability(
                response, journal_checker, issue_checker
            )

        self.assertIn("CORE COMMUNICATION FAILURE", str(context.exception))

    def test_issue_divergence_triggers_core_refresh(self):
        """Test that issue divergence triggers a refresh from core."""
        mock_journal = Mock()
        mock_issue_xml = Mock()
        mock_issue_article = Mock()
        mock_article = Mock()
        mock_article.journal = mock_journal
        mock_article.issue = mock_issue_article

        response = {
            "article": mock_article,
            "journal": mock_journal,
            "issue": mock_issue_xml,
        }

        journal_checker = Mock()
        issue_checker = Mock()

        with self.assertRaises(PackageDataError):
            _check_xml_and_registered_data_compability(
                response, journal_checker, issue_checker
            )

        issue_checker.refresh.assert_called_once()
