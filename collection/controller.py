import logging
import json

from django.utils.translation import gettext_lazy as _
from .models import (
    Collection,
    SciELOJournal,
    SciELOIssue,
    SciELODocument,
    ClassicWebsiteConfiguration,
    NewWebSiteConfiguration,
)
from files_storage.models import Configuration as FilesStorageConfiguration
from . import exceptions


def load_config(user):
    try:
        with open(".envs/.bigbang") as fp:
            data = json.loads(fp.read())

        collection = Collection.get_or_create(
            data['collection_acron'],
            data['collection_name'],
            user,
        )
        classic_website = ClassicWebsiteConfiguration.get_or_create(
            collection, data['classic_ws_config'], user,
        )
        for fs_data in data['files_storages']:
            fs_data['user'] = user
            fs_config = FilesStorageConfiguration.get_or_create(
                **fs_data
            )
        new_website_config = NewWebSiteConfiguration.get_or_create(
            data['url'], data['db_uri'], user)
    except Exception as e:
        raise exceptions.StartCollectionConfigurationError(
            "Unable to start system %s" % e)

###########################################################################


def get_updated_scielo_journal(
        user,
        collection_acron, scielo_issn,
        classic_website_journal,
        official_journal,
        ):

    # cria ou obtém scielo_journal
    scielo_journal = SciELOJournal.get_or_create(
        collection_acron, scielo_issn, user)
    scielo_journal.update(
        user,
        acron=classic_website_journal.acronym,
        title=classic_website_journal.title,
        availability_status=classic_website_journal.current_status,
        official_journal=official_journal,
    )
    return scielo_journal


###########################################################################

def get_scielo_issue(issue_pid, issue_folder):
    return SciELOIssue.get(issue_pid, issue_folder)


def get_updated_scielo_issue(
        user,
        collection_acron,
        scielo_issn,
        issue_pid,
        issue,
        official_issue=None,
        ):
    logging.info(_("Get SciELO Issue {} {} {}").format(
        collection_acron, scielo_issn, issue_pid))

    try:
        # obtém scielo_journal para criar ou obter scielo_issue
        scielo_journal = SciELOJournal.get_or_create(
            collection_acron, scielo_issn, user)

        # cria ou obtém scielo_issue
        scielo_issue = SciELOIssue.get_or_create(
            scielo_journal=scielo_journal,
            issue_pid=issue_pid,
            issue_folder=issue.issue_label,
            creator=user,
        )
        scielo_issue.update(user, official_issue)

        return scielo_issue
    except Exception as e:
        raise exceptions.GetUpdatedSciELOIssueError(
            _("Unable to get updated SciELO issue {} {} {} {}").format(
                collection_acron, issue_pid, type(e), e
            )
        )

############################################################################


def get_scielo_document(pid, key):
    return SciELODocument.get(pid, key)


def get_or_create_scielo_document(scielo_issue, pid, key, creator):
    return SciELODocument.get(scielo_issue, pid, key, creator)
