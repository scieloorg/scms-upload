import unittest
from types import SimpleNamespace
from unittest.mock import Mock, PropertyMock, patch

import pytest
from django.utils.translation import gettext, override
from lxml import etree

from issue.models import Issue
from journal.models import Journal, OfficialJournal
from proc.models import IssueProc, JournalProc
from proc.source_core_api import FetchIssueDataException, FetchJournalDataException
from upload.controller import (
    PackageDataError,
    UploadIssueDataChecker,
    UploadJournalDataChecker,
    _check_xml_and_registered_data_compatibility,
)


@pytest.fixture(params=["journal", "issue"])
def checker_case(request, db, django_user_model):
    user = django_user_model.objects.create_user(username="depositor")
    official = OfficialJournal.objects.create(
        creator=user,
        title="Test Journal",
        issn_electronic="1234-5678",
        issn_print="8765-4321",
    )
    journal = Journal.objects.create(creator=user, official_journal=official)
    journal_proc = JournalProc.objects.create(creator=user, journal=journal)
    if request.param == "journal":
        record = journal
        proc = journal_proc
        checker = UploadJournalDataChecker(
            "Test Journal", "1234-5678", "8765-4321", user
        )
        fetch_path = "proc.source_core_api.fetch_and_create_journal"
        error = FetchJournalDataException
        fetch_args = (user,)
        fetch_kwargs = {
            "issn_electronic": "1234-5678",
            "issn_print": "8765-4321",
            "force_update": True,
        }
    else:
        record = Issue.objects.create(
            creator=user,
            journal=journal,
            publication_year="2024",
            volume="10",
            number="1",
        )
        proc = IssueProc.objects.create(
            creator=user, journal_proc=journal_proc, issue=record
        )
        checker = UploadIssueDataChecker(journal, "2024", "10", None, "1", user)
        fetch_path = "proc.source_core_api.fetch_and_create_issues"
        error = FetchIssueDataException
        fetch_args = (journal, "2024", "10", None, "1", user)
        fetch_kwargs = {}

    # Catalog completeness is covered by proc; keep actual lookup and Proc records here.
    with patch.object(
        Journal, "is_complete", new_callable=PropertyMock, return_value=True
    ):
        yield SimpleNamespace(
            key=request.param,
            record=record,
            proc=proc,
            checker=checker,
            fetch_path=fetch_path,
            fetch_error=error,
            fetch_args=fetch_args,
            fetch_kwargs=fetch_kwargs,
        )


def test_local_registration_updates_response_without_calling_core(checker_case):
    case = checker_case
    response = {}

    with patch(case.fetch_path) as fetch:
        case.checker.check(response)

    assert response[case.key] == case.record
    fetch.assert_not_called()


def test_missing_registration_is_received_from_core(checker_case):
    case = checker_case
    type(case.record).objects.filter(pk=case.record.pk).delete()

    def register(*args, **kwargs):
        case.record.save()

    response = {}

    with patch(case.fetch_path, side_effect=register) as fetch:
        case.checker.check(response)

    assert response[case.key] == case.record
    fetch.assert_called_once_with(*case.fetch_args, **case.fetch_kwargs)


def test_registration_without_proc_is_refreshed_before_acceptance(checker_case):
    case = checker_case
    case.proc.delete()
    response = {}

    with patch(case.fetch_path) as fetch:
        case.checker.check(response)

    assert response[case.key] == case.record
    fetch.assert_called_once_with(*case.fetch_args, **case.fetch_kwargs)


@pytest.mark.parametrize("core_unreachable", [False, True])
def test_missing_registration_distinguishes_core_failure(
    checker_case, core_unreachable
):
    case = checker_case
    type(case.record).objects.filter(pk=case.record.pk).delete()
    response = {}
    failure = case.fetch_error("Connection refused") if core_unreachable else None

    with override("en"), patch(case.fetch_path, side_effect=failure):
        with pytest.raises(PackageDataError) as error:
            case.checker.check(response)

    assert response[case.key] is None
    assert bool(response.get("core_communication_error")) is core_unreachable
    assert ("CORE COMMUNICATION FAILURE" in str(error.value)) is core_unreachable
    if not core_unreachable:
        assert f"registered {case.key}" in str(error.value)


def test_refresh_recovers_after_core_communication_failure(checker_case):
    case = checker_case
    type(case.record).objects.filter(pk=case.record.pk).delete()
    failed = {}

    with patch(case.fetch_path, side_effect=case.fetch_error("Timeout")):
        case.checker.refresh(failed)

    assert failed["core_communication_error"] is True

    def register(*args, **kwargs):
        case.record.save()

    recovered = {}

    with patch(case.fetch_path, side_effect=register):
        case.checker.refresh(recovered)

    assert recovered[case.key] == case.record
    assert not recovered.get("core_communication_error")
    assert case.checker.core_communication_error is False


def test_packtools_xml_metadata_initializes_upload_checkers():
    tree = etree.fromstring(b"""
        <article><front><journal-meta>
          <journal-title-group><journal-title>Test Journal</journal-title></journal-title-group>
          <issn pub-type="epub">1234-5678</issn><issn pub-type="ppub">8765-4321</issn>
        </journal-meta><article-meta>
          <pub-date publication-format="electronic" date-type="pub"><year>2024</year></pub-date>
          <volume>10</volume><issue>1</issue>
        </article-meta></front></article>
    """)
    user = object()
    journal = UploadJournalDataChecker.from_xmltree(tree, user)
    issue = UploadIssueDataChecker.from_xmltree(tree, None, user)

    assert (journal.journal_title, journal.issn_electronic, journal.issn_print) == (
        "Test Journal",
        "1234-5678",
        "8765-4321",
    )
    assert (issue.publication_year, issue.volume, issue.suppl, issue.number) == (
        "2024",
        "10",
        None,
        "1",
    )


class CheckXmlAndRegisteredDataCompatibilityTestCase(unittest.TestCase):
    """Test cases for _check_xml_and_registered_data_compatibility()."""

    def test_no_article_does_nothing(self):
        """Test that function returns without error when there is no article."""
        response = {"article": None, "journal": Mock(), "issue": Mock()}
        journal_checker = Mock()
        issue_checker = Mock()

        _check_xml_and_registered_data_compatibility(
            response, journal_checker, issue_checker
        )

        journal_checker.refresh.assert_not_called()
        issue_checker.refresh.assert_not_called()

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

        _check_xml_and_registered_data_compatibility(
            response, journal_checker, issue_checker
        )

        journal_checker.refresh.assert_not_called()
        issue_checker.refresh.assert_not_called()

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
            _check_xml_and_registered_data_compatibility(
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

        _check_xml_and_registered_data_compatibility(
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
            _check_xml_and_registered_data_compatibility(
                response, journal_checker, issue_checker
            )

        difference = gettext("{} (registered, {}) differs from {} (XML, {})").format(
            mock_article.journal,
            mock_article.journal.id,
            mock_journal_xml,
            mock_journal_xml.id,
        )

        self.assertEqual(
            str(context.exception),
            gettext(
                "CORE COMMUNICATION FAILURE: {}. Could not refresh data from core API"
            ).format(difference),
        )

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
            _check_xml_and_registered_data_compatibility(
                response, journal_checker, issue_checker
            )

        issue_checker.refresh.assert_called_once()
