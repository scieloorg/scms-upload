import unittest
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils.translation import gettext_lazy as _

from collection.models import Collection, Language
from journal.models import Journal, OfficialJournal
from issue.models import Issue
from proc.models import JournalProc, IssueProc
from proc.exceptions import ProcBaseException
from proc.source_core_api import (
    BaseDataChecker,
    FetchIssueDataException,
    FetchJournalDataException,
    FetchMultipleJournalsError,
    IssueDataChecker,
    JournalDataChecker,
    UnableToGetJournalDataFromCoreError,
    fetch_and_create_issues,
    fetch_and_create_journal,
    fetch_issue_data_with_pagination,
    fetch_journal_data_with_pagination,
    process_issue_result,
    process_journal_result,
)

User = get_user_model()


class DummyDataChecker(BaseDataChecker):
    """Subclasse concreta para testar os métodos genéricos de BaseDataChecker."""

    model = MagicMock()
    key = "dummy"

    def get_local(self):
        pass

    def is_local_or_remote(self, obj):
        pass

    def fetch_from_core(self, **kwargs):
        pass


class TestCoreApiExceptions(unittest.TestCase):
    """Testes para garantir que as exceções personalizadas herdam da classe base."""

    def test_custom_exceptions_inherit_from_proc_base_exception(self):
        self.assertTrue(issubclass(FetchMultipleJournalsError, ProcBaseException))
        self.assertTrue(issubclass(UnableToGetJournalDataFromCoreError, ProcBaseException))
        self.assertTrue(issubclass(FetchJournalDataException, ProcBaseException))
        self.assertTrue(issubclass(FetchIssueDataException, ProcBaseException))


class TestBaseDataChecker(unittest.TestCase):
    """Testes dos métodos abstratos/genéricos da BaseDataChecker."""

    def setUp(self):
        self.user = MagicMock()
        self.checker = DummyDataChecker(user=self.user)

    def test_get_or_fetch_returns_local_obj_when_updated_and_not_force_update(self):
        obj = MagicMock()
        self.checker.get_local = MagicMock(return_value=obj)
        self.checker.is_local_or_remote = MagicMock(return_value="local")
        self.checker.fetch_from_core = MagicMock()

        result = self.checker.get_or_fetch(force_update=False)

        self.assertEqual(result, obj)
        self.checker.fetch_from_core.assert_not_called()

    def test_get_or_fetch_fetches_remote_when_force_update_is_true(self):
        obj = MagicMock()
        self.checker.get_local = MagicMock(return_value=obj)
        self.checker.is_local_or_remote = MagicMock(return_value="local")
        self.checker.fetch_from_core = MagicMock()

        result = self.checker.get_or_fetch(force_update=True)

        self.checker.fetch_from_core.assert_called_once()
        self.assertEqual(result, obj)

    def test_get_or_fetch_fetches_remote_when_local_is_outdated(self):
        obj = MagicMock()
        self.checker.get_local = MagicMock(side_effect=[obj, obj])
        self.checker.is_local_or_remote = MagicMock(return_value="remote")
        self.checker.fetch_from_core = MagicMock()

        result = self.checker.get_or_fetch(force_update=False)

        self.checker.fetch_from_core.assert_called_once()
        self.assertEqual(result, obj)

    def test_get_or_fetch_returns_none_if_model_does_not_exist_after_fetch(self):
        self.checker.model.DoesNotExist = Exception
        self.checker.get_local = MagicMock(side_effect=Exception("DoesNotExist"))
        self.checker.is_local_or_remote = MagicMock(return_value="remote")
        self.checker.fetch_from_core = MagicMock()

        result = self.checker.get_or_fetch(force_update=False)

        self.assertIsNone(result)

    def test_refresh_sets_error_flag_on_communication_failure(self):
        response = {}
        self.checker.fetch_from_core = MagicMock()
        self.checker.core_communication_error = True

        self.checker.refresh(response)

        self.assertTrue(response.get("core_communication_error"))
        self.assertNotIn("dummy", response)


class TestJournalDataChecker(TestCase):
    """Testes unitários para JournalDataChecker."""

    def setUp(self):
        self.user = MagicMock()
        self.user.username = "testuser"
        self.checker = JournalDataChecker(
            journal_title="Revista de Teste",
            issn_electronic="1234-5678",
            issn_print="8765-4321",
            user=self.user,
        )

    def test_is_local_or_remote_returns_false_if_journal_is_not_complete(self):
        journal = MagicMock()
        journal.core_synchronized = False

        self.assertEqual("remote", self.checker.is_local_or_remote(journal))

    @patch("proc.source_core_api.JournalProc.objects.filter")
    def test_is_local_or_remote_returns_false_if_journal_proc_does_not_exist(self, mock_proc_filter):
        journal = MagicMock()
        journal.core_synchronized = True
        journal.missing_fields = []
        mock_proc_filter.return_value.exists.return_value = False

        self.assertEqual("remote", self.checker.is_local_or_remote(journal))

    @patch("proc.source_core_api.JournalProc.objects.filter")
    def test_is_local_or_remote_returns_true_when_complete_and_proc_exists(self, mock_proc_filter):
        journal = MagicMock()
        journal.core_synchronized = True
        journal.missing_fields = []
        mock_proc_filter.return_value.exists.return_value = True

        self.assertEqual("local", self.checker.is_local_or_remote(journal))

    @patch.object(JournalDataChecker, "get_or_fetch")
    @patch("proc.source_core_api.JournalProc.objects.filter")
    def test_ensure_proc_exists_success(self, mock_proc_filter, mock_get_or_fetch):
        mock_journal = MagicMock()
        mock_get_or_fetch.return_value = mock_journal
        mock_proc_filter.return_value.exists.return_value = True

        result = self.checker.ensure_proc_exists(force_update=False)

        self.assertEqual(result, mock_journal)

    @patch.object(JournalDataChecker, "get_or_fetch")
    @patch("proc.source_core_api.JournalProc.objects.filter")
    def test_ensure_proc_exists_raises_does_not_exist(self, mock_proc_filter, mock_get_or_fetch):
        mock_journal = MagicMock()
        mock_get_or_fetch.return_value = mock_journal
        mock_proc_filter.return_value.exists.return_value = False

        with self.assertRaises(JournalProc.DoesNotExist):
            self.checker.ensure_proc_exists(force_update=False)

    @patch("proc.source_core_api.fetch_and_create_journal")
    def test_fetch_from_core_handles_exception_and_sets_flag(self, mock_fetch):
        mock_fetch.side_effect = FetchJournalDataException("Erro ao buscar dados")

        self.checker.fetch_from_core(force_update=True)

        self.assertTrue(self.checker.core_communication_error)


class TestFetchJournalDataWithPagination(TestCase):
    """Testes para a busca de periódicos com paginação."""

    @patch("proc.source_core_api.fetch_data")
    @patch("proc.source_core_api.settings")
    def test_fetch_journal_data_pagination_yields_all_results(self, mock_settings, mock_fetch_data):
        mock_settings.JOURNAL_API_URL = "http://core.scielo.org/api/journals/"

        mock_fetch_data.side_effect = [
            {
                "next": "http://core.scielo.org/api/journals/?page=2",
                "results": [{"id": 1, "title": "Journal 1"}],
            },
            {
                "next": None,
                "results": [{"id": 2, "title": "Journal 2"}],
            },
        ]

        results = list(fetch_journal_data_with_pagination(issn_electronic="1234-5678"))

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["title"], "Journal 1")
        self.assertEqual(results[1]["title"], "Journal 2")
        self.assertEqual(mock_fetch_data.call_count, 2)

    @patch("proc.source_core_api.fetch_data")
    @patch("proc.source_core_api.settings")
    def test_fetch_journal_data_raises_fetch_journal_data_exception_on_error(self, mock_settings, mock_fetch_data):
        mock_settings.JOURNAL_API_URL = "http://core.scielo.org/api/journals/"
        mock_fetch_data.side_effect = Exception("Timeout de rede")

        generator = fetch_journal_data_with_pagination(issn_electronic="1234-5678")

        with self.assertRaises(FetchJournalDataException):
            next(generator)


class TestProcessJournalResult(TestCase):
    """Testes para a função process_journal_result."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="editor", 
            email="editor@teste.org", 
            password="password"
        )
        
        self.collection = Collection.get_or_create(
            acron="scl",
            name="SciELO Brasil",
            user=self.user,
        )

        Language.objects.get_or_create(code2="pt", creator=self.user)
        
        self.result_data = {
            "title": "Revista Brasileira de Teste",
            "short_title": "Rev. Bras. Teste",
            "contact_address": "Rua Exemplo, 123",
            "contact_name": "Contato Teste",
            "journal_use_license": "CC-BY",
            "nlm_title": "Rev Bras Teste",
            "doi_prefix": "10.1590",
            "wos_areas": ["Science"],
            "url_logo": "http://example.com/logo.png",
            "submission_online_url": "http://example.com/sub",
            "official": {
                "title": "Revista Brasileira de Teste",
                "iso_short_title": "RBT",
                "issn_print": "1111-2222",
                "issn_electronic": "3333-4444",
                "issnl": "1111-2222",
                "foundation_year": 2000,
            },
            "next_journal_title": None,
            "previous_journal_title": None,
            "email": ["contato@teste.org"],
            "subject": [{"value": "Health Sciences"}],
            "publisher": [{"name": "Editora Exemplo"}],
            "owner": [],
            "sponsor": [],
            "mission": [{"language": "pt", "rich_text": "Missão do periódico"}],
            "scielo_journal": [
                {
                    "collection_acron": "scl",
                    "issn_scielo": "3333-4444",
                    "journal_acron": "rbt",
                    "status": "C",
                    "journal_history": [
                        {
                            "event_type": "C",
                            "year": "2020",
                            "month": "01",
                            "day": "01",
                            "interruption_reason": "",
                        }
                    ],
                }
            ],
        }

    def test_process_journal_result_raises_value_error_if_no_scielo_journal(self):
        self.result_data["scielo_journal"] = []

        with self.assertRaises(ValueError):
            process_journal_result(self.user, self.result_data)

    def test_process_journal_result_creates_journal_and_synchronizes(self):
        journal = process_journal_result(self.user, self.result_data)

        self.assertIsNotNone(journal)
        self.assertTrue(journal.core_synchronized)
        self.assertEqual(journal.title, "Revista Brasileira de Teste")
        self.assertEqual(journal.journal_acron, "rbt")
        self.assertTrue(JournalProc.objects.filter(journal=journal, acron="rbt").exists())


class TestIssueDataChecker(TestCase):
    """Testes unitários para IssueDataChecker."""

    def setUp(self):
        self.user = MagicMock()
        self.journal = MagicMock()
        self.checker = IssueDataChecker(
            journal=self.journal,
            publication_year=2024,
            volume="10",
            suppl=None,
            number="1",
            user=self.user,
        )

    @patch("proc.source_core_api.IssueProc.objects.filter")
    def test_is_local_or_remote_returns_true_when_proc_exists(self, mock_proc_filter):
        mock_proc_filter.return_value.exists.return_value = True
        issue = MagicMock()

        self.assertTrue(self.checker.is_local_or_remote(issue))

    @patch("proc.source_core_api.IssueProc.objects.filter")
    def test_is_local_or_remote_returns_false_when_proc_does_not_exist(self, mock_proc_filter):
        mock_proc_filter.return_value.exists.return_value = False
        issue = MagicMock()

        self.assertFalse(self.checker.is_local_or_remote(issue))

    @patch.object(IssueDataChecker, "get_or_fetch")
    @patch("proc.source_core_api.IssueProc.objects.filter")
    def test_ensure_proc_exists_success(self, mock_proc_filter, mock_get_or_fetch):
        mock_issue = MagicMock()
        mock_get_or_fetch.return_value = mock_issue
        mock_proc_filter.return_value.exists.return_value = True

        result = self.checker.ensure_proc_exists(force_update=False)

        self.assertEqual(result, mock_issue)

    @patch.object(IssueDataChecker, "get_or_fetch")
    @patch("proc.source_core_api.IssueProc.objects.filter")
    def test_ensure_proc_exists_raises_does_not_exist(self, mock_proc_filter, mock_get_or_fetch):
        mock_issue = MagicMock()
        mock_get_or_fetch.return_value = mock_issue
        mock_proc_filter.return_value.exists.return_value = False

        with self.assertRaises(IssueProc.DoesNotExist):
            self.checker.ensure_proc_exists(force_update=False)


class TestFetchAndProcessIssues(TestCase):
    """Testes para a busca e processamento de fascículos (Issues)."""

    def setUp(self):
        self.user = User.objects.create_user(username="issue_user")
        self.journal = MagicMock()
        self.journal.official_journal.issn_print = "1111-2222"
        self.journal.official_journal.issn_electronic = "3333-4444"

    @patch("proc.source_core_api.process_issue_result")
    @patch("proc.source_core_api.fetch_issue_data_with_pagination")
    @patch("proc.source_core_api.settings")
    def test_fetch_and_create_issues_calls_process_issue_result(
        self, mock_settings, mock_fetch_pagination, mock_process_issue
    ):
        mock_settings.ISSUE_API_URL = "http://core.scielo.org/api/issues/"
        mock_fetch_pagination.return_value = [
            {"volume": "10", "number": "1", "year": "2024"}
        ]

        fetch_and_create_issues(
            journal=self.journal,
            pub_year=2024,
            volume="10",
            suppl=None,
            number="1",
            user=self.user,
        )

        mock_process_issue.assert_called_once_with(
            self.user,
            self.journal,
            {"volume": "10", "number": "1", "year": "2024"},
        )

    @patch("proc.source_core_api.Issue.get_or_create")
    @patch("proc.source_core_api.JournalProc.objects.filter")
    def test_process_issue_result_creates_issue_and_issue_proc(
        self, mock_journal_proc_filter, mock_issue_get_or_create
    ):
        mock_issue = MagicMock()
        mock_issue_get_or_create.return_value = mock_issue
        
        mock_journal_proc = MagicMock()
        mock_journal_proc.collection = MagicMock()
        mock_journal_proc_filter.return_value = [mock_journal_proc]

        result_data = {
            "volume": "10",
            "number": "1",
            "supplement": None,
            "year": 2024,
            "order": 1,
            "issue_pid_suffix": "v10n1",
        }

        with patch("proc.source_core_api.IssueProc.objects.get") as mock_issue_proc_get:
            mock_issue_proc_get.side_effect = IssueProc.DoesNotExist
            with patch("proc.source_core_api.IssueProc.create_from_journal_proc_and_issue") as mock_create_issue_proc:
                process_issue_result(self.user, self.journal, result_data)

                mock_issue.save.assert_called_once()
                mock_create_issue_proc.assert_called_once_with(
                    self.user, mock_journal_proc, mock_issue
                )


if __name__ == "__main__":
    unittest.main()