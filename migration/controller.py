import json
import os
import logging
import traceback
import sys
from datetime import datetime
from random import randint

from django.utils.translation import gettext_lazy as _
from django.contrib.auth import get_user_model
from django.db.models import Q

from defusedxml.ElementTree import parse
from defusedxml.ElementTree import tostring as defusedxml_tostring

# from packtools.sps.models.article_assets import (
#     ArticleAssets,
#     SupplementaryMaterials,
# )
# from packtools.sps.models.related_articles import (
#     RelatedItems,
# )
# from packtools.sps.models.article_renditions import (
#     ArticleRenditions,
# )

# from scielo_classic_website import migration as classic_ws
from scielo_classic_website import classic_ws

from django_celery_beat.models import PeriodicTask, CrontabSchedule

from libs.dsm.files_storage.minio import MinioStorage
from libs.dsm.publication.db import mk_connection
from libs.dsm.publication.journals import JournalToPublish
# from libs.dsm.publication.issues import IssueToPublish, get_bundle_id
# from libs.dsm.publication.documents import DocumentToPublish

from collection.choices import CURRENT
from collection.controller import (
    JournalController,
    IssueController,
    DocumentController,
    get_scielo_journal_by_title,
    get_or_create_scielo_journal,
    # get_scielo_issue_by_collection,
    get_classic_website_configuration,
)
from collection.exceptions import (
    GetSciELOJournalError,
)
from .models import (
    JournalMigration,
    # IssueMigration,
    # DocumentMigration,
    # IssueFilesMigration,
    # DocumentFilesMigration,
    MigrationFailure,
    # SciELOFile,
    # SciELOFileWithLang,
    # SciELOHTMLFile,
    MigrationConfiguration,
)
from .choices import MS_MIGRATED, MS_PUBLISHED, MS_TO_IGNORE
from . import exceptions


User = get_user_model()


def insert_hyphen_in_YYYYMMMDD(YYYYMMMDD):
    if YYYYMMMDD[4:6] == "00":
        return f"{YYYYMMMDD[:4]}"
    if YYYYMMMDD[6:] == "00":
        return f"{YYYYMMMDD[:4]}-{YYYYMMMDD[4:6]}"
    return f"{YYYYMMMDD[:4]}-{YYYYMMMDD[4:6]}-{YYYYMMMDD[6:]}"


def _register_failure(msg,
                      collection_acron, action_name, object_name, pid,
                      e,
                      user_id,
                      # exc_type, exc_value, exc_traceback,
                      ):
    exc_type, exc_value, exc_traceback = sys.exc_info()
    logging.error(msg)
    logging.exception(e)
    register_failure(
        collection_acron, action_name, object_name, pid,
        e, exc_type, exc_value, exc_traceback,
        user_id,
    )


def register_failure(collection_acron, action_name, object_name, pid, e,
                     exc_type, exc_value, exc_traceback, user_id):
    migration_failure = MigrationFailure()
    migration_failure.collection_acron = collection_acron
    migration_failure.action_name = action_name
    migration_failure.object_name = object_name
    migration_failure.pid = pid[:23]
    migration_failure.exception_msg = str(e)[:555]
    migration_failure.traceback = [
        str(item)
        for item in traceback.extract_tb(exc_traceback)
    ]
    migration_failure.exception_type = str(type(e))
    migration_failure.creator = User.objects.get(pk=user_id)
    migration_failure.save()


def get_or_create_journal_migration(scielo_journal, creator_id):
    """
    Returns a JournalMigration (registered or new)
    """
    try:
        jm, created = JournalMigration.objects.get_or_create(
            scielo_journal=scielo_journal,
            creator_id=creator_id,
        )
    except Exception as e:
        raise exceptions.GetOrCreateJournalMigrationError(
            _('Unable to get_or_create_journal_migration {} {} {}').format(
                scielo_journal, type(e), e
            )
        )
    return jm


def get_journal_migration_status(scielo_issn):
    """
    Returns a JournalMigration status
    """
    try:
        return JournalMigration.objects.get(
            scielo_journal__scielo_issn=scielo_issn,
        ).status
    except Exception as e:
        raise exceptions.GetJournalMigratioStatusError(
            _('Unable to get_journal_migration_status {} {} {}').format(
                scielo_issn, type(e), e
            )
        )


class MigrationConfigurationController:

    def __init__(self, collection_acron):
        try:
            self._config = MigrationConfiguration.objects.get(
                classic_website_config__collection__acron=collection_acron)
        except Exception as e:
            raise exceptions.GetMigrationConfigurationError(
                _('Unable to get_migration_configuration {} {} {}').format(
                    collection_acron, type(e), e
                )
            )

    def connect_db(self):
        try:
            return mk_connection(self._config.new_website_config.db_uri)

        except Exception as e:
            raise exceptions.GetMigrationConfigurationError(
                _("Unable to connect db {} {}").format(type(e), e)
            )

    @property
    def classic_website(self):
        try:
            return self._config.classic_website_config

        except Exception as e:
            raise exceptions.GetMigrationConfigurationError(
                _("Unable to get classic website configuration {} {}").format(
                    type(e), e)
            )

    def get_source_file_path(self, db_name):
        try:
            return getattr(self.classic_website, f'{db_name}_path')
        except AttributeError:
            raise exceptions.GetMigrationConfigurationError(
                _("Unable to get path of {} {} {}").format(
                    db_name, type(e), e)
            )


def migrate_and_publish_journals(
        user_id,
        collection_acron,
        force_update=False,
        ):
    try:
        action = "migrate"
        mcc = MigrationConfigurationController(collection_acron)
        mcc.connect_db()
        source_file_path = mcc.get_source_file_path("title")

        for scielo_issn, journal_data in classic_ws.get_records_by_source_path("title", source_file_path):
            try:
                action = "migrate"
                journal_migration = migrate_journal(
                    user_id, collection_acron,
                    scielo_issn, journal_data[0], force_update)
                action = "publish"
                publish_migrated_journal(journal_migration)
            except Exception as e:
                _register_failure(
                    _("Error migrating and publishing journal {} {}").format(
                        collection_acron, scielo_issn),
                    collection_acron, action, "journal", scielo_issn,
                    e,
                    user_id,
                )
    except Exception as e:
        _register_failure(
            _("Error migrating and publishing journal {} {}").format(
                collection_acron, _("GENERAL")),
            collection_acron, action, "journal", _("GENERAL"),
            e,
            user_id,
        )


def migrate_journal(user_id, collection_acron, scielo_issn, journal_data,
                    force_update=False):
    """
    Create/update JournalMigration
    """
    journal = classic_ws.Journal(journal_data)
    journal_controller = JournalController(
        user_id=user_id,
        collection_acron=collection_acron,
        scielo_issn=scielo_issn,
        issn_l=None,
        e_issn=journal.electronic_issn,
        print_issn=journal.print_issn,
        journal_acron=journal.acronym,
    )

    journal_migration = get_or_create_journal_migration(
        journal_controller.scielo_journal, creator_id=user_id)

    if not journal_controller.scielo_journal.publication_status or not journal_controller.scielo_journal.title:
        if not journal_controller.scielo_journal.publication_status:
            journal_controller.scielo_journal.publication_status = journal.publication_status
        if not journal_controller.scielo_journal.title:
            journal_controller.scielo_journal.title = journal.title
        journal_controller.scielo_journal.save()

    try:
        jc = journal_controller.scielo_journal_in_journal_collections
        if not jc.official_journal.title or not jc.official_journal.foundation_date:
            if not jc.official_journal.title:
                jc.official_journal.title = journal.title
            if journal.first_year and journal.first_year.isdigit():
                if not jc.official_journal.foundation_year:
                    jc.official_journal.foundation_year = journal.first_year and journal.first_year[:4]
                if not jc.official_journal.foundation_date:
                    jc.official_journal.foundation_date = journal.first_year
            jc.official_journal.save()
    except Exception as e:
        _register_failure(
            _('Updating official journal data error'),
            collection_acron, "migrate", "journal", scielo_issn,
            e,
            user_id,
        )

    # check if it needs to be update
    if journal_migration.isis_updated_date == journal.isis_updated_date:
        if not force_update:
            # nao precisa atualizar
            return journal_migration
    try:
        journal_migration.isis_created_date = journal.isis_created_date
        journal_migration.isis_updated_date = journal.isis_updated_date
        journal_migration.status = MS_MIGRATED
        if journal.publication_status != CURRENT:
            journal_migration.status = MS_TO_IGNORE
        journal_migration.data = journal_data
        journal_migration.save()
        return journal_migration
    except Exception as e:
        raise exceptions.JournalMigrationSaveError(
            _("Unable to save journal migration {} {} {}").format(
                collection_acron, scielo_issn, e
            )
        )


def publish_migrated_journal(journal_migration):
    journal = classic_ws.Journal(journal_migration.data)
    if journal.publication_status != CURRENT:
        # journal must not be published
        return

    if journal_migration.status != MS_MIGRATED:
        return

    try:
        journal_to_publish = JournalToPublish(journal.scielo_issn)
        journal_to_publish.add_contact(
            " | ".join(journal.publisher_name),
            journal.publisher_email,
            ", ".join(journal.publisher_address),
            journal.publisher_city,
            journal.publisher_state,
            journal.publisher_country,
        )

        for mission in journal.mission:
            journal_to_publish.add_item_to_mission(
                mission["language"], mission["text"])

        for item in journal.status_history:
            journal_to_publish.add_item_to_timeline(
                item["status"],
                insert_hyphen_in_YYYYMMMDD(item["date"]),
                item.get("reason"),
            )
        journal_to_publish.add_journal_issns(
            journal.scielo_issn,
            journal.electronic_issn,
            journal.print_issn,
        )
        journal_to_publish.add_journal_titles(
            journal.title,
            journal.abbreviated_iso_title,
            journal.abbreviated_title,
        )

        journal_to_publish.add_online_submission_url(journal.submission_url)

        # TODO links previous e next
        # previous_journal = next_journal_title = None
        # if journal.previous_title:
        #     try:
        #         previous_journal = get_scielo_journal_by_title(
        #             journal.previous_title)
        #     except GetSciELOJournalError:
        #         previous_journal = None
        # if journal.next_title:
        #     try:
        #         next_journal = get_scielo_journal_by_title(journal.next_title)
        #         next_journal_title = journal.next_title
        #     except GetSciELOJournalError:
        #         next_journal_title = None
        # if previous_journal or next_journal_title:
        #     journal_to_publish.add_related_journals(
        #         previous_journal, next_journal_title,
        #     )
        for item in journal.sponsors:
            journal_to_publish.add_sponsor(item)

        # TODO confirmar se subject_categories é subject_descriptors
        journal_to_publish.add_thematic_scopes(
            journal.subject_descriptors, journal.subject_areas,
        )

        # journal não tem este dado
        # journal_to_publish.add_issue_count(
        #     journal.issue_count,
        # )

        # journal não tem este dado
        # journal_to_publish.add_item_to_metrics(
        #     journal.total_h5_index,
        #     journal.total_h5_median,
        #     journal.h5_metric_year,
        # )
        # journal não tem este dado
        # journal_to_publish.add_logo_url(journal.logo_url)
        journal_to_publish.add_acron(journal.acronym)
        journal_to_publish.publish_journal()
    except Exception as e:
        raise exceptions.PublishJournalError(
            _("Unable to publish {} {} {}").format(
                journal_migration, type(e), e)
        )

    try:
        journal_migration.status = MS_PUBLISHED
        journal_migration.save()
    except Exception as e:
        raise exceptions.PublishJournalError(
            _("Unable to publish {} {} {}").format(
                journal_migration, type(e), e)
        )

