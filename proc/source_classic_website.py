"""
Módulo responsável pela migração de dados do site clássico e processamento de PIDs.
"""

import logging
import sys

from django.db.models import Max

from migration.models import MigratedData, MigratedFile, modified_date
from migration import controller
from proc.models import IssueProc, JournalProc
from tracker.models import UnexpectedEvent


def create_or_update_migrated_journal(
    user,
    collection,
    classic_website,
    force_update,
):
    """
    Cria ou atualiza journals migrados do site clássico (base title).
    """
    register_id_file_records(
        user,
        collection,
        classic_website.classic_website_paths.title_path,
        classic_website.get_journals_id_file,
        JournalProc,
        "journal",
        force_update,
    )


def create_or_update_migrated_issue(
    user,
    collection,
    classic_website,
    force_update,
):
    """
    Cria ou atualiza issues migrados do site clássico (base issue).
    """
    register_id_file_records(
        user,
        collection,
        classic_website.classic_website_paths.issue_path,
        classic_website.get_issues_id_file,
        IssueProc,
        "issue",
        force_update,
    )


def register_id_file_records(
    user, collection, id_file_path, get_id_file, proc_class, content_type, force_update
):
    """
    Registra (proc_class.register_classic_website_data) os registros do
    arquivo .id somente se o arquivo mudou desde a última leitura completa
    (ou se force_update).

    Sem force_update, registra somente os registros novos de title.id ou issue.id,
    usando os campos de atualização (v941 em title, v091 em issue)
    igual ou posterior à mais recente já registrada para a coleção. 
    Só os registros novos são convertidos para JSON.

    O arquivo só é marcado como lido se for lido completamente; assim, uma
    leitura interrompida é refeita na próxima execução. Falhas em registros
    individuais não impedem a marcação: ficam registradas pelo próprio
    proc (BLOCKED) ou em UnexpectedEvent.
    """
    file_datetime_iso = modified_date(id_file_path)
    has_changes = MigratedFile.has_changes(
        collection, id_file_path, force_update
    )
    if not has_changes:
        logging.info(f"skip reading {id_file_path}: records already read")
        return

    last_run_date = None
    if not force_update:
        # Max ignora registros sem data (order_by("-...") os poria primeiro
        # no Postgres e anularia o filtro)
        last_run_date = MigratedData.objects.filter(
            collection=collection,
            content_type=content_type,
        ).aggregate(d=Max("isis_updated_date"))["d"]

    try:
        # items() não converte os registros para JSON; item.date não depende
        # da conversão, que só ocorre para os registrados (item.data)
        for item in get_id_file().items(since=last_run_date):
            pid = item.pid
            try:
                proc_class.register_classic_website_data(
                    user, collection, pid, item.data, content_type, force_update
                )
            except Exception as e:
                exc_type, exc_value, exc_traceback = sys.exc_info()
                UnexpectedEvent.create(
                    action="proc.source_classic_website.register_id_file_records",
                    item=pid,
                    e=e,
                    exc_traceback=exc_traceback,
                    detail={
                        "collection": collection.acron,
                        "id_file_path": id_file_path,
                        "force_update": force_update,
                    },
                )
    except Exception as e:
        # leitura incompleta do arquivo .id: não marca como lido
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            action="proc.source_classic_website.register_id_file_records",
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "collection": collection.acron,
                "id_file_path": id_file_path,
                "force_update": force_update,
                "message": "incomplete reading; the file will be read again in the next execution",
            },
        )
        return

    MigratedFile.create_or_update(
        user=user,
        collection=collection,
        original_path=id_file_path,
        source_path=id_file_path,
        component_type="id_file",
        force_update=force_update,
        file_datetime_iso=file_datetime_iso,
    )


def migrate_journal(
    user,
    journal_proc,
    force_update,
):
    """
    Executa a migração de um journal específico do site clássico.
    """
    try:
        event = None
        detail = {}
        detail = {
            "journal_proc": str(journal_proc),
            "force_update": force_update,
        }
        event = journal_proc.start(user, "create or update journal")

        # cria ou atualiza Journal e atualiza journal_proc
        completed = journal_proc.create_or_update_item(
            user, force_update, controller.create_or_update_journal
        )
        event.finish(user, completed=bool(completed), detail=detail)

    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        if event:
            event.finish(
                user,
                completed=False,
                detail=detail,
                exception=e,
                exc_traceback=exc_traceback,
            )
            return

        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "proc.sources.classic_website.migrate_journal",
                "user_id": user.id,
                "username": user.username,
                "collection": journal_proc.collection.acron,
                "pid": journal_proc.pid,
                "force_update": force_update,
            },
        )


# def create_or_update_journal_acron_id_file(
#     user, collection, journal_filter, force_update=None
# ):
#     """
#     Cria ou atualiza arquivos de ID baseados em acrônimos de journals.
#     """
#     items = JournalProc.objects.select_related(
#         "collection",
#         "journal",
#     ).filter(
#         collection=collection,
#         **journal_filter,
#     )
#     logging.info(f"create_or_update_journal_acron_id_file - JournalProc params: collection={collection.acron}, journal_filter={journal_filter} - {items.count()} items found")
#     for journal_proc in items:
#         logging.info(f"create_or_update_journal_acron_id_file - JournalProc {journal_proc}")
#         controller.import_journal_acron_id_records(
#             user,
#             journal_proc,
#             force_update=force_update,
#         )


def migrate_issue(user, issue_proc, force_update):
    """
    Executa a migração de um issue específico do site clássico.
    """
    try:
        event = None
        detail = {}
        detail = {
            "issue_proc": str(issue_proc),
            "force_update": force_update,
        }
        event = issue_proc.start(user, "create or update issue")
        collection = issue_proc.collection
        issue_proc.create_or_update_item(
            user,
            force_update,
            controller.create_or_update_issue,
            JournalProc=JournalProc,
        )
        event.finish(user, completed=True, detail=detail)
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        if event:
            event.finish(
                user,
                completed=False,
                detail=detail,
                exception=e,
                exc_traceback=exc_traceback,
            )
            return

        UnexpectedEvent.create(
            action="proc.sources.classic_website.migrate_issue",
            item=issue_proc.pid,
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "issue_proc": str(issue_proc),
                "force_update": force_update,
            },
        )


# def migrate_document_records(
#     user,
#     collection_acron=None,
#     journal_acron=None,
#     issue_folder=None,
#     publication_year=None,
#     status=None,
#     force_update=None,
#     skip_migrate_pending_document_records=None,
# ):
#     """
#     Executa a migração de registros de documentos do site clássico.
#     """
#     params = {}
#     if collection_acron:
#         params["collection__acron"] = collection_acron
#     if journal_acron:
#         params["journal_proc__acron"] = journal_acron
#     if issue_folder:
#         params["issue_folder"] = str(issue_folder)
#     if publication_year:
#         params["issue__publication_year"] = str(publication_year)
#     if status:
#         params["docs_status__in"] = tracker_choices.get_valid_status(
#             status, force_update
#         )

#     logging.info(f"migrate_document_records - IssueProc params: {params}")
#     for issue_proc in IssueProc.objects.select_related(
#         "collection",
#         "journal_proc",
#         "issue",
#     ).filter(**params):
#         logging.info(f"migrate_document_records - IssueProc {issue_proc}")
#         issue_proc.migrate_document_records(user, force_update)
#         ArticleProc.mark_for_reprocessing(issue_proc)

#     # if skip_migrate_pending_document_records:
#     #     return

#     # IssueProc.migrate_pending_document_records(
#     #     user,
#     #     collection_acron,
#     #     journal_acron,
#     #     issue_folder,
#     #     publication_year,
#     # )


# def migrate_document_files(
#     user,
#     collection_acron=None,
#     journal_acron=None,
#     issue_folder=None,
#     publication_year=None,
#     status=None,
#     force_update=None,
# ):
#     """
#     Obtém arquivos do site clássico para processamento.
#     """
#     params = {}
#     if collection_acron:
#         params["collection__acron"] = collection_acron
#     if journal_acron:
#         params["journal_proc__acron"] = journal_acron
#     if issue_folder:
#         params["issue_folder"] = str(issue_folder)
#     if publication_year:
#         params["issue__publication_year"] = str(publication_year)
#     if status:
#         params["files_status__in"] = tracker_choices.get_valid_status(
#             status, force_update
#         )
#     items = IssueProc.objects.select_related(
#         "collection",
#         "journal_proc",
#         "issue",
#     ).filter(**params)
#     logging.info(f"migrate_document_files - IssueProc params: {params} - {items.count()} items found")
#     for issue_proc in items:
#         logging.info(f"migrate_document_files - IssueProc {issue_proc}")
#         issue_proc.migrate_document_files(
#             user, force_update, controller.migrate_issue_files
#         )
#         ArticleProc.mark_for_reprocessing(issue_proc)
