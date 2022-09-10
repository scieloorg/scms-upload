from django.utils.translation import gettext_lazy as _

from .models import (
    Collection,
    JournalCollections,
    SciELOJournal,
    SciELOIssue,
    IssueInCollections,
)
from journal.controller import get_or_create_official_journal
from issue.controller import get_or_create_official_issue

from . import exceptions


def get_or_create_collection(collection_acron):
    try:
        collection, status = Collection.objects.get_or_create(
            acron=collection_acron
        )
    except Exception as e:
        raise exceptions.GetOrCreateCollectionError(
            _('Unable to get_or_create_collection {} {} {}').format(
                collection_acron, type(e), e
            )
        )
    return collection


def get_or_create_scielo_journal(collection, scielo_issn):
    try:
        scielo_journal, status = SciELOJournal.objects.get_or_create(
            collection=collection, scielo_issn=scielo_issn,
        )
    except Exception as e:
        raise exceptions.GetOrCreateScieloJournalError(
            _('Unable to get_or_create_scielo_journal {} {} {} {}').format(
                collection, scielo_issn, type(e), e
            )
        )
    return scielo_journal


def get_or_create_journal_collections(official_journal):
    try:
        scielo_journal, status = JournalCollections.objects.get_or_create(
            official_journal=official_journal,
        )
    except Exception as e:
        raise exceptions.GetOrCreateJournalCollectionsError(
            _('Unable to get_or_create_journal_collections {} {} {}').format(
                official_journal, type(e), e
            )
        )
    return scielo_journal


def get_or_create_scielo_journal_in_journal_collections(official_journal, scielo_journal):

    try:
        journal_collections = get_or_create_journal_collections(official_journal)

    except Exception as e:
        raise exceptions.GetOrCreateScieloJournalInJournalCollectionsError(
            _('Unable to get_or_create_scielo_journal_in_journal_collections {} {} {} {}').format(
                official_journal, scielo_journal, type(e), e
            )
        )
    journal_collections.scielo_journals.get_or_create(scielo_journal)
    return journal_collections

###########################################################################


def get_or_create_scielo_issue(scielo_journal, issue_pid, issue_folder):
    try:
        scielo_issue, status = SciELOIssue.objects.get_or_create(
            scielo_journal=scielo_journal,
            issue_pid=issue_pid,
            issue_folder=issue_folder,
        )
    except Exception as e:
        raise exceptions.GetOrCreateScieloIssueError(
            _('Unable to get_or_create_scielo_issue {} {} {} {}').format(
                scielo_journal, issue_pid, type(e), e
            )
        )
    return scielo_issue


def get_or_create_issue_in_collections(official_issue, scielo_issue):
    try:
        scielo_issue, status = IssueInCollections.objects.get_or_create(
            official_issue=official_issue,
        )
    except Exception as e:
        raise exceptions.GetOrCreateIssueInCollectionsError(
            _('Unable to get_or_create_issue_in_collections {} {} {}').format(
                official_issue, type(e), e
            )
        )
    return scielo_issue


def get_or_create_scielo_issue_in_issue_collections(official_issue, scielo_issue):

    try:
        issue_collections = get_or_create_issue_collections(official_issue)

    except Exception as e:
        raise exceptions.GetOrCreateScieloIssueInIssueCollectionsError(
            _('Unable to get_or_create_scielo_issue_in_issue_collections {} {} {} {}').format(
                official_issue, scielo_issue, type(e), e
            )
        )
    issue_collections.scielo_issues.get_or_create(scielo_issue)
    return issue_collections


class JournalManager:

    def __init__(self, collection_acron, scielo_issn, issn_l, e_issn, print_issn):
        self._collection_acron = collection_acron
        self._scielo_issn = scielo_issn
        self._issn_l = issn_l
        self._e_issn = e_issn
        self._print_issn = print_issn

    @property
    def collection(self):
        if not hasattr(self, '_collection'):
            self._collection = None
        if not self._collection:
            self._collection = get_or_create_collection(self._collection_acron)
        return self._collection

    @property
    def scielo_journal(self):
        if not hasattr(self, '_scielo_journal'):
            self._scielo_journal = None
        if not self._scielo_journal:
            self._scielo_journal = get_or_create_scielo_journal(
                self.collection,
                self._scielo_issn,
            )
        return self._scielo_journal

    @property
    def official_journal(self):
        if not hasattr(self, '_official_journal'):
            self._official_journal = None
        if not self._official_journal:
            self._official_journal = get_or_create_official_journal(
                self._issn_l, self._e_issn, self._print_issn
            )
        return self._official_journal

    @property
    def scielo_journal_in_journal_collections(self):
        if not hasattr(self, '_scielo_journal_in_journal_collections'):
            self._scielo_journal_in_journal_collections = None

        if not self._scielo_journal_in_journal_collections:
            self._scielo_journal_in_journal_collections = (
                get_or_create_scielo_journal_in_journal_collections(
                    self.official_journal,
                    self.scielo_journal,
                )
            )
        return self._scielo_journal_in_journal_collections


class IssueManager:

    def __init__(self, official_journal, scielo_journal,
                 year, volume, number, supplement,
                 issue_pid,
                 ):
        self._official_journal = official_journal
        self._scielo_journal = scielo_journal
        self._issue_pid = issue_pid
        self._year = year
        self._volume = volume
        self._number = number
        self._supplement = supplement
        self._issue_pid = issue_pid

    @property
    def official_journal(self):
        return self._official_journal

    @property
    def issue_folder(self):
        keys = ("v", "n", "s")
        values = (self._volume, self._number, self._supplement)
        if self._number == "ahead":
            return self._year + "nahead"
        return "".join([
            f"{k}{v}"
            for k, v in zip(keys, values)
            if v])

    @property
    def scielo_journal(self):
        return self._scielo_journal

    @property
    def scielo_issue(self):
        if not hasattr(self, '_scielo_issue'):
            self._scielo_issue = None
        if not self._scielo_issue:
            self._scielo_issue = get_or_create_scielo_issue(
                self.scielo_journal,
                self._issue_pid,
                self.issue_folder,
            )
        return self._scielo_issue

    @property
    def official_issue(self):
        if not hasattr(self, '_official_issue'):
            self._official_issue = None
        if not self._official_issue:
            self._official_issue = get_or_create_official_issue(
                self.official_journal,
                self._year,
                self._volume,
                self._number,
                self._supplement,
            )
        return self._official_issue

    @property
    def scielo_issue_in_issue_collections(self):
        if not hasattr(self, '_scielo_issue_in_issue_collections'):
            self._scielo_issue_in_issue_collections = None

        if not self._scielo_issue_in_issue_collections:
            self._scielo_issue_in_issue_collections = (
                get_or_create_scielo_issue_in_issue_collections(
                    self.official_issue,
                    self.scielo_issue,
                )
            )
        return self._scielo_issue_in_issue_collections
