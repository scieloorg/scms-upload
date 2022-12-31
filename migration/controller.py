import json
import os
import logging
import traceback
import sys
from datetime import datetime
from random import randint
from io import StringIO

from django.utils.translation import gettext_lazy as _
from django.contrib.auth import get_user_model
from django.db.models import Q

from lxml import etree

from packtools.sps.models.article_assets import (
    ArticleAssets,
    SupplementaryMaterials,
)
from packtools.sps.models.related_articles import (
    RelatedItems,
)
from packtools.sps.models.article_renditions import (
    ArticleRenditions,
)

from scielo_classic_website import classic_ws

from django_celery_beat.models import PeriodicTask, CrontabSchedule

from libs.xml_sps_utils import get_xml_with_pre_from_uri
from libs.dsm.publication.db import mk_connection
from libs.dsm.publication.journals import JournalToPublish
from libs.dsm.publication.issues import IssueToPublish, get_bundle_id
from libs.dsm.publication.documents import DocumentToPublish
from pid_provider.controller import PidProvider
from core.controller import parse_non_standard_date, parse_months_names

from collection.choices import CURRENT
from collection.controller import load_config
from collection.exceptions import (
    GetSciELOJournalError,
)
from files_storage.controller import FilesStorageManager
from .models import (
    JournalMigration,
    IssueMigration,
    DocumentMigration,
    MigrationFailure,
    MigrationConfiguration,
)
from collection.models import (
    XMLFile,
    AssetFile,
    FileWithLang,
    SciELOHTMLFile,
)
from .choices import MS_IMPORTED, MS_PUBLISHED, MS_TO_IGNORE
from . import exceptions
from journal.controller import get_updated_official_journal
from issue.controller import get_or_create as official_issue_get_or_create
from publication.models import Article as PublicationArticle


User = get_user_model()


def read_xml_file(file_path):
    return etree.parse(file_path)


def tostring(xmltree):
    # garante que os diacríticos estarão devidamente representados
    return etree.tostring(xmltree, encoding="utf-8").decode("utf-8")


def _get_classic_website_rel_path(file_path):
    if 'htdocs' in file_path:
        return file_path[file_path.find("htdocs"):]
    if 'base' in file_path:
        return file_path[file_path.find("base"):]


def start(user_id):
    try:
        user = User.objects.get(pk=user_id)

        load_config(user)

        migration_configuration = MigrationConfiguration.get_or_create(
            ClassicWebsiteConfiguration.objects.all().first(),
            NewWebSiteConfiguration.objects.all().first(),
            FilesStorageConfiguration.get_or_create(name='website'),
            FilesStorageConfiguration.get_or_create(name='migration'),
            user,
        )

        schedule_journals_and_issues_migrations(
            migration_configuration.classic_website_config.collection.acron,
            user,
        )

    except Exception as e:
        raise exceptions.MigrationStartError(
            "Unable to start migration %s" % e)


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


def schedule_issues_documents_migration(collection_acron, user_id):
    """
    Agenda tarefas para migrar e publicar todos os documentos
    """
    for issue_migration in IssueMigration.objects.filter(
            scielo_issue__scielo_journal__collection__acron=collection_acron):

        journal_acron = issue_migration.scielo_issue.scielo_journal.acron
        scielo_issn = issue_migration.scielo_issue.scielo_journal.scielo_issn
        publication_year = issue_migration.scielo_issue.official_issue.publication_year

        schedule_issue_documents_migration(
            issue_migration, journal_acron,
            scielo_issn, publication_year, user_id)


def schedule_issue_documents_migration(collection_acron,
                                       journal_acron,
                                       scielo_issn,
                                       publication_year,
                                       user_id):
    """
    Agenda tarefas para migrar e publicar um conjunto de documentos por:

        - ano
        - periódico
        - periódico e ano
    """
    logging.info(_("Schedule issue documents migration {} {} {} {}").format(
        collection_acron,
        journal_acron,
        scielo_issn,
        publication_year,
    ))
    action = 'migrate'
    task = _('Migrate documents')

    params_list = (
        {"scielo_issn": scielo_issn, "publication_year": publication_year},
        {"scielo_issn": scielo_issn},
        {"publication_year": publication_year},
    )
    documents_group_ids = (
        f"{journal_acron} {publication_year}",
        f"{journal_acron}",
        f"{publication_year}",
    )

    count = 0
    for group_id, params in zip(documents_group_ids, params_list):
        count += 1
        if len(params) == 2:
            modes = ("full", "incremental")
        else:
            modes = ("incremental", )

        for mode in modes:

            name = f'{collection_acron} | {group_id} | {action} | {mode}'

            kwargs = dict(
                collection_acron=collection_acron,
                user_id=user_id,
                force_update=(mode == "full"),
            )
            kwargs.update(params)

            try:
                periodic_task = PeriodicTask.objects.get(name=name, task=task)
            except PeriodicTask.DoesNotExist:
                now = datetime.utcnow()
                periodic_task = PeriodicTask()
                periodic_task.name = name
                periodic_task.task = task
                periodic_task.kwargs = json.dumps(kwargs)
                if mode == "full":
                    # full: force_update = True
                    # modo full está programado para ser executado manualmente
                    # ou seja, a task fica disponível para que o usuário
                    # apenas clique em RUN e rodará na sequência,
                    # não dependente dos atributos: enabled, one_off, crontab

                    # prioridade alta
                    periodic_task.priority = 1
                    # desabilitado para rodar automaticamente
                    periodic_task.enabled = False
                    # este parâmetro não é relevante devido à execução manual
                    periodic_task.one_off = True
                    # este parâmetro não é relevante devido à execução manual
                    hours, minutes = sum_hours_and_minutes(0, 1)
                    periodic_task.crontab = get_or_create_crontab_schedule(
                        hour=hours,
                        minute=minutes,
                    )
                else:
                    # modo incremental está programado para ser executado
                    # automaticamente
                    # incremental: force_update = False

                    # prioridade 3, exceto se houver ano de publicação
                    periodic_task.priority = 3
                    if publication_year:
                        # estabelecer prioridade maior para os mais recentes
                        periodic_task.priority = (
                            datetime.now().year - int(publication_year)
                        )

                    # deixa habilitado para rodar frequentemente
                    periodic_task.enabled = True

                    # programado para rodar automaticamente 1 vez se o ano de
                    # publicação não é o atual
                    periodic_task.one_off = (
                        publication_year and
                        publication_year != datetime.now().year
                    )

                    # distribui as tarefas para executarem dentro de 1h
                    # e elas executarão a cada 1h
                    hours, minutes = sum_hours_and_minutes(0, count % 100)
                    periodic_task.crontab = get_or_create_crontab_schedule(
                        # hour=hours,
                        minute=minutes,
                    )
                periodic_task.save()
    logging.info(_("Scheduled {} tasks to migrate documents").format(count))


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


class IssueFilesController:

    ClassFileModels = {
        "asset": AssetFile,
        "pdf": FileWithLang,
        "xml": XMLFile,
        "html": SciELOHTMLFile,
    }

    def __init__(self, scielo_issue):
        self.scielo_issue = scielo_issue

    def add_file(self, item):
        item['scielo_issue'] = self.scielo_issue
        ClassFile = self.ClassFileModels[item.pop('type')]
        return ClassFile.create_or_update(item)

    def get_files(self, type_, key, **kwargs):
        ClassFile = self.ClassFileModels[type_]
        return ClassFile.objects.filter(
            scielo_issue=self.scielo_issue,
            key=key,
            **kwargs,
        )

    def migrate_files(self, mcc):
        # obtém os arquivos de site clássico
        issue_files = mcc.get_classic_website_issue_files(
            self.scielo_issue.scielo_journal.acron,
            self.scielo_issue.issue_folder,
        )
        result = {"failures": [], "success": []}
        for item in issue_files:
            self.migrate_file(mcc, item)
            if item.get("error"):
                result['failures'].append(item['path'])
            else:
                result['success'].append(item['path'])
        return result

    def migrate_file(self, mcc, item):
        try:
            # create AssetFile or XMLFile or SciELOHTMLFile
            file = self.add_file(item)

            # instancia files storage manager (website ou migration)
            # de acordo com o arquivo
            files_storage_manager = mcc.get_files_storage(item['path'])

            # armazena arquivo
            response = files_storage_manager.push_file(
                file.versions,
                item['path'],
                subdirs=os.path.join(
                    self.scielo_issue.scielo_journal.acron,
                    self.scielo_issue.issue_folder,
                ),
                preserve_name=True,
                creator=mcc.user)
            item.update(response)
        except Exception as e:
            item['error'] = str(e)
            item['error_type'] = str(type(e))

    @property
    def uris(self):
        if not hasattr(self, '_uris') or not self._uris:
            self._uris = {
                name: asset.uri
                for name, asset in self.issue_assets_dict.items()
            }
        return self._uris

    @property
    def issue_assets_dict(self):
        if not hasattr(self, '_issue_assets_as_dict') or not self._issue_assets_as_dict:
            self._issue_assets_as_dict = {
                asset.name: asset
                for asset in AssetFile.objects.filter(
                    scielo_issue=self.scielo_issue,
                )
            }
        return self._issue_assets_as_dict


class MigrationConfigurationController:

    def __init__(self, collection_acron, user):
        self.config = (
            MigrationConfiguration.objects.get(
                classic_website_config__collection__acron=collection_acron)
        )
        self.classic_website = self.config.classic_website_config
        self.fs_managers = dict(
            website=FilesStorageManager(
                self.config.public_files_storage_config.name),
            migration=FilesStorageManager(
                self.config.migration_files_storage_config.name),
        )
        self.user = user
        self.pid_requester = PidRequester('website')

    def pid_provider_request_document_ids(self, xml_with_pre, name, user):
        # TODO
        # {"v3": '', "xml_file_versions": ""}
        return self.pid_requester.request_doc_ids(xml_with_pre, name, user)

    def connect_db(self):
        try:
            return mk_connection(self.config.new_website_config.db_uri)
        except Exception as e:
            raise exceptions.GetMigrationConfigurationError(
                _("Unable to connect db {} {}").format(type(e), e)
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

    def get_classic_website_issue_files(self, journal_acron, issue_folder):
        try:
            classic_website_paths = {
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
        try:
            issue_files = classic_ws.get_issue_files(
                journal_acron, issue_folder, classic_website_paths)
        except Exception as e:
            raise exceptions.IssueFilesStoreError(
                _("Unable to get issue files from classic website {} {} {}").format(
                    journal_acron, issue_folder, e,
                )
            )

        for info in issue_files:
            try:
                info['relative_path'] = _get_classic_website_rel_path(info['path'])
            except Exception as e:
                info['error'] = str(e)
                info['error_type'] = str(type(e))
            yield info

    def get_files_storage(self, filename):
        name, ext = os.path.splitext(filename)
        if ext in (".xml", ".html", ".htm"):
            return self.fs_managers['migration']
        else:
            return self.fs_managers['website']


def migrate_journals(
        user_id,
        collection_acron,
        force_update=False,
        ):
    try:
        action = "migrate"
        mcc = MigrationConfigurationController(
            collection_acron, User.objects.get(pk=user_id))
        mcc.connect_db()
        source_file_path = mcc.get_source_file_path("title")

        for scielo_issn, journal_data in classic_ws.get_records_by_source_path("title", source_file_path):
            try:
                action = "import"
                journal_migration = import_data_from_title_database(
                    mcc.user, collection_acron,
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


def import_data_from_title_database(user, collection_acron,
                                    scielo_issn,
                                    journal_data, force_update=False):
    """
    Create/update JournalMigration
    """
    try:
        # obtém classic website journal
        classic_website_journal = classic_ws.Journal(journal_data)

        # cria ou obtém official_journal
        official_journal = get_updated_official_journal(
            user,
            title=classic_website_journal.title,
            issn_l=None,
            e_issn=classic_website_journal.electronic_issn,
            print_issn=classic_website_journal.print_issn,
            short_title=classic_website_journal.title_iso,
            foundation_date=classic_website_journal.first_year,
            foundation_year=classic_website_journal.first_year,
            foundation_month=None,
            foundation_day=None,
        )

        # cria ou obtém scielo_journal
        scielo_journal = collection_controller.get_updated_scielo_journal(
            user,
            collection_acron,
            scielo_issn,
            classic_website_journal,
            official_journal,
        )

        # cria ou obtém journal_migration
        journal_migration = JournalMigration.get_or_create(
            scielo_journal, user, force_update)

        # atualiza journal_migration
        journal_migration.update(journal, journal_data)
        return journal_migration
    except Exception as e:
        raise exceptions.JournalMigrationSaveError(
            _("Unable to save journal migration {} {} {}").format(
                collection_acron, scielo_issn, e
            )
        )


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


def migrate_issues(
        user_id,
        collection_acron,
        force_update=False,
        ):
    try:
        mcc = MigrationConfigurationController(
            collection_acron, User.objects.get(pk=user_id))
        mcc.connect_db()
        source_file_path = mcc.get_source_file_path("issue")

        user = mcc.user
        for issue_pid, issue_data in classic_ws.get_records_by_source_path("issue", source_file_path):
            try:
                action = "import"
                issue_migration = import_data_from_issue_database(
                    user=user,
                    collection_acron=collection_acron,
                    scielo_issn=issue_pid[:9],
                    issue_pid=issue_pid,
                    issue_data=issue_data[0],
                    force_update=force_update,
                )
                if issue_migration.status == MS_IMPORTED:
                    schedule_issue_documents_migration(
                        collection_acron=collection_acron,
                        journal_acron=issue_migration.scielo_issue.scielo_journal.acron,
                        scielo_issn=issue_migration.scielo_issue.scielo_journal.scielo_issn,
                        publication_year=issue_migration.scielo_issue.official_issue.publication_year,
                        user_id=user_id,
                    )
                    publish_imported_issue(issue_migration)
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
        user,
        collection_acron,
        scielo_issn,
        issue_pid,
        issue_data,
        force_update=False,
        ):
    """
    Create/update IssueMigration
    """
    try:
        logging.info("Import data from database issue {} {} {}".format(
            collection_acron, scielo_issn, issue_pid))

        classic_website_issue = classic_ws.Issue(issue_data)

        scielo_issue = get_scielo_issue(
            classic_website_issue,
            collection_acron,
            scielo_issn,
            issue_pid,
            user,
        )

        issue_migration = IssueMigration.get_or_create(
            scielo_issue, creator=user)

        issue_migration.update(classic_website_issue, issue_data, force_update)
        return issue_migration
    except Exception as e:
        logging.error(_("Error importing issue {} {} {}").format(collection_acron, issue_pid, issue_data))
        logging.exception(e)
        raise exceptions.IssueMigrationSaveError(
            _("Unable to save {} migration {} {} {}").format(
                "issue", collection_acron, issue_pid, e
            )
        )


def _get_months_from_issue(classic_website_issue):
    """
    Get months from issue (classic_website.Issue)
    """
    months_names = {}
    for item in classic_website_issue.bibliographic_strip_months:
        if item.get("text"):
            months_names[item['lang']] = item.get("text")
    if months_names:
        return months_names.get("en") or months_names.values()[0]


def get_scielo_issue(
            classic_website_issue,
            collection_acron,
            scielo_issn,
            issue_pid,
            user,
            ):
    logging.info(_("Get SciELO Issue {} {} {}").format(
        collection_acron, scielo_issn, issue_pid))

    try:

        official_issue = get_or_create_official_issue(
            classic_website_issue, collection_acron,
            scielo_issn, issue_pid, user
        )
        return get_updated_scielo_issue(
            user,
            collection_acron,
            scielo_issn,
            issue_pid,
            classic_website_issue,
            official_issue,
        )
    except Exception as e:
        raise exceptions.GetSciELOIssueError(
            _("Unable to get SciELO issue {} {} {}").format(
                scielo_issue, type(e), e
            )
        )


def get_or_create_official_issue(classic_website_issue, collection_acron,
                                 scielo_issn, issue_pid, user):
    if classic_website_issue.is_press_release:
        # press release não é um documento oficial,
        # sendo assim, não será criado official issue correspondente
        return

    try:
        # obtém ou cria official_issue
        logging.info(_("Create official issue {}").format(
            classic_website_issue))

        flexible_date = parse_non_standard_date(
            classic_website_issue.publication_date)
        months = parse_months_names(_get_months_from_issue(issue))
        return official_issue_get_or_create(
            official_journal,
            classic_website_issue.publication_year,
            classic_website_issue.volume,
            classic_website_issue.number,
            classic_website_issue.supplement,
            user,
            initial_month_number=flexible_date.get("month_number"),
            initial_month_name=months.get("initial_month_name"),
            final_month_name=months.get("final_month_name"),
        )
    except Exception as e:
        raise exceptions.GetOrCreateOfficialIssueError(
            _("Unable to set official issue to SciELO issue {} {} {}").format(
                scielo_issue, type(e), e
            )
        )
    return scielo_issue


def publish_imported_issue(issue_migration):
    """
    Raises
    ------
    PublishIssueError
    """
    issue = classic_ws.Issue(issue_migration.data)

    if issue_migration.status != MS_IMPORTED:
        logging.info("Skipped: publish issue {}".format(issue_migration))
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


def import_issues_files_and_migrate_documents(
        user_id,
        collection_acron,
        scielo_issn=None,
        publication_year=None,
        force_update=False,
        ):

    params = {
        'scielo_issue__scielo_journal__collection__acron': collection_acron
    }
    if scielo_issn:
        params['scielo_issue__scielo_journal__scielo_issn'] = scielo_issn
    if publication_year:
        params['scielo_issue__official_issue__publication_year'] = publication_year

    logging.info(params)

    items = IssueMigration.objects.filter(
        Q(status=MS_PUBLISHED) | Q(status=MS_IMPORTED),
        **params,
    )

    mcc = MigrationConfigurationController(
        collection_acron, User.objects.get(pk=user_id))
    mcc.connect_db()

    for issue_migration in items:
        try:
            import_issue_files(
                user_id=user_id,
                issue_migration=issue_migration,
                mcc=mcc,
                force_update=force_update,
            )
        except Exception as e:
            _register_failure(
                _("Error import isse files of {}").format(issue_migration),
                collection_acron, "import", "issue files",
                issue_migration.scielo_issue.issue_pid,
                e,
                user_id,
            )

    for issue_migration in items:
        try:
            for source_file_path in mcc.get_artigo_source_files_paths(
                    issue_migration.scielo_issue.scielo_journal.acron,
                    issue_migration.scielo_issue.issue_folder,
                    ):

                # migra os documentos da base de dados `source_file_path`
                # que não contém necessariamente os dados de só 1 fascículo
                migrate_documents(
                    mcc.user,
                    collection_acron,
                    source_file_path,
                    issue_migration,
                    mcc,
                    force_update,
                )

        except Exception as e:
            _register_failure(
                _("Error importing documents of {}").format(issue_migration),
                collection_acron, "import", "document",
                issue_migration.scielo_issue.issue_pid,
                e,
                user_id,
            )


# FIXME remover user_id
def import_issue_files(
        user_id,
        issue_migration,
        mcc,
        force_update,
        ):
    """135
    Migra os arquivos do fascículo (pdf, img, xml ou html)
    """
    logging.info("Import issue files {}".format(issue_migration.scielo_issue))
    if issue_migration.files_status == MS_IMPORTED and not force_update:
        logging.info("Skipped: Import files from classic website {}".format(
            issue_migration))
        return

    try:
        scielo_issue = issue_migration.scielo_issue
        issue = classic_ws.Issue(issue_migration.data)
        issue_files_controller = IssueFilesController(scielo_issue)
        result = issue_files_controller.migrate_files(mcc)
        if not result.get("failures"):
            issue_migration.files_status = MS_IMPORTED
            issue_migration.save()
    except Exception as e:
        raise exceptions.IssueFilesMigrationSaveError(
            _("Unable to save issue files migration {} {}").format(
                scielo_issue, e)
        )


def migrate_documents(
        user,
        collection_acron,
        source_file_path,
        issue_migration,
        mcc,
        force_update=False,
        ):
    """
    Importa os registros presentes na base de dados `source_file_path`
    Importa os arquivos dos documentos (xml, pdf, html, imagens)
    Publica os artigos no site
    """
    try:
        # apesar de supostamente estar migrando documentos de um fascículo
        # é possível que source_file_path contenha artigos de mais de 1 issue

        # obtém os registros de title e issue
        journal_migration = JournalMigration.objects.get(
            scielo_journal=issue_migration.scielo_issue.scielo_journal
        )
        journal_issue_and_document_data = {
            'title': journal_migration.data,
            'issue': issue_migration.data,
        }

        # obtém registros da base "artigo" que não necessariamente é só
        # do fascículo de issue_migration
        # possivelmente source_file pode conter registros de outros fascículos
        # se source_file for acrônimo
        logging.info("Importing documents records from source_file_path={}".format(source_file_path))
        for grp_id, grp_records in classic_ws.get_records_by_source_path(
                "artigo", source_file_path):
            try:
                logging.info(_("Get {} from {}").format(grp_id, source_file_path))
                if len(grp_records) == 1:
                    # é possível que em source_file_path exista registro tipo i
                    journal_issue_and_document_data['issue'] = grp_records[0]
                    continue

                journal_issue_and_document_data['article'] = grp_records
                migrate_document(
                    mcc,
                    user,
                    collection_acron,
                    scielo_issn,
                    issue_pid,
                    journal_issue_and_document_data,
                )

            except Exception as e:
                _register_failure(
                    _('Error migrating document {}').format(pid),
                    collection_acron, "migrate", "document", pid,
                    e,
                    user,
                )
    except Exception as e:
        _register_failure(
            _('Error migrating documents'),
            collection_acron, "migrate", "document", "GENERAL",
            e,
            user,
        )


def migrate_document(
        mcc,
        user,
        collection_acron,
        scielo_issn,
        issue_pid,
        journal_issue_and_document_data,
        ):
    # instancia Document com registros de title, issue e artigo
    document = classic_ws.Document(journal_issue_and_document_data)
    pid = document.pid
    scielo_issn = document.journal.scielo_issn
    issue_pid = document.issue.pid

    scielo_issue = get_scielo_issue(
        document.issue, collection_acron, scielo_issn,
        issue_pid, user)

    scielo_document = collection_controller.get_or_create_scielo_document(
        scielo_issue,
        pid,
        document.filename_without_extension,
        user,
    )
    issue_files_controller = IssueFilesController(
        scielo_document.scielo_issue, scielo_document.key)

    # busca o pdf que tem o idioma == 'main'
    try:
        files = issue_files_controller.get_files('pdf', ang='main')
        files[0].lang = document.original_language
        files[0].save()
    except IndexError:
        pass
    # atualiza rendition files do scielo_document
    scielo_document.rendition_files.set(
        issue_files_controller.get_files('pdf')
    )
    scielo_document.html_files.set(
        issue_files_controller.get_files('html')
    )
    scielo_document.xml_files.set(
        issue_files_controller.get_files('xml')
    )
    if scielo_document.html_files.count() > 0:
        add_xml_generated_from_html(scielo_document, document, mcc, user)
    scielo_document.set_langs()
    scielo_document.add_assets(issue_files_controller.issue_assets_dict)
    scielo_document.save()

    # XMLFile
    xml_pre_with_remote_assets = (
        scielo_document.get_xml_with_pre_with_remote_assets(
            issue_files_controller.issue_assets_uris))

    response = mcc.pid_provider_request_document_ids(
        **xml_pre_with_remote_assets)

    article = PublicationArticle.get_or_create(response['v3'])

    document_migration.update(document, document_data, force_update)

    publish_document(
        pid,
        response['v3'],
        article.xml_uri,
        document, document_migration,
        scielo_document,
    )


def add_xml_generated_from_html(scielo_document, document, mcc, user):
    for item in scielo_document.html_files.iterator():
        xml_from_html = document.filename_without_extension + ".xml"
        subdirs = "/".join(
            item.relative_path.split("/")[-3:-1])
        data = {
            'scielo_issue': item.scielo_issue,
            'key': document.filename_without_extension,
            'relative_path': os.path.join(subdirs, xml_from_html),
            'name': xml_from_html,
        }
        xml_file = XMLFile.create_or_update(data)
        mcc.fs_managers['migration'].push_xml_content(
            xml_file.versions,
            xml_from_html,
            subdirs,
            document.xml_from_html,
            user,
        )
        scielo_document.xml_files.add(xml_file)
        scielo_document.xml_files.save()
        scielo_document.save()
        break


def publish_document(pid, v3, xml_uri,
                     document, document_migration, scielo_document):
    """
    Atualiza o registro do site novo,
    preenchendo opac_schema.models.v1.Article com dados provenientes
    principalmente dos registros das bases ISIS +
    alguns dados provenientes do XML

    Raises
    ------
    PublishDocumentError
    """
    doc_to_publish = DocumentToPublish(pid)

    if doc_to_publish.doc.created:
        logging.info(
            "Skipped: Publish document {}. It is already published {}".format(
                document_migration, doc_to_publish.doc.created))
        return

    if document_migration.status != MS_IMPORTED:
        logging.info(
            "Skipped: Publish document {}. Migration status = {} ".format(
                document_migration, document_migration.status))
        return

    try:
        # IDS
        doc_to_publish.add_identifiers(
            v3,
            document.scielo_pid_v2,
            document.publisher_ahead_id,
        )

        # MAIN METADATA
        doc_to_publish.add_document_type(document.document_type)
        doc_to_publish.add_main_metadata(
            document.original_title,
            document.section,
            document.original_abstract,
            document.original_language,
            document.doi,
        )
        for item in document.authors:
            doc_to_publish.add_author(
                item['surname'], item['given_names'],
                item.get("suffix"),
                item.get("affiliation"),
                item.get("orcid"),
            )

        # ISSUE
        try:
            year = document.document_publication_date[:4]
            month = document.document_publication_date[4:6]
            day = document.document_publication_date[6:]
            doc_to_publish.add_publication_date(year, month, day)
        except:
            logging.info("Document has no document publication date %s" % pid)
        doc_to_publish.add_in_issue(
            document.order,
            document.fpage,
            document.fpage_seq,
            document.lpage,
            document.elocation,
        )

        # ISSUE
        bundle_id = get_bundle_id(
            document.journal.scielo_issn,
            document.issue_publication_date[:4],
            document.volume,
            document.issue_number,
            document.supplement,
        )
        doc_to_publish.add_issue(bundle_id)

        # JOURNAL
        doc_to_publish.add_journal(document.journal.scielo_issn)

        # IDIOMAS
        for item in document.doi_with_lang:
            doc_to_publish.add_doi_with_lang(item["language"], item["doi"])

        for item in document.abstracts:
            doc_to_publish.add_abstract(item['language'], item['text'])

        # nao há translated sections
        # TODO necessario resolver
        # for item in document.translated_sections:
        #     doc_to_publish.add_section(item['language'], item['text'])

        for item in document.translated_titles:
            doc_to_publish.add_translated_title(
                item['language'], item['text'],
            )
        for lang, keywords in document.keywords_groups.items():
            doc_to_publish.add_keywords(lang, keywords)

        # ARQUIVOS
        # xml
        doc_to_publish.add_xml(xml_uri)

        # htmls
        for item in scielo_document.text_langs:
            doc_to_publish.add_html(item['lang'], uri=None)

        # pdfs
        for item in scielo_document.rendition_files.iterator():
            doc_to_publish.add_pdf(
                lang=item.lang,
                url=item.uri,
                filename=item.name,
                type='pdf',
            )

        # mat supl
        for item in scielo_document.supplementary_materials:
            doc_to_publish.add_mat_suppl(
                lang=item['lang'],
                url=item['uri'],
                ref_id=item['ref_id'],
                filename=item['name'])

        # RELATED
        # doc_to_publish.add_related_article(doi, ref_id, related_type)
        # <related-article
        #  ext-link-type="doi" id="A01"
        #  related-article-type="commentary-article"
        #  xlink:href="10.1590/0101-3173.2022.v45n1.p139">

        for item in scielo_document.related_items:
            logging.info(item)
            doc_to_publish.add_related_article(
                doi=item['href'],
                ref_id=item['id'],
                related_type=item["related-article-type"],
            )

        doc_to_publish.publish_document()
        logging.info(_("Published {}").format(document_migration))
    except Exception as e:
        raise exceptions.PublishDocumentError(
            _("Unable to publish {} {}").format(pid, e)
        )

    try:
        document_migration.status = MS_PUBLISHED
        document_migration.save()
    except Exception as e:
        raise exceptions.PublishDocumentError(
            _("Unable to update document_migration status {} {}").format(
                pid, e
            )
        )
