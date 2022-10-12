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
from .choices import MS_IMPORTED, MS_PUBLISHED, MS_TO_IGNORE
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
    Agenda tarefas para importar e publicar dados de title e issue
    """
    logging.info(_("Schedule journals and issues migrations tasks"))
    items = (
        ("title", _("Migrate journals"), 'migration', 0, 2, 0),
        ("issue", _("Migrate issues"), 'migration', 0, 7, 2),
    )

    for db_name, task, action, hours_after_now, minutes_after_now, priority in items:
        for mode in ("full", "incremental"):
            name = f'{collection_acron} | {db_name} | {action} | {mode}'
            kwargs = dict(
                collection_acron=collection_acron,
                user_id=user_id,
                force_update=(mode == "full"),
            )
            try:
                periodic_task = PeriodicTask.objects.get(name=name)
            except PeriodicTask.DoesNotExist:
                hours, minutes = sum_hours_and_minutes(
                    hours_after_now, minutes_after_now)

                periodic_task = PeriodicTask()
                periodic_task.name = name
                periodic_task.task = task
                periodic_task.kwargs = json.dumps(kwargs)
                if mode == "full":
                    periodic_task.priority = priority
                    periodic_task.enabled = False
                    periodic_task.one_off = True
                    periodic_task.crontab = get_or_create_crontab_schedule(
                        hour=hours,
                        minute=minutes,
                    )
                else:
                    periodic_task.priority = priority
                    periodic_task.enabled = True
                    periodic_task.one_off = False
                    periodic_task.crontab = get_or_create_crontab_schedule(
                        minute=minutes,
                    )
                periodic_task.save()
    logging.info(_("Scheduled journals and issues migrations tasks"))


def sum_hours_and_minutes(hours_after_now, minutes_after_now, now=None):
    """
    Retorna a soma dos minutos / horas a partir da hora atual
    """
    now = now or datetime.utcnow()
    hours = now.hour + hours_after_now
    minutes = now.minute + minutes_after_now
    if minutes > 59:
        hours += 1
    hours = hours % 24
    minutes = minutes % 60
    return hours, minutes


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
        self._collection_acron = collection_acron

    @property
    def config(self):
        return (
            MigrationConfiguration.objects.get(
                classic_website_config__collection__acron=self._collection_acron)
        )

    def connect_db(self):
        try:
            return mk_connection(self.config.new_website_config.db_uri)

        except Exception as e:
            raise exceptions.GetMigrationConfigurationError(
                _("Unable to connect db {} {}").format(type(e), e)
            )

    @property
    def classic_website(self):
        try:
            return self.config.classic_website_config

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

    def get_artigo_source_files_paths(self, journal_acron, issue_folder):
        """
        Apesar de fornecer `issue_folder` o retorno pode ser a base de dados
        inteira do `journal_acron`
        """
        logging.info("Harvest classic website records {} {}".format(journal_acron, issue_folder))
        try:
            artigo_source_files_paths = classic_ws.get_artigo_db_path(
                journal_acron, issue_folder, self.classic_website)
        except Exception as e:
            raise exceptions.IssueFilesStoreError(
                _("Unable to get artigo db paths from classic website {} {} {}").format(
                    journal_acron, issue_folder, e,
                )
            )
        logging.info(artigo_source_files_paths)
        return artigo_source_files_paths

    @property
    def classic_website_paths(self):
        try:
            return {
                "BASES_TRANSLATION_PATH": self.classic_website.bases_translation_path,
                "BASES_PDF_PATH": self.classic_website.bases_pdf_path,
                "HTDOCS_IMG_REVISTAS_PATH": self.classic_website.htdocs_img_revistas_path,
                "BASES_XML_PATH": self.classic_website.bases_xml_path,
            }
        except Exception as e:
            raise exceptions.GetMigrationConfigurationError(
                _("Unable to get classic website paths {} {}").format(
                    type(e), e)
            )

    @property
    def bucket_public_subdir(self):
        try:
            return self.config.files_storage_config.bucket_public_subdir
        except Exception as e:
            raise exceptions.GetMigrationConfigurationError(
                _("Unable to get bucket_public_subdir {} {}").format(
                    type(e), e)
            )

    @property
    def bucket_migration_subdir(self):
        try:
            return self.config.files_storage_config.bucket_migration_subdir
        except Exception as e:
            raise exceptions.GetMigrationConfigurationError(
                _("Unable to get bucket_migration_subdir {} {}").format(
                    type(e), e)
            )

    @property
    def files_storage(self):
        try:
            files_storage_config = self.config.files_storage_config
            self._bucket_public_subdir = files_storage_config.bucket_public_subdir
            self._bucket_migration_subdir = files_storage_config.bucket_migration_subdir
            return MinioStorage(
                minio_host=files_storage_config.host,
                minio_access_key=files_storage_config.access_key,
                minio_secret_key=files_storage_config.secret_key,
                bucket_root=files_storage_config.bucket_root,
                bucket_subdir=(
                    files_storage_config.bucket_app_subdir or
                    files_storage_config.bucket_public_subdir),
                minio_secure=files_storage_config.secure,
                minio_http_client=None,
            )
        except Exception as e:
            raise exceptions.GetFilesStorageError(
                _("Unable to get MinioStorage {} {} {}").format(
                    files_storage_config, type(e), e)
            )

    def store_issue_files(self, journal_acron, issue_folder):
        try:
            issue_files = classic_ws.get_issue_files(
                journal_acron, issue_folder, self.classic_website_paths)
        except Exception as e:
            raise exceptions.IssueFilesStoreError(
                _("Unable to get issue files from classic website {} {} {}").format(
                    journal_acron, issue_folder, e,
                )
            )

        for info in issue_files:
            try:
                mimetype = None
                name, ext = os.path.splitext(info['path'])
                if ext in (".xml", ".html", ".htm"):
                    subdir = self.bucket_migration_subdir
                    mimetype = "text/xml" if ext == ".xml" else "html"
                else:
                    subdir = self.bucket_public_subdir
                subdirs = os.path.join(
                    subdir, journal_acron, issue_folder,
                )
                response = self.files_storage.register(
                    info['path'], subdirs=subdirs, preserve_name=True)
                info['relative_path'] = _get_classic_website_rel_path(info['path'])
                info.update(response)
                logging.info("Stored {} in files storage".format(info))
                yield info

            except Exception as e:
                raise exceptions.IssueFilesStoreError(
                    _("Unable to store issue files {} {} {}").format(
                        journal_acron, issue_folder, e,
                    )
                )


def migrate_journals(
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
                action = "import"
                journal_migration = import_data_from_title_database(
                    user_id, collection_acron,
                    scielo_issn, journal_data[0], force_update)
                action = "publish"
                publish_imported_journal(journal_migration)
            except Exception as e:
                _register_failure(
                    _("Error migrating journal {} {}").format(
                        collection_acron, scielo_issn),
                    collection_acron, action, "journal", scielo_issn,
                    e,
                    user_id,
                )
    except Exception as e:
        _register_failure(
            _("Error migrating journal {} {}").format(
                collection_acron, _("GENERAL")),
            collection_acron, action, "journal", _("GENERAL"),
            e,
            user_id,
        )


def import_data_from_title_database(user_id, collection_acron, scielo_issn,
                                    journal_data, force_update=False):
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
        journal_migration.status = MS_IMPORTED
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
            title=journal.title,
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
            official_journal.foundation_date = journal.first_year
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


def publish_imported_journal(journal_migration):
    journal = classic_ws.Journal(journal_migration.data)
    if journal.current_status != CURRENT:
        # journal must not be published
        return

    if journal_migration.status != MS_IMPORTED:
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


def migrate_issues(
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
                action = "import"
                issue_migration = import_data_from_issue_database(
                    user_id=user_id,
                    collection_acron=collection_acron,
                    scielo_issn=issue_pid[:9],
                    issue_pid=issue_pid,
                    issue_data=issue_data[0],
                    force_update=force_update,
                )
                publish_imported_issue(issue_migration, force_update)
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
            collection_acron, "migrate", "issue", "GENERAL",
            e,
            user_id,
        )


def import_data_from_issue_database(
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
        issue_migration.status = MS_IMPORTED
        if issue.is_press_release:
            issue_migration.status = MS_TO_IGNORE
        issue_migration.data = issue_data

        issue_migration.save()
        return issue_migration
    except Exception as e:
        logging.error(_("Error importing issue {} {}").format(collection_acron, issue_pid))
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


def publish_imported_issue(issue_migration, force_update):
    """
    Raises
    ------
    PublishIssueError
    """
    issue = classic_ws.Issue(issue_migration.data)

    if issue_migration.status != MS_IMPORTED and not force_update:
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
