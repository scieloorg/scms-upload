import logging

from django.utils.translation import gettext_lazy as _

from .models import (
    Collection,
    JournalCollections,
    SciELOJournal,
    SciELOIssue,
    IssueInCollections,
    ClassicWebsiteConfiguration,
    FilesStorageConfiguration,
    NewWebSiteConfiguration,
)
from journal.controller import get_or_create_official_journal
from issue.controller import get_or_create_official_issue
from article.controller import get_or_create_official_article

from . import exceptions


def get_classic_website_configuration(collection_acron):
    try:
        configuration = ClassicWebsiteConfiguration.objects.get(
            collection__acron=collection_acron)
    except Exception as e:
        raise exceptions.GetClassicWebsiteConfigurationError(
            _('Unable to get_classic_website_configuration {} {} {}').format(
                collection_acron, type(e), e
            )
        )
    return configuration


def get_or_create_collection(collection_acron, user_id):
    try:
        collection, status = Collection.objects.get_or_create(
            acron=collection_acron, creator_id=user_id,
        )
    except Exception as e:
        raise exceptions.GetOrCreateCollectionError(
            _('Unable to get_or_create_collection {} {} {}').format(
                collection_acron, type(e), e
            )
        )
    return collection


def get_scielo_journal_by_title(journal_title):
    try:
        scielo_journal = SciELOJournal.objects.get(
            title=journal_title,
        )
    except Exception as e:
        raise exceptions.GetSciELOJournalError(
            _('Unable to get_scielo_journal_by_title {} {} {}').format(
                journal_title, type(e), e
            )
        )
    return scielo_journal


def get_scielo_journal(collection_acron, scielo_issn):
    try:
        scielo_journal = SciELOJournal.objects.get(
            collection__acron=collection_acron,
            scielo_issn=scielo_issn,
        )
    except Exception as e:
        raise exceptions.GetSciELOJournalError(
            _('Unable to get_scielo_journal {} {} {} {}').format(
                collection_acron, scielo_issn, type(e), e
            )
        )
    return scielo_journal


def get_or_create_scielo_journal(collection, scielo_issn, journal_acron, user_id):
    try:
        scielo_journal, status = SciELOJournal.objects.get_or_create(
            collection=collection,
            scielo_issn=scielo_issn,
            acron=journal_acron,
            creator_id=user_id,
        )
    except Exception as e:
        raise exceptions.GetOrCreateScieloJournalError(
            _('Unable to get_or_create_scielo_journal {} {} {} {}').format(
                collection, scielo_issn, type(e), e
            )
        )
    return scielo_journal


def get_or_create_journal_collections(official_journal, user_id):
    try:
        scielo_journal, status = JournalCollections.objects.get_or_create(
            official_journal=official_journal,
            creator_id=user_id,
        )
    except Exception as e:
        raise exceptions.GetOrCreateJournalCollectionsError(
            _('Unable to get_or_create_journal_collections {} {} {}').format(
                official_journal, type(e), e
            )
        )
    return scielo_journal


def get_or_create_scielo_journal_in_journal_collections(official_journal, scielo_journal, user_id):

    try:
        journal_collections = get_or_create_journal_collections(official_journal, user_id)

    except Exception as e:
        raise exceptions.GetOrCreateScieloJournalInJournalCollectionsError(
            _('Unable to get_or_create_scielo_journal_in_journal_collections {} {} {} {}').format(
                official_journal, scielo_journal, type(e), e
            )
        )
    try:
        item = JournalCollections.objects.filter(scielo_journals__acron=scielo_journal.acron)
    except Exception as e:
        journal_collections.scielo_journals.add(scielo_journal)
    return journal_collections


def get_journal_collections(collection_acron, scielo_issn):
    try:
        scielo_journal = get_scielo_journal(collection_acron, scielo_issn)

    except Exception as e:
        raise exceptions.GetJournalCollectionsError(
            _('Unable to get_journal_collections {} {} {} {}').format(
                collection, scielo_issn, type(e), e
            )
        )
    return JournalCollections.objects.get(scielo_journals__scielo_issn=scielo_journal.scielo_issn)


###########################################################################

def get_scielo_issue_by_collection(collection_acron, issue_pid):
    try:
        scielo_issue = SciELOIssue.objects.get(
            issue_pid=issue_pid,
            scielo_journal__collection__acron=collection_acron,
        )
    except Exception as e:
        raise exceptions.GetOrCreateScieloIssueError(
            _('Unable to get_scielo_issue {} {} {} {}').format(
                issue_pid, issue_folder, type(e), e
            )
        )
    return scielo_issue


def get_scielo_issue(issue_pid, issue_folder):
    try:
        scielo_issue = SciELOIssue.objects.get(
            issue_pid=issue_pid,
            issue_folder=issue_folder,
        )
    except Exception as e:
        raise exceptions.GetOrCreateScieloIssueError(
            _('Unable to get_scielo_issue {} {} {} {}').format(
                issue_pid, issue_folder, type(e), e
            )
        )
    return scielo_issue


def get_or_create_scielo_issue(scielo_journal, issue_pid, issue_folder, user_id):
    try:
        scielo_issue, status = SciELOIssue.objects.get_or_create(
            scielo_journal=scielo_journal,
            issue_pid=issue_pid,
            issue_folder=issue_folder,
            creator_id=user_id,
        )
    except Exception as e:
        raise exceptions.GetOrCreateScieloIssueError(
            _('Unable to get_or_create_scielo_issue {} {} {} {}').format(
                scielo_journal, issue_pid, type(e), e
            )
        )
    return scielo_issue


def get_or_create_issue_in_collections(official_issue, scielo_issue, user_id):
    try:
        scielo_issue, status = IssueInCollections.objects.get_or_create(
            official_issue=official_issue,
            creator_id=user_id,
        )
    except Exception as e:
        raise exceptions.GetOrCreateIssueInCollectionsError(
            _('Unable to get_or_create_issue_in_collections {} {} {}').format(
                official_issue, type(e), e
            )
        )
    return scielo_issue


def get_or_create_scielo_issue_in_issue_collections(official_issue, scielo_issue, user_id):

    try:
        issue_collections = get_or_create_issue_collections(official_issue, user_id)

    except Exception as e:
        raise exceptions.GetOrCreateScieloIssueInIssueCollectionsError(
            _('Unable to get_or_create_scielo_issue_in_issue_collections {} {} {} {}').format(
                official_issue, scielo_issue, type(e), e
            )
        )
    issue_collections.scielo_issues.get_or_create(scielo_issue)
    return issue_collections


def get_issue_collections(issue_pid, issue_folder):
    try:
        scielo_issue = get_scielo_issue(issue_pid, issue_folder)

    except Exception as e:
        raise exceptions.GetIssueInCollectionsError(
            _('Unable to get_issue_collections {} {} {} {}').format(
                issue_pid, issue_folder, type(e), e
            )
        )
    return IssueInCollections.objects.get(scielo_issues__scielo_issue=scielo_issue)


############################################################################
def get_scielo_document(pid, file_id):
    try:
        scielo_document = SciELODocument.objects.get(
            pid=pid,
            file_id=file_id,
        )
    except Exception as e:
        raise exceptions.GetSciELODocumentError(
            _('Unable to get_scielo_document {} {} {} {}').format(
                pid, file_id, type(e), e
            )
        )
    return scielo_document


def get_or_create_scielo_document(scielo_issue, pid, file_id, user_id):
    try:
        scielo_document, status = SciELODocument.objects.get_or_create(
            scielo_issue=scielo_issue,
            pid=pid,
            file_id=file_id,
            creator_id=user_id,
        )
    except Exception as e:
        raise exceptions.GetOrCreateScieloDocumentError(
            _('Unable to get_or_create_scielo_document {} {} {} {}').format(
                scielo_issue, pid, type(e), e
            )
        )
    return scielo_document


def get_or_create_document_in_collections(official_doc, scielo_document, user_id):
    try:
        scielo_document, status = DocumentInCollections.objects.get_or_create(
            official_document=official_doc,
            creator_id=user_id,
        )
    except Exception as e:
        raise exceptions.GetOrCreateDocumentInCollectionsError(
            _('Unable to get_or_create_document_in_collections {} {} {}').format(
                official_doc, type(e), e
            )
        )
    return scielo_document


def get_or_create_scielo_document_in_document_collections(official_doc, scielo_document):

    try:
        document_collections = get_or_create_document_collections(official_doc)

    except Exception as e:
        raise exceptions.GetOrCreateScieloDocumentInDocumentCollectionsError(
            _('Unable to get_or_create_scielo_document_in_document_collections {} {} {} {}').format(
                official_doc, scielo_document, type(e), e
            )
        )
    document_collections.scielo_docs.get_or_create(scielo_document)
    return document_collections


def get_document_collections(pid, file_id):
    try:
        scielo_doc = get_scielo_document(pid, file_id)

    except Exception as e:
        raise exceptions.GetDocumentInCollectionsError(
            _('Unable to get_doc_collections {} {} {} {}').format(
                pid, file_id, type(e), e
            )
        )
    return DocumentInCollections.objects.get(scielo_docs__scielo_doc=scielo_doc)


class JournalController:

    def __init__(self, user_id, collection_acron, scielo_issn, issn_l, e_issn, print_issn, journal_acron):
        self._user_id = user_id
        self._collection_acron = collection_acron
        self._scielo_issn = scielo_issn
        self._issn_l = issn_l
        self._e_issn = e_issn
        self._print_issn = print_issn
        self._journal_acron = journal_acron

    @property
    def collection(self):
        if not hasattr(self, '_collection') or not self._collection:
            self._collection = get_or_create_collection(
                self._collection_acron, self._user_id)
        return self._collection

    @property
    def scielo_journal(self):
        if not hasattr(self, '_scielo_journal') or not self._scielo_journal:
            self._scielo_journal = get_or_create_scielo_journal(
                self.collection,
                self._scielo_issn,
                self._journal_acron,
                self._user_id,
            )
        return self._scielo_journal

    @property
    def official_journal(self):
        if not hasattr(self, '_official_journal') or not self._official_journal:
            self._official_journal = get_or_create_official_journal(
                self._issn_l, self._e_issn, self._print_issn, self._user_id
            )
        return self._official_journal

    @property
    def scielo_journal_in_journal_collections(self):
        if (not hasattr(self, '_scielo_journal_in_journal_collections') or
                not self._scielo_journal_in_journal_collections):
            self._scielo_journal_in_journal_collections = (
                get_or_create_scielo_journal_in_journal_collections(
                    self.official_journal,
                    self.scielo_journal,
                    self._user_id,
                )
            )
        return self._scielo_journal_in_journal_collections


class IssueController:

    def __init__(self, user_id, collection_acron, scielo_issn,
                 year, volume, number, supplement,
                 issue_pid,
                 is_press_release,
                 ):
        self._user_id = user_id
        self._collection_acron = collection_acron
        self._scielo_issn = scielo_issn
        self._issue_pid = issue_pid
        self._year = year
        self._volume = volume
        self._number = number
        self._supplement = supplement
        self._issue_pid = issue_pid
        self._is_press_release = is_press_release or ''

    @property
    def journal_collections(self):
        if not hasattr(self, '_journal_collections') or not self._journal_collections:
            self._journal_collections = get_journal_collections(
                self._collection_acron, self._scielo_issn
            )
        return self._journal_collections

    @property
    def official_journal(self):
        return self.journal_collections.official_journal

    @property
    def scielo_journal(self):
        if not hasattr(self, '_scielo_journal') or not self._scielo_journal:
            self._scielo_journal = get_scielo_journal(
                self._collection_acron, self._scielo_issn
            )
        return self._scielo_journal

    @property
    def issue_folder(self):
        keys = ("v", "n", "s", "")
        values = (self._volume, self._number, self._supplement, self._is_press_release)
        if self._number in ("ahead", "review"):
            return self._year + "n" + self._number + self._is_press_release
        return "".join([
            f"{k}{v}"
            for k, v in zip(keys, values)
            if v])

    @property
    def scielo_issue(self):
        if not hasattr(self, '_scielo_issue') or not self._scielo_issue:
            self._scielo_issue = get_or_create_scielo_issue(
                self.scielo_journal,
                self._issue_pid,
                self.issue_folder,
                self._user_id,
            )
        return self._scielo_issue

    @property
    def official_issue(self):
        if not hasattr(self, '_official_issue') or not self._official_issue:
            self._official_issue = get_or_create_official_issue(
                self.official_journal,
                self._year,
                self._volume,
                self._number,
                self._supplement,
                self._user_id,
            )
        return self._official_issue

    @property
    def scielo_issue_in_issue_collections(self):
        if (not hasattr(self, '_scielo_issue_in_issue_collections') or
                not self._scielo_issue_in_issue_collections):
            self._scielo_issue_in_issue_collections = (
                get_or_create_scielo_issue_in_issue_collections(
                    self.official_issue,
                    self.scielo_issue,
                    self._user_id,
                )
            )
        return self._scielo_issue_in_issue_collections


class DocumentController:

    def __init__(self, user_id, issue_pid, issue_folder,
                 file_id,
                 pid,
                 xmltree,
                 ):
        self._user_id = user_id
        self._issue_pid = issue_pid
        self._issue_folder = issue_folder
        self._xmltree = xmltree
        self._pid = pid
        self._file_id = file_id

    @property
    def issue_collections(self):
        if not hasattr(self, '_issue_collections') or not self._issue_collections:
            self._issue_collections = get_issue_collections(
                self._issue_pid, self._issue_folder,
            )
        return self._issue_collections

    @property
    def official_issue(self):
        return self.issue_collections.official_issue

    @property
    def scielo_issue(self):
        return get_scielo_issue(
            self._issue_pid, self._issue_folder,
        )

    @property
    def scielo_document(self):
        if not hasattr(self, '_scielo_document') or not self._scielo_document:
            self._scielo_document = get_or_create_scielo_document(
                self.scielo_issue,
                self._pid,
                self._file_id,
                self._user_id,
            )
        return self._scielo_document

    @property
    def official_document(self):
        if not hasattr(self, '_official_document') or not self._official_document:
            self._official_document = get_or_create_official_article(
                self._xmltree
            )
        return self._official_document

    @property
    def scielo_document_in_document_collections(self):
        if not hasattr(self, '_scielo_document_in_document_collections') or not self._scielo_document_in_document_collections:
            self._scielo_document_in_document_collections = (
                get_or_create_scielo_document_in_document_collections(
                    self.official_document,
                    self.scielo_document,
                    self._user_id,
                )
            )
        return self._scielo_document_in_document_collections
