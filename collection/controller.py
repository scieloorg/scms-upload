import logging

from django.utils.translation import gettext_lazy as _

from .models import (
    Collection,
    SciELOJournal,
    SciELOIssue,
    SciELODocument,
    ClassicWebsiteConfiguration,
    FilesStorageConfiguration,
    NewWebSiteConfiguration,
)
from journal.controller import get_or_create_official_journal
from journal.exceptions import GetOrCreateOfficialJournalError
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
        try:
            logging.info("Create or Get Collection {}".format(collection_acron))
            collection = Collection.objects.get(
                acron=collection_acron,
            )
        except Collection.DoesNotExist:
            logging.info("Create {}".format(collection_acron))
            collection = Collection()
            collection.acron = collection_acron
            collection.creator_id = user_id
            collection.save()
    except Exception as e:
        raise exceptions.GetOrCreateCollectionError(
            _('Unable to get_or_create_collection {} {} {}').format(
                collection_acron, type(e), e
            )
        )
    return collection


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


def get_or_create_scielo_journal(collection_acron, scielo_issn, user_id):
    try:
        try:
            logging.info("Create or Get SciELOJournal {}".format(collection_acron))
            scielo_journal = SciELOJournal.objects.get(
                collection__acron=collection_acron,
                scielo_issn=scielo_issn,
            )
        except SciELOJournal.DoesNotExist:
            logging.info("Create SciELOJournal {}".format(collection_acron))
            scielo_journal = SciELOJournal()
            logging.info("Collection {}".format(collection_acron))
            scielo_journal.collection = get_or_create_collection(
                collection_acron, user_id
            )
            scielo_journal.scielo_issn = scielo_issn
            scielo_journal.creator_id = user_id
            scielo_journal.save()
    except Exception as e:
        raise exceptions.GetOrCreateScieloJournalError(
            _('Unable to get_or_create_scielo_journal {} {} {} {}').format(
                collection_acron, scielo_issn, type(e), e
            )
        )
    return scielo_journal


###########################################################################

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
        try:
            scielo_issue = SciELOIssue.objects.get(
                scielo_journal=scielo_journal,
                issue_pid=issue_pid,
                issue_folder=issue_folder,
            )
        except SciELOIssue.DoesNotExist:
            scielo_issue = SciELOIssue()
            scielo_issue.scielo_journal = scielo_journal
            scielo_issue.issue_folder = issue_folder
            scielo_issue.issue_pid = issue_pid
            scielo_issue.creator_id = user_id
            scielo_issue.save()
    except Exception as e:
        raise exceptions.GetOrCreateScieloIssueError(
            _('Unable to get_or_create_scielo_issue {} {} {} {}').format(
                scielo_journal, issue_pid, type(e), e
            )
        )
    return scielo_issue


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
        try:
            scielo_document = SciELODocument.objects.get(
                scielo_issue=scielo_issue,
                pid=pid,
                file_id=file_id,
            )
        except SciELODocument.DoesNotExist:
            scielo_document = SciELODocument()
            scielo_document.scielo_issue = scielo_issue
            scielo_document.pid = pid
            scielo_document.file_id = file_id
            scielo_document.creator_id = user_id
            scielo_document.save()
    except Exception as e:
        raise exceptions.GetOrCreateScieloDocumentError(
            _('Unable to get_or_create_scielo_document {} {} {} {}').format(
                scielo_issue, pid, type(e), e
            )
        )
    return scielo_document
