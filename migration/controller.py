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

from scielo_classic_website import classic_ws

from django_celery_beat.models import PeriodicTask, CrontabSchedule

from libs.dsm.files_storage.minio import MinioStorage
from libs.dsm.publication.db import mk_connection
from libs.dsm.publication.journals import JournalToPublish
from libs.dsm.publication.issues import IssueToPublish, get_bundle_id
# from libs.dsm.publication.documents import DocumentToPublish

from core.controller import get_or_create_flexible_date
from collection.choices import CURRENT
from collection import controller as collection_controller
from collection.exceptions import (
    GetSciELOJournalError,
)
from .models import (
    JournalMigration,
    IssueMigration,
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


def start(user_id):
    try:
        logging.info(_("Get or create migration configuration"))
        classic_website, files_storage_config, new_website_config = collection_controller.start()
        try:
            migration_configuration = MigrationConfiguration.objects.get(
                classic_website_config=classic_website)
        except MigrationConfiguration.DoesNotExist:
            migration_configuration = MigrationConfiguration()
            migration_configuration.classic_website_config = classic_website
            migration_configuration.new_website_config = new_website_config
            migration_configuration.files_storage_config = files_storage_config
            migration_configuration.creator_id = user_id
            migration_configuration.save()

        schedule_journals_and_issues_migrations(classic_website.collection.acron, user_id)

    except Exception as e:
        raise exceptions.MigrationStartError("Unable to start system %s" % e)


def schedule_journals_and_issues_migrations(collection_acron, user_id):
    """
    Agenda tarefas para migrar e publicar dados de title e issue
    """
    items = (
        ("title", _("Migrate and publish journals"), 'migration & publication', 1, 0, 0),
        ("issue", _("Migrate and publish issues"), 'migration & publication', 3, 0, 2),
    )

    for db_name, task, action, hours_after_now, minutes_after_now, priority in items:
        for kind in ("full", "incremental"):
            name = f'{collection_acron} | {db_name} | {action} | {kind}'
            try:
                periodic_task = PeriodicTask.objects.get(name=name)
            except PeriodicTask.DoesNotExist:
                now = datetime.utcnow()
                periodic_task = PeriodicTask()
                periodic_task.name = name
                periodic_task.task = task
                periodic_task.kwargs = json.dumps(dict(
                    collection_acron=collection_acron,
                    user_id=user_id,
                    force_update=(kind == "full"),
                ))
                if kind == "full":
                    periodic_task.priority = priority
                    periodic_task.enabled = True
                    periodic_task.one_off = True
                    periodic_task.crontab = get_or_create_crontab_schedule(
                        hour=(now.hour + hours_after_now) % 24,
                        minute=now.minute,
                    )
                else:
                    periodic_task.priority = priority
                    periodic_task.enabled = True
                    periodic_task.one_off = False
                    periodic_task.crontab = get_or_create_crontab_schedule(
                        minute=(now.minute + minutes_after_now) % 60,
                    )
                periodic_task.save()


def get_or_create_crontab_schedule(day_of_week=None, hour=None, minute=None):
    try:
        crontab_schedule, status = CrontabSchedule.objects.get_or_create(
            day_of_week=day_of_week or '*',
            hour=hour or '*',
            minute=minute or '*',
        )
    except Exception as e:
        raise exceptions.GetOrCreateCrontabScheduleError(
            _('Unable to get_or_create_crontab_schedule {} {} {} {} {}').format(
                day_of_week, hour, minute, type(e), e
            )
        )
    return crontab_schedule


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
        try:
            item = JournalMigration.objects.get(
                scielo_journal=scielo_journal,
            )
        except JournalMigration.DoesNotExist:
            item = JournalMigration()
            item.creator_id = creator_id
            item.scielo_journal = scielo_journal
            item.save()
    except Exception as e:
        raise exceptions.GetOrCreateJournalMigrationError(
            _('Unable to get_or_create_journal_migration {} {} {}').format(
                scielo_journal, type(e), e
            )
        )
    return item


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

    scielo_journal = get_scielo_journal(
        journal, collection_acron, scielo_issn, user_id
    )

    # cria ou obtém journal_migration
    journal_migration = get_or_create_journal_migration(
        scielo_journal, creator_id=user_id)

    # check if it needs to be update
    if journal_migration.isis_updated_date == journal.isis_updated_date:
        if not force_update:
            # nao precisa atualizar
            return journal_migration
    try:
        journal_migration.isis_created_date = journal.isis_created_date
        journal_migration.isis_updated_date = journal.isis_updated_date
        journal_migration.status = MS_MIGRATED
        if journal.current_status != CURRENT:
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


def get_scielo_journal(journal, collection_acron, scielo_issn, user_id):

    try:
        # cria ou obtém official_journal
        official_journal = collection_controller.get_or_create_official_journal(
            issn_l=None,
            e_issn=journal.electronic_issn,
            print_issn=journal.print_issn,
            creator_id=user_id,
        )
        official_journal_data = (
            official_journal.title,
            official_journal.foundation_date,
        )
        journal_data = (
            journal.title,
            journal.first_year,
        )
        if official_journal_data != journal_data:
            official_journal.title = journal.title
            official_journal.foundation_date = get_or_create_flexible_date(
                journal.first_year)
            official_journal.save()
    except Exception as e:
        official_journal = None

    # cria ou obtém scielo_journal
    scielo_journal = collection_controller.get_or_create_scielo_journal(
        collection_acron, scielo_issn, user_id
    )
    try:
        scielo_journal_data = (
            scielo_journal.title,
            scielo_journal.availability_status,
            scielo_journal.official_journal,
            scielo_journal.acron,
        )
        journal_data = (
            journal.title,
            journal.current_status,
            official_journal,
            journal.acronym,
        )
        if scielo_journal_data != journal_data:
            scielo_journal.title = journal.title
            scielo_journal.availability_status = journal.current_status
            scielo_journal.official_journal = official_journal
            scielo_journal.acron = journal.acronym
            scielo_journal.save()
    except Exception as e:
        raise exceptions.JournalMigrationSaveError(
            _("Unable to save scielo_journal {} {}").format(
                scielo_journal, e
            )
        )
    return scielo_journal


def publish_migrated_journal(journal_migration):
    journal = classic_ws.Journal(journal_migration.data)
    if journal.current_status != CURRENT:
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


def get_or_create_issue_migration(scielo_issue, creator_id):
    """
    Returns a IssueMigration (registered or new)
    """
    try:
        try:
            item = IssueMigration.objects.get(
                scielo_issue=scielo_issue,
            )
        except IssueMigration.DoesNotExist:
            item = IssueMigration()
            item.creator_id = creator_id
            item.scielo_issue = scielo_issue
            item.save()
    except Exception as e:
        raise exceptions.GetOrCreateIssueMigrationError(
            _('Unable to get_or_create_issue_migration {} {} {}').format(
                scielo_issue, type(e), e
            )
        )
    return item


def migrate_and_publish_issues(
        user_id,
        collection_acron,
        force_update=False,
        ):
    try:
        mcc = MigrationConfigurationController(collection_acron)
        mcc.connect_db()
        source_file_path = mcc.get_source_file_path("issue")

        for issue_pid, issue_data in classic_ws.get_records_by_source_path("issue", source_file_path):
            try:
                action = "migrate"
                issue_migration = migrate_issue(
                    user_id=user_id,
                    collection_acron=collection_acron,
                    scielo_issn=issue_pid[:9],
                    issue_pid=issue_pid,
                    issue_data=issue_data[0],
                    force_update=force_update,
                )
                publish_migrated_issue(issue_migration, force_update)
            except Exception as e:
                _register_failure(
                    _("Error migrating issue {} {}").format(collection_acron, issue_pid),
                    collection_acron, action, "issue", issue_pid,
                    e,
                    user_id,
                )
    except Exception as e:
        _register_failure(
            _("Error migrating issue {}").format(collection_acron),
            collection_acron, action, "issue", "GENERAL",
            e,
            user_id,
        )


def migrate_issue(
        user_id,
        collection_acron,
        scielo_issn,
        issue_pid,
        issue_data,
        force_update=False,
        ):
    """
    Create/update IssueMigration
    """
    issue = classic_ws.Issue(issue_data)

    scielo_issue = get_scielo_issue(
        issue, collection_acron, scielo_issn, issue_pid, user_id)

    issue_migration = get_or_create_issue_migration(
        scielo_issue, creator_id=user_id)

    # check if it needs to be update
    if issue_migration.isis_updated_date == issue.isis_updated_date:
        if not force_update:
            # nao precisa atualizar
            return issue_migration
    try:
        issue_migration.isis_created_date = issue.isis_created_date
        issue_migration.isis_updated_date = issue.isis_updated_date
        issue_migration.status = MS_MIGRATED
        if issue.is_press_release:
            issue_migration.status = MS_TO_IGNORE
        issue_migration.data = issue_data

        issue_migration.save()
        return issue_migration
    except Exception as e:
        logging.error(_("Error migrating issue {} {}").format(collection_acron, issue_pid))
        logging.exception(e)
        raise exceptions.IssueMigrationSaveError(
            _("Unable to save {} migration {} {} {}").format(
                "issue", collection_acron, issue_pid, e
            )
        )


def get_scielo_issue(issue, collection_acron, scielo_issn, issue_pid, user_id):
    # obtém scielo_journal para obter ou criar scielo_issue
    scielo_journal = collection_controller.get_scielo_journal(
        collection_acron, scielo_issn)

    # cria ou obtém scielo_issue
    scielo_issue = collection_controller.get_or_create_scielo_issue(
        scielo_journal,
        issue_pid,
        issue.issue_label,
        user_id,
    )

    official_issue = None
    # obtém official_issue
    if not issue.is_press_release:
        try:
            official_issue = collection_controller.get_or_create_official_issue(
                scielo_journal.official_journal,
                issue.publication_year,
                issue.volume,
                issue.number,
                issue.suppl,
                user_id,
            )
            # atualiza dados de scielo_issue
            scielo_issue.official_issue = official_issue
        except:
            pass
    scielo_issue.publication_date = get_or_create_flexible_date(
        issue.publication_year)
    scielo_issue.save()
    return scielo_issue


def publish_migrated_issue(issue_migration, force_update):
    """
    Raises
    ------
    PublishIssueError
    """
    issue = classic_ws.Issue(issue_migration.data)

    if issue_migration.status != MS_MIGRATED and not force_update:
        return
    try:
        published_id = get_bundle_id(
            issue.journal,
            issue.publication_year,
            issue.volume,
            issue.number,
            issue.supplement,
        )
        issue_to_publish = IssueToPublish(published_id)

        issue_to_publish.add_identification(
            issue.volume,
            issue.number,
            issue.supplement)
        issue_to_publish.add_journal(issue.journal)
        issue_to_publish.add_order(int(issue.order[4:]))
        issue_to_publish.add_pid(issue.pid)
        issue_to_publish.add_publication_date(
            issue.publication_year,
            issue.start_month,
            issue.end_month)
        # FIXME indica se há artigos / documentos
        # para uso de indicação fascículo aop "desativado"
        issue_to_publish.has_docs = []

        issue_to_publish.publish_issue()
    except Exception as e:
        raise exceptions.PublishIssueError(
            _("Unable to publish {} {}").format(
                issue_migration.scielo_issue.issue_pid, e)
        )

    try:
        issue_migration.status = MS_PUBLISHED
        issue_migration.save()
    except Exception as e:
        raise exceptions.PublishIssueError(
            _("Unable to upate issue_migration status {} {}").format(
                issue_migration.scielo_issue.issue_pid, e)
        )
