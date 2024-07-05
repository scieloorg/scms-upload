import logging
import sys

from migration import controller
from proc.models import IssueProc, JournalProc
from publication.api.issue import publish_issue
from publication.api.journal import publish_journal
from publication.api.publication import get_api_data
from tracker.models import UnexpectedEvent


def migrate_and_publish_journals(
    user, collection, classic_website, force_update, import_acron_id_file=False
):
    api_data = get_api_data(collection, "journal", website_kind="QA")
    for (
        scielo_issn,
        journal_data,
    ) in classic_website.get_journals_pids_and_records():
        # para cada registro da base de dados "title",
        # cria um registro MigratedData (source="journal")
        try:
            journal_proc = JournalProc.register_classic_website_data(
                user,
                collection,
                scielo_issn,
                journal_data[0],
                "journal",
                force_update,
            )
            # cria ou atualiza Journal e atualiza journal_proc
            journal_proc.create_or_update_item(
                user, force_update, controller.create_or_update_journal
            )
            # acron.id
            if import_acron_id_file:
                controller.register_acron_id_file_content(
                    user,
                    journal_proc,
                    force_update,
                )
            journal_proc.publish(
                user,
                publish_journal,
                api_data=api_data,
                force_update=force_update,
            )

        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            UnexpectedEvent.create(
                e=e,
                exc_traceback=exc_traceback,
                detail={
                    "task": "proc.controller.migrate_and_publish_journals",
                    "user_id": user.id,
                    "username": user.username,
                    "collection": collection.acron,
                    "pid": scielo_issn,
                    "force_update": force_update,
                },
            )


def migrate_and_publish_issues(
    user,
    collection,
    classic_website,
    force_update,
    get_files_from_classic_website=False,
):
    api_data = get_api_data(collection, "issue", website_kind="QA")
    for (
        pid,
        issue_data,
    ) in classic_website.get_issues_pids_and_records():
        # para cada registro da base de dados "issue",
        # cria um registro MigratedData (source="issue")
        try:
            issue_proc = IssueProc.register_classic_website_data(
                user,
                collection,
                pid,
                issue_data[0],
                "issue",
                force_update,
            )
            issue_proc.create_or_update_item(
                user,
                force_update,
                controller.create_or_update_issue,
                JournalProc=JournalProc,
            )
            issue_proc.publish(
                user,
                publish_issue,
                api_data=api_data,
                force_update=force_update,
            )

            if get_files_from_classic_website:
                issue_proc.get_files_from_classic_website(
                    user, force_update, controller.import_one_issue_files
                )
        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            UnexpectedEvent.create(
                e=e,
                exc_traceback=exc_traceback,
                detail={
                    "task": "proc.controller.migrate_and_publish_issues",
                    "user_id": user.id,
                    "username": user.username,
                    "collection": collection.acron,
                    "pid": pid,
                    "force_update": force_update,
                },
            )
