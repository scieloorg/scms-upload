import json
import logging
import os
from datetime import datetime
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from packtools.sps.models.article_assets import ArticleAssets
from scielo_classic_website import classic_ws

from article.choices import AS_READ_TO_PUBLISH
from article.controller import (
    request_pid_v3_and_create_article as article_controller_request_pid_v3_and_create_article,
)
from article.models import ArticlePackages
from collection.models import Collection
from core.controller import parse_yyyymmdd
from django_celery_beat.models import CrontabSchedule, PeriodicTask
from issue.models import Issue, SciELOIssue
from journal.models import Journal, OfficialJournal, SciELOJournal
from xmlsps.xml_sps_lib import get_xml_items

from . import exceptions
from .choices import MS_IMPORTED, MS_PUBLISHED, MS_TO_IGNORE
from .models import (
    BodyAndBackFile,
    ClassicWebsiteConfiguration,
    GeneratedXMLFile,
    MigratedDocument,
    MigratedFile,
    MigratedIssue,
    MigratedJournal,
    MigrationFailure,
)

User = get_user_model()


def _get_classic_website_rel_path(file_path):
    if "htdocs" in file_path:
        return file_path[file_path.find("htdocs") :]
    if "base" in file_path:
        return file_path[file_path.find("base") :]


def schedule_migrations(user, collection_acron=None):
    try:
        task_parms = (
            ("title", "migrate_journal_records", 0, 2, 0),
            ("issue", "migrate_issue_records", 0, 7, 2),
        )
        if collection_acron:
            collections = Collection.objects.filter(acron=collection_acron).iterator()
        else:
            collections = Collection.objects.iterator()
        for collection in collections:
            collection_acron = collection.acron
            for (
                db_name,
                task,
                hours_after_now,
                minutes_after_now,
                priority,
            ) in task_parms:
                for mode in ("full", "incremental"):
                    # agenda tarefas para migrar title.mst e issue.mst
                    _schedule_db_migration(
                        collection_acron,
                        user,
                        db_name,
                        task,
                        "migrate",
                        hours_after_now,
                        minutes_after_now,
                        priority,
                        mode,
                    )

    except Exception as e:
        logging.exception(e)
        raise exceptions.ScheduleMigrationsError("Unable to start migration %s" % e)


def _schedule_db_migration(
    collection_acron,
    user,
    db_name,
    task,
    action,
    hours_after_now,
    minutes_after_now,
    priority,
    mode,
):
    """
    Agenda tarefas para migrar dados de title e issue
    """
    name = f"{collection_acron} | {db_name} | {action} | {mode}"
    kwargs = dict(
        collection_acron=collection_acron,
        username=user.username,
        force_update=(mode == "full"),
    )
    try:
        periodic_task = PeriodicTask.objects.get(name=name)
    except PeriodicTask.DoesNotExist:
        hours, minutes = sum_hours_and_minutes(hours_after_now, minutes_after_now)

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
    logging.info(_("Scheduled task: {}").format(name))


def schedule_documents_migration(collection_acron, user):
    """
    Agenda tarefas para migrar e publicar todos os documentos
    """
    for migrate_journal in MigratedJournal.journals(
        collection_acron=collection_acron,
        status=MS_IMPORTED,
    ):
        for migrated_issue in MigratedIssue.objects.filter(
            migrated_journal=migrate_journal,
        ):
            _schedule_issue_documents_migrations(user, migrated_issue)


def _schedule_issue_documents_migrations(user, migrated_issue):
    """
    Agenda tarefas para migrar e publicar todos os documentos
    """
    collection_acron = migrated_issue.migrated_journal.collection.acron
    journal_acron = migrated_issue.migrated_journal.acron
    scielo_issn = migrated_issue.migrated_journal.scielo_issn
    publication_year = migrated_issue.publication_year

    """
    Agenda tarefas para migrar e publicar um conjunto de documentos por:
        - ano
        - periódico
        - periódico e ano
    """
    logging.info(
        _("Schedule issue documents migration {} {} {} {}").format(
            collection_acron,
            journal_acron,
            scielo_issn,
            publication_year,
        )
    )

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
            modes = ("incremental",)

        for mode in modes:
            # agenda tarefa com variações de parâmetros para migrar os documentos
            _schedule_issue_documents_migration(
                collection_acron,
                journal_acron,
                scielo_issn,
                publication_year,
                user,
                group_id,
                mode,
                params,
                count,
            )


def _schedule_issue_documents_migration(
    collection_acron,
    journal_acron,
    scielo_issn,
    publication_year,
    user,
    group_id,
    mode,
    params,
    count,
):
    name = f"{collection_acron} | {group_id} | migrate | {mode}"
    task = "migrate_issue_files_and_document_records"

    kwargs = dict(
        collection_acron=collection_acron,
        username=user.username,
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
                periodic_task.priority = datetime.now().year - int(publication_year)

            # deixa habilitado para rodar frequentemente
            periodic_task.enabled = True

            # programado para rodar automaticamente 1 vez se o ano de
            # publicação não é o atual
            periodic_task.one_off = (
                publication_year and publication_year != datetime.now().year
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
            day_of_week=day_of_week or "*",
            hour=hour or "*",
            minute=minute or "*",
        )
    except Exception as e:
        logging.exception(e)
        raise exceptions.GetOrCreateCrontabScheduleError(
            _("Unable to get_or_create_crontab_schedule {} {} {} {} {}").format(
                day_of_week, hour, minute, type(e), e
            )
        )
    return crontab_schedule


def get_classic_website(collection_acron):
    config = ClassicWebsiteConfiguration.objects.get(collection__acron=collection_acron)
    return classic_ws.ClassicWebsite(
        bases_path=os.path.dirname(config.bases_work_path),
        bases_work_path=config.bases_work_path,
        bases_translation_path=config.bases_translation_path,
        bases_pdf_path=config.bases_pdf_path,
        bases_xml_path=config.bases_xml_path,
        htdocs_img_revistas_path=config.htdocs_img_revistas_path,
        serial_path=config.serial_path,
        cisis_path=config.cisis_path,
        title_path=config.title_path,
        issue_path=config.issue_path,
    )


def migrate_journal_records(
    user,
    collection_acron,
    force_update=False,
):
    collection = Collection.get_or_create(collection_acron)
    classic_website = get_classic_website(collection.acron)
    for scielo_issn, journal_data in classic_website.get_journals_pids_and_records():

        migrated_journal = import_data_from_title_database(
            user,
            collection,
            scielo_issn,
            journal_data[0],
            force_update,
        )


def import_data_from_title_database(
    user,
    collection,
    scielo_issn,
    journal_data,
    classic_website_journal,
    force_update=False,
):
    """
    Create/update JournalMigration
    """
    try:
        # obtém classic website journal
        classic_website_journal = classic_ws.Journal(journal_data)

        year, month, day = parse_yyyymmdd(classic_website_journal.first_year)
        official_journal = OfficialJournal.create_or_update(
            issn_electronic=classic_website_journal.electronic_issn,
            issn_print=classic_website_journal.print_issn,
            title=classic_website_journal.title,
            title_iso=classic_website_journal.title_iso,
            foundation_year=year,
            user=user,
        )
        logging.info(f"Got official_journal {official_journal}")

        journal = Journal.create_or_update(
            official_journal=official_journal,
        )
        logging.info(f"Got journal {journal}")
        # TODO
        # for publisher_name in classic_website_journal.raw_publisher_names:
        #     journal.add_publisher(user, publisher_name)

        scielo_journal = SciELOJournal.create_or_update(
            collection,
            scielo_issn=scielo_issn,
            creator=user,
            official_journal=official_journal,
            acron=classic_website_journal.acronym,
            title=classic_website_journal.title,
            availability_status=classic_website_journal.current_status,
        )
        logging.info(f"Got scielo_journal {scielo_journal}")

        migrated_journal = MigratedJournal.create_or_update(
            scielo_journal=scielo_journal,
            creator=user,
            isis_created_date=classic_website_journal.isis_created_date,
            isis_updated_date=classic_website_journal.isis_updated_date,
            data=journal_data,
            status=MS_IMPORTED,
            force_update=force_update,
        )
        return migrated_journal
    except Exception as e:
        logging.exception(e)
        message = _("Unable to migrate journal {} {}").format(
            collection.acron, scielo_issn
        )
        MigrationFailure.create(
            collection_acron=collection.acron,
            migrated_item_name="journal",
            migrated_item_id=scielo_issn,
            message=message,
            action_name="migrate",
            e=e,
            creator=user,
        )


def migrate_issue_records(
    user,
    collection_acron,
    force_update=False,
):
    collection = Collection.get_or_create(acron=collection_acron)
    classic_website = get_classic_website(collection_acron)
    for issue_pid, issue_data in classic_website.get_issues_pids_and_records():
        migrated_issue = import_data_from_issue_database(
            user=user,
            collection=collection,
            scielo_issn=issue_pid[:9],
            issue_pid=issue_pid,
            issue_data=issue_data[0],
            force_update=force_update,
        )
    schedule_documents_migration(collection_acron, user)


def import_data_from_issue_database(
    user,
    collection,
    scielo_issn,
    issue_pid,
    issue_data,
    force_update=False,
):
    """
    Create/update IssueMigration
    """
    try:
        logging.info(
            "Import data from database issue {} {} {}".format(
                collection, scielo_issn, issue_pid
            )
        )

        classic_website_issue = classic_ws.Issue(issue_data)

        migrated_journal = MigratedJournal.get(
            collection=collection, scielo_issn=scielo_issn
        )
        issue = Issue.get_or_create(
            official_journal=migrated_journal.scielo_journal.official_journal,
            publication_year=classic_website_issue.publication_year,
            volume=classic_website_issue.volume,
            number=classic_website_issue.number,
            supplement=classic_website_issue.supplement,
            user=user,
        )
        scielo_issue = SciELOIssue.create_or_update(
            scielo_journal=migrated_journal.scielo_journal,
            user=user,
            issue_pid=issue_pid,
            issue_folder=classic_website_issue.issue_label,
            official_issue=issue,
        )

        migrated_issue = MigratedIssue.create_or_update(
            scielo_issue=scielo_issue,
            migrated_journal=migrated_journal,
            creator=user,
            isis_created_date=classic_website_issue.isis_created_date,
            isis_updated_date=classic_website_issue.isis_updated_date,
            status=MS_IMPORTED,
            data=issue_data,
            force_update=force_update,
        )
        logging.info(migrated_issue.status)
        return migrated_issue
    except Exception as e:
        logging.exception(e)
        message = _("Unable to migrate issue {} {}").format(collection.acron, issue_pid)
        MigrationFailure.create(
            collection_acron=collection.acron,
            migrated_item_name="issue",
            migrated_item_id=issue_pid,
            message=message,
            action_name="migrate",
            e=e,
            creator=user,
        )


def migrate_issue_files_and_document_records(
    user,
    collection_acron,
    scielo_issn=None,
    publication_year=None,
    force_update=False,
):
    params = {"migrated_journal__scielo_journal__collection__acron": collection_acron}
    if scielo_issn:
        params["migrated_journal__scielo_journal__scielo_issn"] = scielo_issn
    if publication_year:
        params["scielo_issue__official_issue__publication_year"] = publication_year

    classic_website = get_classic_website(collection_acron)

    # Melhor importar todos os arquivos e depois tratar da carga
    # dos metadados, e geração de XML, pois
    # há casos que os HTML mencionam arquivos de pastas diferentes
    # da sua pasta do fascículo
    items = MigratedIssue.objects.filter(
        Q(status=MS_PUBLISHED) | Q(status=MS_IMPORTED),
        **params,
    )
    for migrated_issue in items.iterator():
        logging.info(migrated_issue)

        issue_folder = migrated_issue.issue_folder
        issue_pid = migrated_issue.issue_pid

        import_issue_files(
            migrated_issue=migrated_issue,
            classic_website=classic_website,
            force_update=force_update,
            user=user,
        )
        # migra os documentos da base de dados `source_file_path`
        # que não contém necessariamente os dados de só 1 fascículo
        migrate_document_records(
            user,
            collection_acron,
            migrated_issue,
            classic_website,
            force_update,
        )


def migrate_one_issue_files_and_document_records(
    user,
    migrated_issue_id,
    collection_acron,
    scielo_issn=None,
    publication_year=None,
    force_update=False,
):

    migrated_issue = MigratedIssue.objects.get(id=migrated_issue_id)
    logging.info(migrated_issue)

    classic_website = get_classic_website(collection_acron)

    # Melhor importar todos os arquivos e depois tratar da carga
    # dos metadados, e geração de XML, pois
    # há casos que os HTML mencionam arquivos de pastas diferentes
    # da sua pasta do fascículo
    issue_folder = migrated_issue.issue_folder
    issue_pid = migrated_issue.issue_pid

    import_issue_files(
        migrated_issue=migrated_issue,
        classic_website=classic_website,
        force_update=force_update,
        user=user,
    )
    # migra os documentos da base de dados `source_file_path`
    # que não contém necessariamente os dados de só 1 fascículo
    migrate_document_records(
        user,
        collection_acron,
        migrated_issue,
        classic_website,
        force_update,
    )


def import_issue_files(
    migrated_issue,
    classic_website,
    force_update,
    user,
):
    """135
    Migra os arquivos do fascículo (pdf, img, xml ou html)
    """
    collection_acron = migrated_issue.migrated_journal.collection.acron
    journal_acron = migrated_issue.migrated_journal.acron
    issue_folder = migrated_issue.issue_folder

    logging.info(f"Import issue files {migrated_issue}")

    classic_issue_files = classic_website.get_issue_files(
        journal_acron,
        issue_folder,
    )
    for file in classic_issue_files:
        """
        {"type": "pdf", "key": name, "path": path, "name": basename, "lang": lang}
        {"type": "xml", "key": name, "path": path, "name": basename, }
        {"type": "html", "key": name, "path": path, "name": basename, "lang": lang, "part": label}
        {"type": "asset", "path": item, "name": os.path.basename(item)}
        """
        try:
            logging.info(file)
            original_path = _get_classic_website_rel_path(file["path"])
            category = check_category(file)

            pkg_name = file.get("key")
            migrated_file = MigratedFile.create_or_update(
                migrated_issue=migrated_issue,
                original_path=original_path,
                source_path=file["path"],
                category=category,
                lang=file.get("lang"),
                part=file.get("part"),
                pkg_name=pkg_name,
                creator=user,
            )
        except Exception as e:
            logging.exception(e)
            message = _("Unable to migrate issue files {} {} {}").format(
                collection_acron, journal_acron, issue_folder
            )
            MigrationFailure.create(
                collection_acron=collection_acron,
                migrated_item_name="issue files",
                migrated_item_id=f"{journal_acron} {issue_folder} {file}",
                message=message,
                action_name="migrate",
                e=e,
                creator=user,
            )


def check_category(file):
    if file["type"] == "pdf":
        logging.info(file)
        check = file["name"]
        try:
            check = check.replace(file["lang"] + "_", "")
        except (KeyError, TypeError):
            pass
        try:
            check = check.replace(file["key"], "")
        except (KeyError, TypeError):
            pass
        logging.info(check)
        if check == "":
            return "rendition"
        return "supplmat"
    return file["type"]


def migrate_document_records(
    user,
    collection_acron,
    migrated_issue,
    classic_website,
    force_update=False,
):
    """
    Importa os registros presentes na base de dados `source_file_path`
    Importa os arquivos dos documentos (xml, pdf, html, imagens)
    Publica os artigos no site
    """

    migrated_journal = migrated_issue.migrated_journal
    journal_acron = migrated_journal.acron
    issue_folder = migrated_issue.issue_folder
    issue_pid = migrated_issue.issue_pid

    journal_issue_and_doc_data = {
        "title": migrated_journal.data,
        "issue": migrated_issue.data,
    }

    # obtém registros da base "artigo" que não necessariamente é só
    # do fascículo de migrated_issue
    # possivelmente source_file pode conter registros de outros fascículos
    # se source_file for acrônimo
    logging.info(
        "Importing documents records {} {}".format(
            journal_acron,
            issue_folder,
        )
    )
    for doc_id, doc_records in classic_website.get_documents_pids_and_records(
        journal_acron,
        issue_folder,
        issue_pid,
    ):
        try:
            logging.info(_("Get {}").format(doc_id))
            if len(doc_records) == 1:
                # é possível que em source_file_path exista registro tipo i
                journal_issue_and_doc_data["issue"] = doc_records[0]
                continue

            journal_issue_and_doc_data["article"] = doc_records
            classic_ws_doc = classic_ws.Document(journal_issue_and_doc_data)

            migrated_document = migrate_document(
                collection_acron,
                migrated_issue,
                issue_pid,
                user,
                classic_ws_doc=classic_ws_doc,
                journal_issue_and_doc_data=journal_issue_and_doc_data,
                force_update=force_update,
            )
            _generate_xml_from_html(classic_ws_doc, migrated_document, user)

        except Exception as e:
            logging.exception(e)
            message = _("Unable to migrate issue documents {} {} {} {}").format(
                collection_acron, journal_acron, issue_folder, doc_id
            )
            MigrationFailure.create(
                collection_acron=collection_acron,
                migrated_item_name="document",
                migrated_item_id=f"{journal_acron} {issue_folder} {doc_id}",
                message=message,
                action_name="migrate",
                e=e,
                creator=user,
            )


def migrate_document(
    collection_acron,
    migrated_issue,
    issue_pid,
    user,
    classic_ws_doc,
    journal_issue_and_doc_data,
    force_update,
):
    try:
        # instancia Document com registros de title, issue e artigo
        pid = classic_ws_doc.scielo_pid_v2 or (
            "S" + issue_pid + classic_ws_doc.order.zfill(5)
        )
        pkg_name = classic_ws_doc.filename_without_extension

        if classic_ws_doc.scielo_pid_v2 != pid:
            classic_ws_doc.scielo_pid_v2 = pid

        return MigratedDocument.create_or_update(
            migrated_issue=migrated_issue,
            pid=pid,
            pkg_name=pkg_name,
            aop_pid=classic_ws_doc.aop_pid,
            pid_v3=classic_ws_doc.scielo_pid_v3,
            creator=user,
            isis_created_date=classic_ws_doc.isis_created_date,
            isis_updated_date=classic_ws_doc.isis_updated_date,
            data=journal_issue_and_doc_data,
            status=MS_IMPORTED,
            force_update=force_update,
        )
    except Exception as e:
        logging.exception(e)
        message = _("Unable to migrate document {} {}").format(collection_acron, pid)
        MigrationFailure.create(
            collection_acron=collection_acron,
            migrated_item_name="document",
            migrated_item_id=pid,
            message=message,
            action_name="migrate",
            e=e,
            creator=user,
        )


def _generate_xml_from_html(classic_ws_doc, migrated_document, user):
    html_texts = migrated_document.html_texts
    if not html_texts:
        return

    migrated_issue = migrated_document.migrated_issue
    collection_acron = migrated_issue.migrated_journal.collection.acron
    pkg_name = migrated_document.pkg_name

    try:
        # obtém um XML com body e back a partir dos arquivos HTML / traduções
        classic_ws_doc.generate_body_and_back_from_html(html_texts)
    except Exception as e:
        logging.exception(e)
        message = _("Unable to generate body and back from HTML {} {}").format(
            collection_acron, migrated_document.pid
        )
        MigrationFailure.create(
            collection_acron=collection_acron,
            migrated_item_name="document",
            migrated_item_id=migrated_document.pid,
            message=message,
            action_name="xml-body-and-back",
            e=e,
            creator=user,
        )
        return

    for i, xml_body_and_back in enumerate(classic_ws_doc.xml_body_and_back):
        try:
            # para cada versão de body/back, guarda a versão de body/back
            migrated_file = BodyAndBackFile.create_or_update(
                migrated_issue=migrated_issue,
                pkg_name=pkg_name,
                creator=user,
                file_content=xml_body_and_back,
                version=i,
            )
            # para cada versão de body/back, guarda uma versão de XML
            xml_content = classic_ws_doc.generate_full_xml(xml_body_and_back)
            migrated_file = GeneratedXMLFile.create_or_update(
                migrated_issue=migrated_issue,
                pkg_name=pkg_name,
                creator=user,
                file_content=xml_content,
                version=i,
            )
        except Exception as e:
            logging.exception(e)
            message = _("Unable to generate XML from HTML {} {}").format(
                collection_acron, migrated_document.pid
            )
            MigrationFailure.create(
                collection_acron=collection_acron,
                migrated_item_name="document",
                migrated_item_id=migrated_document.pid,
                message=message,
                action_name="xml-to-html",
                e=e,
                creator=user,
            )


def create_articles(
    user,
    collection_acron=None,
    from_date=None,
    force_update=None,
):
    from_date = from_date or "0"
    params = {}
    if collection_acron:
        params["migrated_issue__migrated_journal__collection__acron"] = collection_acron
    params = {}
    if from_date:
        params["created__gte"] = from_date

    for migrated_document in MigratedDocument.objects.filter(
        **params,
    ).iterator():
        logging.info(migrate_document)
        dm = DocumentMigration(migrated_document, user)
        dm.request_pid_v3()
        dm.build_sps_package()
        dm.publish_package(minio_push_file_content)


def _get_xml(path):
    for item in get_xml_items(path):
        return item


def minio_push_file_content(**kwargs):
    return {"uri": "https://localhost"}


class DocumentMigration:
    def __init__(self, migrated_document, user):
        self.migrated_document = migrated_document
        self.migrated_issue = migrated_document.migrated_issue
        self.collection_acron = (
            migrated_document.migrated_issue.migrated_journal.collection.acron
        )
        self.user = user

        migrated_xml = migrated_document.migrated_xml
        self.xml_name = migrated_xml["name"]

        xml = _get_xml(migrated_xml["path"])
        self.xml_with_pre = xml["xml_with_pre"]
        self.article_pkgs = None
        self._set_sps_pkg_name()

    def register_failure(
        self, e, migrated_item_name, migrated_item_id, message, action_name
    ):
        logging.info(message)
        logging.exception(e)
        MigrationFailure.create(
            collection_acron=self.collection_acron,
            migrated_item_name=migrated_item_name,
            migrated_item_id=migrated_item_id,
            message=message,
            action_name=action_name,
            e=e,
            creator=self.user,
        )

    def request_pid_v3(self):
        try:
            logging.info(f"Solicita PID v3 para {self.migrated_document}")
            self.xml_with_pre.v2 = self.migrated_document.pid

            # solicita pid v3 e obtém o article criado
            response = article_controller_request_pid_v3_and_create_article(
                self.xml_with_pre, self.xml_name, self.user, "migration"
            )
            try:
                # cria / obtém article
                logging.info(f"Cria / obtém article para {self.migrated_document}")
                self.migrated_document.sps_pkg_name = self.sps_pkg_name
                self.migrated_document.article = response["article"]
                self.migrated_document.article.status = AS_READ_TO_PUBLISH
                self.migrated_document.article.issue = (
                    self.migrated_issue.scielo_issue.official_issue
                )
                self.migrated_document.article.journal = Journal.get(
                    official_journal=self.migrated_issue.migrated_journal.scielo_journal.official_journal
                )
                self.migrated_document.article.save()
                self.migrated_document.save()

                logging.info(f"Criado / obtido article para {self.migrated_document}")
                self.article_pkgs = ArticlePackages.get_or_create(
                    article=self.migrated_document.article,
                    sps_pkg_name=self.sps_pkg_name,
                    creator=self.user,
                )
            except KeyError as e:
                logging.info("Falhou cria / obtém article")
                self.register_failure(
                    e,
                    migrated_item_name="document",
                    migrated_item_id=self.migrated_document.pid,
                    message=str(response),
                    action_name="request-pid-v3",
                )
                return
        except Exception as e:
            message = _(
                "Unable to get or create article and xml with pid v3 {} {}"
            ).format(self.collection_acron, self.migrated_document.pid)
            self.register_failure(
                e,
                migrated_item_name="document",
                migrated_item_id=self.migrated_document.pid,
                message=message,
                action_name="request-pid-v3",
            )

    def _set_sps_pkg_name(self):
        issue = self.migrated_issue.scielo_issue.official_issue
        journal = issue.official_journal

        suppl = issue.supplement
        try:
            if suppl and int(suppl) == 0:
                suppl = "suppl"
        except TypeError:
            pass

        parts = [
            journal.issn_electronic or journal.issn_print or journal.issnl,
            self.migrated_issue.migrated_journal.acron,
            issue.volume,
            issue.number and issue.number.zfill(2),
            suppl,
            self._get_pkg_name_suffix() or self.migrated_document.pkg_name,
        ]
        self.migrated_document.sps_pkg_name = "-".join([part for part in parts if part])
        self.migrated_document.save()
        self.sps_pkg_name = self.migrated_document.sps_pkg_name

    def _get_pkg_name_suffix(self):
        xml_with_pre = self.xml_with_pre
        if xml_with_pre.is_aop and xml_with_pre.main_doi:
            doi = xml_with_pre.main_doi
            if "/" in doi:
                doi = doi[doi.find("/") + 1 :]
            return doi.replace(".", "-")
        if xml_with_pre.elocation_id:
            return xml_with_pre.elocation_id
        if xml_with_pre.fpage:
            try:
                fpage = int(xml_with_pre.fpage)
            except TypeError:
                pass
            if fpage != 0:
                return xml_with_pre.fpage + (xml_with_pre.fpage_seq or "")

    def build_sps_package(self):
        logging.info(f"Build SPS Package {self.migrated_document}")
        try:
            # gera nome de pacote padrão SPS ISSN-ACRON-VOL-NUM-SUPPL-ARTICLE
            with TemporaryDirectory() as tmpdirname:
                logging.info("TemporaryDirectory %s" % tmpdirname)
                temp_zip_file_path = os.path.join(
                    tmpdirname, f"{self.migrated_document.pkg_name}.zip"
                )

                with ZipFile(temp_zip_file_path, "w") as zf:
                    # adiciona XML em zip
                    self._build_sps_package_add_xml(zf)

                    # add renditions (pdf) to zip
                    self._build_sps_package_add_renditions(zf)

                    # A partir do XML, obtém os nomes dos arquivos dos ativos digitais
                    sps_article_assets = ArticleAssets(self.xml_with_pre.xmltree)
                    self._build_sps_package_replace_asset_href(sps_article_assets)
                    self._build_sps_package_add_assets(
                        zf, sps_article_assets.article_assets
                    )

                with open(temp_zip_file_path, "rb") as fp:
                    # guarda o pacote compactado
                    self.article_pkgs.add_sps_package_file(
                        filename=self.sps_pkg_name + ".zip",
                        content=fp.read(),
                        user=self.user,
                    )
        except Exception as e:
            message = _("Unable to build sps package {} {}").format(
                self.collection_acron, self.migrated_document.pid
            )
            self.register_failure(
                e,
                migrated_item_name="zip",
                migrated_item_id=self.migrated_document.pid,
                message=message,
                action_name="build-sps-package",
            )

    def _build_sps_package_add_xml(self, zf):
        try:
            sps_xml_name = self.sps_pkg_name + ".xml"
            zf.writestr(self.sps_pkg_name + ".xml", self.xml_with_pre.tostring())
            self.article_pkgs.add_component(
                sps_filename=sps_xml_name,
                user=self.user,
                category="xml",
            )
        except Exception as e:
            message = _("Unable to _build_sps_package_add_xml {} {} {}").format(
                self.collection_acron, self.sps_pkg_name, sps_xml_name
            )
            self.register_failure(
                e,
                migrated_item_name="xml",
                migrated_item_id=sps_xml_name,
                message=message,
                action_name="build-sps-package",
            )

    def _build_sps_package_add_renditions(self, zf):
        # grava renditions (pdf) em zip
        for rendition_file in MigratedFile.objects.filter(
            migrated_issue=self.migrated_issue,
            pkg_name=self.migrated_document.pkg_name,
            category="rendition",
        ):
            try:
                logging.info(f"Add rendition {rendition_file.original_path}")
                if rendition_file.lang:
                    sps_filename = f"{self.sps_pkg_name}-{rendition_file.lang}.pdf"
                else:
                    sps_filename = f"{self.sps_pkg_name}.pdf"
                zf.write(rendition_file.file.path, arcname=sps_filename)
                self.article_pkgs.add_component(
                    sps_filename=sps_filename,
                    user=self.user,
                    category="rendition",
                    lang=rendition_file.lang,
                    collection_acron=self.collection_acron,
                    former_href=rendition_file.former_href,
                )
            except Exception as e:
                message = _(
                    "Unable to _build_sps_package_add_renditions {} {} {}"
                ).format(self.collection_acron, self.sps_pkg_name, rendition_file)
                self.register_failure(
                    e,
                    migrated_item_name="rendition",
                    migrated_item_id=str(rendition_file),
                    message=message,
                    action_name="build-sps-package",
                )

    def _build_sps_package_replace_asset_href(self, sps_article_assets):
        alternatives = {}
        for xml_graphic in sps_article_assets.article_assets:
            try:
                asset_file = MigratedFile.get(
                    migrated_issue=self.migrated_issue,
                    original_name=xml_graphic.name,
                )
            except MigratedFile.DoesNotExist as e:
                name, ext = os.path.splitext(xml_graphic.name)
                try:
                    alternative = MigratedFile.get(
                        migrated_issue=self.migrated_issue,
                        original_name=name,
                    )
                except MigratedFile.DoesNotExist as e:
                    alternative = MigratedFile.objects.filter(
                        migrated_issue=self.migrated_issue,
                        original_name__startswith=name + ".",
                    ).first()
                if alternative:
                    alternatives[xml_graphic.name] = alternative.original_name
        sps_article_assets.replace_names(alternatives)

    def _build_sps_package_add_assets(self, zf, article_assets):
        for xml_graphic in article_assets:
            try:
                asset_file = MigratedFile.get(
                    migrated_issue=self.migrated_issue,
                    original_name=xml_graphic.name,
                )
            except MigratedFile.DoesNotExist as e:
                message = _("Unable to _build_sps_package_add_assets {} {} {}").format(
                    self.collection_acron, self.sps_pkg_name, xml_graphic.name
                )
                self.register_failure(
                    e=e,
                    migrated_item_name="asset",
                    migrated_item_id=xml_graphic.name,
                    message=message,
                    action_name="build-sps-package",
                )
                continue
            else:
                self._build_sps_package_add_asset(zf, asset_file, xml_graphic)

    def _build_sps_package_add_asset(self, zf, asset_file, xml_graphic):
        try:
            logging.info(f"Add asset {asset_file.original_path}")
            # obtém o nome do arquivo no padrão sps
            sps_filename = xml_graphic.name_canonical(self.sps_pkg_name)
            logging.info(sps_filename)

            # adiciona componente ao pacote
            self.article_pkgs.add_component(
                sps_filename=sps_filename,
                user=self.user,
                category="asset",
                collection_acron=self.collection_acron,
                former_href=asset_file.original_href,
            )
            # adiciona o arquivo no zip
            zf.write(asset_file.file.path, arcname=sps_filename)
        except Exception as e:
            message = _("Unable to _build_sps_package_add_asset {} {} {}").format(
                self.collection_acron, self.sps_pkg_name, asset_file.original_name
            )
            self.register_failure(
                e=e,
                migrated_item_name="asset",
                migrated_item_id=asset_file.original_name,
                message=message,
                action_name="build-sps-package",
            )

    def publish_package(self, minio_push_file_content):
        responses = self.article_pkgs.publish_package(
            minio_push_file_content,
            self.user,
        )
        for response in responses:
            try:
                uri = response["uri"]
            except KeyError:
                self.register_failure(**response)
