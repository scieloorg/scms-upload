"""
Módulo responsável pela migração de dados do site clássico e processamento de PIDs.
"""

import logging
import sys

from migration import controller
from proc.models import ArticleProc, IssueProc, JournalProc
from tracker import choices as tracker_choices
from tracker.models import UnexpectedEvent


def create_or_update_migrated_journal(
    user,
    collection,
    classic_website,
    force_update,
):
    """
    Cria ou atualiza journals migrados do site clássico.
    """
    has_changes = controller.id_file_has_changes(
        user,
        collection,
        classic_website.classic_website_paths.title_path,
        force_update,
    )
    if not has_changes:
        logging.info(f"skip reading {classic_website.classic_website_paths.title_path}")
        return

    for (
        scielo_issn,
        journal_data,
    ) in classic_website.get_journals_pids_and_records():
        # para cada registro da base de dados "title",
        # cria um registro MigratedData (source="journal")
        try:
            JournalProc.register_classic_website_data(
                user,
                collection,
                scielo_issn,
                journal_data[0],
                "journal",
                force_update,
            )

        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            UnexpectedEvent.create(
                e=e,
                exc_traceback=exc_traceback,
                detail={
                    "task": "proc.sources.classic_website.create_or_update_migrated_journal",
                    "user_id": user.id,
                    "username": user.username,
                    "collection": collection.acron,
                    "pid": scielo_issn,
                    "force_update": force_update,
                },
            )


def create_or_update_migrated_issue(
    user,
    collection,
    classic_website,
    force_update,
):
    """
    Cria ou atualiza issues migrados do site clássico.
    """
    has_changes = controller.id_file_has_changes(
        user,
        collection,
        classic_website.classic_website_paths.issue_path,
        force_update,
    )

    if not has_changes:
        logging.info(f"skip reading {classic_website.classic_website_paths.issue_path}")
        return

    for (
        pid,
        issue_data,
    ) in classic_website.get_issues_pids_and_records():
        # para cada registro da base de dados "issue",
        # cria um registro MigratedData (source="issue")
        try:
            IssueProc.register_classic_website_data(
                user,
                collection,
                pid,
                issue_data[0],
                "issue",
                force_update,
            )

        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            UnexpectedEvent.create(
                e=e,
                exc_traceback=exc_traceback,
                detail={
                    "task": "proc.sources.classic_website.create_or_update_migrated_issue",
                    "user_id": user.id,
                    "username": user.username,
                    "collection": collection.acron,
                    "pid": pid,
                    "force_update": force_update,
                },
            )


def create_collection_procs_from_pid_list(
    user,
    collection,
    pid_list_path,
    force_update,
):
    """
    Cria procs de collection baseado numa lista de PIDs.
    Processa PIDs de artigos, issues e journals de forma hierárquica.
    """
    has_changes = controller.id_file_has_changes(
        user,
        collection,
        pid_list_path,
        force_update,
    )
    if not has_changes:
        logging.info(f"skip reading {pid_list_path}")
        return

    try:
        pid = None
        journal_pids = set()
        issue_pids = set()
        with open(pid_list_path, "r") as fp:
            pids = fp.readlines()

        for pid in pids:
            pid = pid.strip() or ""
            if not len(pid) == 23:
                continue

            # Registra PID do artigo
            ArticleProc.register_pid(
                user,
                collection,
                pid,
                force_update=False,
            )

            # Extrai e registra PID do issue
            issue_pid = pid[1:-5]
            if issue_pid not in issue_pids:
                issue_pids.add(issue_pid)
                IssueProc.register_pid(
                    user,
                    collection,
                    issue_pid,
                    force_update=False,
                )

                # Extrai e registra PID do journal
                journal_pid = pid[1:10]
                if journal_pid not in journal_pids:
                    journal_pids.add(journal_pid)
                    JournalProc.register_pid(
                        user,
                        collection,
                        journal_pid,
                        force_update=False,
                    )

    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "proc.sources.classic_website.create_collection_procs_from_pid_list",
                "user_id": user.id,
                "username": user.username,
                "collection": collection.acron,
                "pid_list_path": pid_list_path,
                "force_update": force_update,
            },
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
        detail = None
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


def create_or_update_journal_acron_id_file(
    user, collection, journal_filter, force_update=None
):
    """
    Cria ou atualiza arquivos de ID baseados em acrônimos de journals.
    """
    items = JournalProc.objects.select_related(
        "collection",
        "journal",
    ).filter(
        collection=collection,
        **journal_filter,
    )
    logging.info(f"create_or_update_journal_acron_id_file - JournalProc params: collection={collection.acron}, journal_filter={journal_filter} - {items.count()} items found")
    for journal_proc in items:
        logging.info(f"create_or_update_journal_acron_id_file - JournalProc {journal_proc}")
        controller.register_acron_id_file_content(
            user,
            journal_proc,
            force_update=force_update,
        )


def migrate_issue(user, issue_proc, force_update):
    """
    Executa a migração de um issue específico do site clássico.
    """
    try:
        event = None
        detail = None
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
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "proc.sources.classic_website.migrate_issue",
                "user_id": user.id,
                "username": user.username,
                "collection": issue_proc.collection.acron,
                "pid": issue_proc.pid,
                "force_update": force_update,
            },
        )


def migrate_document_records(
    user,
    collection_acron=None,
    journal_acron=None,
    issue_folder=None,
    publication_year=None,
    status=None,
    force_update=None,
    skip_migrate_pending_document_records=None,
):
    """
    Executa a migração de registros de documentos do site clássico.
    """
    params = {}
    if collection_acron:
        params["collection__acron"] = collection_acron
    if journal_acron:
        params["journal_proc__acron"] = journal_acron
    if issue_folder:
        params["issue_folder"] = str(issue_folder)
    if publication_year:
        params["issue__publication_year"] = str(publication_year)
    if status:
        params["docs_status__in"] = tracker_choices.get_valid_status(
            status, force_update
        )

    logging.info(f"migrate_document_records - IssueProc params: {params}")
    for issue_proc in IssueProc.objects.select_related(
        "collection",
        "journal_proc",
        "issue",
    ).filter(**params):
        logging.info(f"migrate_document_records - IssueProc {issue_proc}")
        issue_proc.migrate_document_records(user, force_update)
        ArticleProc.mark_for_reprocessing(issue_proc)

    # if skip_migrate_pending_document_records:
    #     return

    # IssueProc.migrate_pending_document_records(
    #     user,
    #     collection_acron,
    #     journal_acron,
    #     issue_folder,
    #     publication_year,
    # )


def get_files_from_classic_website(
    user,
    collection_acron=None,
    journal_acron=None,
    issue_folder=None,
    publication_year=None,
    status=None,
    force_update=None,
):
    """
    Obtém arquivos do site clássico para processamento.
    """
    params = {}
    if collection_acron:
        params["collection__acron"] = collection_acron
    if journal_acron:
        params["journal_proc__acron"] = journal_acron
    if issue_folder:
        params["issue_folder"] = str(issue_folder)
    if publication_year:
        params["issue__publication_year"] = str(publication_year)
    if status:
        params["files_status__in"] = tracker_choices.get_valid_status(
            status, force_update
        )
    items = IssueProc.objects.select_related(
        "collection",
        "journal_proc",
        "issue",
    ).filter(**params)
    logging.info(f"get_files_from_classic_website - IssueProc params: {params} - {items.count()} items found")
    for issue_proc in items:
        logging.info(f"get_files_from_classic_website - IssueProc {issue_proc}")
        issue_proc.get_files_from_classic_website(
            user, force_update, controller.migrate_issue_files
        )
        ArticleProc.mark_for_reprocessing(issue_proc)
