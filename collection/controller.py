import logging
import json

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
from libs.dsm.files_storage.minio import MinioStorage
from journal.controller import get_or_create_official_journal
from journal.exceptions import GetOrCreateOfficialJournalError
from issue.controller import get_or_create_official_issue
from article.controller import get_or_create_official_article

from . import exceptions


def update_files_storage_configuration(
        files_storage,
        name, host, access_key, secret_key, secure,
        bucket_root, bucket_public_subdir,
        user_id,
        ):
    files_storage = files_storage or FilesStorageConfiguration()
    files_storage.host = host
    files_storage.secure = secure
    files_storage.access_key = access_key
    files_storage.secret_key = secret_key
    files_storage.bucket_root = bucket_root
    files_storage.bucket_public_subdir = bucket_public_subdir
    files_storage.creator_id = user_id
    files_storage.save()
    return files_storage


def get_files_storage_configuration(name):
    try:
        return FilesStorageConfiguration.objects.get(name=name)
    except FilesStorageConfiguration.DoesNotExist:
        return FilesStorageConfiguration(name=name)


def get_files_storage(files_storage_config):
    try:
        return MinioStorage(
            minio_host=files_storage_config.host,
            minio_access_key=files_storage_config.access_key,
            minio_secret_key=files_storage_config.secret_key,
            bucket_root=files_storage_config.bucket_root,
            bucket_subdir=files_storage_config.bucket_public_subdir,
            minio_secure=files_storage_config.secure,
            minio_http_client=None,
        )
    except Exception as e:
        raise exceptions.GetFilesStorageError(
            _("Unable to get MinioStorage {} {} {}").format(
                files_storage_config, type(e), e)
        )


def start():
    try:
        with open(".envs/.bigbang") as fp:
            data = json.loads(fp.read())
        user_id = 1
        try:
            collection = Collection.objects.get(
                acron=data['collection_acron'])
        except Collection.DoesNotExist:
            collection = Collection()
            collection.acron = data['collection_acron']
            collection.name = data['collection_name']
            collection.creator_id = user_id
            collection.save()
        try:
            classic_website = ClassicWebsiteConfiguration.objects.get(
                collection=collection)
        except ClassicWebsiteConfiguration.DoesNotExist:
            classic_website = ClassicWebsiteConfiguration()
            classic_website.collection = collection
            classic_website.title_path = (
                data['classic_ws_config']['title_path']
            )
            classic_website.issue_path = (
                data['classic_ws_config']['issue_path']
            )
            classic_website.serial_path = (
                data['classic_ws_config']['SERIAL_PATH']
            )
            classic_website.cisis_path = (
                data['classic_ws_config'].get('CISIS_PATH')
            )
            classic_website.bases_work_path = (
                data['classic_ws_config']['BASES_WORK_PATH']
            )
            classic_website.bases_pdf_path = (
                data['classic_ws_config']['BASES_PDF_PATH']
            )
            classic_website.bases_translation_path = (
                data['classic_ws_config']['BASES_TRANSLATION_PATH']
            )
            classic_website.bases_xml_path = (
                data['classic_ws_config']['BASES_XML_PATH']
            )
            classic_website.htdocs_img_revistas_path = (
                data['classic_ws_config']['HTDOCS_IMG_REVISTAS_PATH']
            )
            classic_website.creator_id = user_id
            classic_website.save()
        try:
            files_storage_config = FilesStorageConfiguration.objects.get(
                host=data['files_storage_config']['host'])
        except FilesStorageConfiguration.DoesNotExist:
            files_storage_config = FilesStorageConfiguration()
            files_storage_config.host = data['files_storage_config']['host']
            files_storage_config.access_key = (
                data['files_storage_config']['access_key']
            )
            files_storage_config.secret_key = (
                data['files_storage_config']['secret_key']
            )
            files_storage_config.secure = (
                data['files_storage_config']['secure'] == 'true'
            )
            files_storage_config.bucket_public_subdir = (
                data['files_storage_config']['bucket_public_subdir']
            )
            files_storage_config.bucket_migration_subdir = (
                data['files_storage_config']['bucket_migration_subdir']
            )
            files_storage_config.bucket_root = (
                data['files_storage_config']['bucket_root']
            )
            files_storage_config.creator_id = user_id
            files_storage_config.save()
        try:
            new_website_config = NewWebSiteConfiguration.objects.get(
                url=data['url'])
        except NewWebSiteConfiguration.DoesNotExist:
            new_website_config = NewWebSiteConfiguration()
            new_website_config.db_uri = data['db_uri']
            new_website_config.url = data.get('url')
            new_website_config.creator_id = user_id
            new_website_config.save()

        return (
            classic_website,
            files_storage_config,
            new_website_config,
        )
    except Exception as e:
        raise exceptions.StartCollectionConfigurationError("Unable to start system %s" % e)


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


###########################################################################


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
            logging.info("Create or Get SciELOJournal {} {}".format(
                collection_acron, scielo_issn))
            scielo_journal = SciELOJournal.objects.get(
                collection__acron=collection_acron,
                scielo_issn=scielo_issn,
            )
            logging.info("Got {}".format(scielo_journal))
        except SciELOJournal.DoesNotExist:
            scielo_journal = SciELOJournal()
            scielo_journal.collection = get_or_create_collection(
                collection_acron, user_id
            )
            scielo_journal.scielo_issn = scielo_issn
            scielo_journal.creator_id = user_id
            scielo_journal.save()
            logging.info("Created SciELOJournal {}".format(scielo_journal))
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
            logging.info("Get or create SciELOIssue {} {} {}".format(scielo_journal, issue_pid, issue_folder))
            scielo_issue = SciELOIssue.objects.get(
                scielo_journal=scielo_journal,
                issue_pid=issue_pid,
                issue_folder=issue_folder,
            )
            logging.info("Got {}".format(scielo_issue))
        except SciELOIssue.DoesNotExist:
            scielo_issue = SciELOIssue()
            scielo_issue.scielo_journal = scielo_journal
            scielo_issue.issue_folder = issue_folder
            scielo_issue.issue_pid = issue_pid
            scielo_issue.creator_id = user_id
            scielo_issue.save()
            logging.info("Created {}".format(scielo_issue))
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
            logging.info("Get or create SciELODocument {} {} {}".format(
                scielo_issue, pid, file_id
            ))
            scielo_document = SciELODocument.objects.get(
                scielo_issue=scielo_issue,
                pid=pid,
                file_id=file_id,
            )
            logging.info("Got {}".format(scielo_document))
        except SciELODocument.DoesNotExist:
            scielo_document = SciELODocument()
            scielo_document.scielo_issue = scielo_issue
            scielo_document.pid = pid
            scielo_document.file_id = file_id
            scielo_document.creator_id = user_id
            scielo_document.save()
            logging.info("Created {}".format(scielo_document))
    except Exception as e:
        raise exceptions.GetOrCreateScieloDocumentError(
            _('Unable to get_or_create_scielo_document {} {} {} {}').format(
                scielo_issue, pid, type(e), e
            )
        )
    return scielo_document
