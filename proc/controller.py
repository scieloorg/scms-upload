import logging
import sys

from django.conf import settings

from collection.models import Collection
from core.utils.requester import fetch_data
from issue.models import Issue
from journal.models import (
    Journal, OfficialJournal,
    Subject,
    Institution,
    Publisher,
    Institution,
    Owner,
    JournalCollection,
    JournalHistory
)    
from migration import controller
from proc.models import IssueProc, JournalProc
from publication.api.issue import publish_issue
from publication.api.journal import publish_journal 
from publication.api.publication import get_api_data
from tracker import choices as tracker_choices
from tracker.models import UnexpectedEvent


class UnableToGetJournalDataFromCoreError(Exception):
    pass


class UnableToCreateIssueProcsError(Exception):
    pass


def migrate_and_publish_journals(
    user, collection, classic_website, force_update, import_acron_id_file=False
):
    try:
        api_data = get_api_data(collection, "journal", website_kind="QA")
    except Exception as e:
        logging.exception(e)
        api_data = None
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
    try:
        api_data = get_api_data(collection, "issue", website_kind="QA")
    except Exception as e:
        logging.exception(e)
        api_data = None
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


def create_or_update_journal(
    journal_title, issn_electronic, issn_print, user, force_update
):
    if force_update:
        return fetch_and_create_journal(
            journal_title, issn_electronic, issn_print, user, force_update
        )
    try:
        return Journal.get_registered(journal_title, issn_electronic, issn_print)
    except Journal.DoesNotExist:
        return fetch_and_create_journal(
            journal_title, issn_electronic, issn_print, user
        )


def fetch_and_create_journal(
    journal_title,
    issn_electronic,
    issn_print,
    user,
    force_update=None,
):
    try:
        response = fetch_data(
            url=settings.JOURNAL_API_URL,
            params={
                "title": journal_title,
                "issn_print": issn_print,
                "issn_electronic": issn_electronic,
            },
            json=True,
        )
    except Exception as e:
        logging.exception(e)
        return

    for result in response.get("results"):
        official = result["official"]
        official_journal = OfficialJournal.create_or_update(
            title=official["title"],
            title_iso=official["iso_short_title"],
            issn_print=official["issn_print"],
            issn_electronic=official["issn_electronic"],
            issnl=official["issnl"],
            foundation_year=official.get("foundation_year"),
            user=user,
        )
        journal = Journal.create_or_update(
            user=user,
            official_journal=official_journal,
            title=result.get("title"),
            short_title=result.get("short_title"),
        )
        journal.license_code = result.get("journal_use_license")
        journal.nlm_title = result.get("nlm_title")
        journal.doi_prefix = result.get("doi_prefix")
        journal.save()

    for item in result.get("Subject") or []:
        journal.subjects.add(Subject.create_or_update(user, item["value"]))

    for item in result.get("publisher") or []:
        institution = Institution.get_or_create(
            inst_name=item["name"],
            inst_acronym=None,
            level_1=None,
            level_2=None,
            level_3=None,
            location=None,
            user=user,
        )
        p = Publisher(journal=journal, institution=institution, creator=user)
        p.save()

    for item in result.get("owner") or []:
        institution = Institution.get_or_create(
            inst_name=item["name"],
            inst_acronym=None,
            level_1=None,
            level_2=None,
            level_3=None,
            location=None,
            user=user,
        )
        p = Owner(journal=journal, institution=institution, creator=user)
        p.save()

    for item in result.get("scielo_journal") or []:
        try:
            collection = Collection.objects.get(acron=item["collection_acron"])
        except Collection.DoesNotExist:
            continue

        journal_proc = JournalProc.get_or_create(user, collection, item["scielo_issn"])
        journal_proc.update(
            user=user,
            journal=journal,
            acron=item["journal_acron"],
            title=journal.title,
            availability_status="C",
            migration_status=tracker_choices.PROGRESS_STATUS_DONE,
            force_update=force_update,
        )
        journal.acron = item.get("journal_acron")
        journal_collection = JournalCollection.create_or_update(
            user, collection, journal
        )
        for jh in item.get("journal_history") or []:
            JournalHistory.create_or_update(
                user,
                journal_collection,
                jh["event_type"],
                jh["year"],
                jh["month"],
                jh["day"],
                jh["interruption_reason"],
            )
    return journal


def create_or_update_issue(journal, volume, suppl, number, user, force_update=None):
    if force_update:
        return fetch_and_create_issue(journal, volume, suppl, number, user)
    try:
        return Issue.get(
            journal=journal,
            volume=volume,
            supplement=suppl,
            number=number,
        )
    except Issue.DoesNotExist:
        return fetch_and_create_issue(journal, volume, suppl, number, user)


@staticmethod
def fetch_and_create_issue(journal, volume, suppl, number, user):
    if journal and any((volume, number)):
        issn_print = journal.official_journal.issn_print
        issn_electronic = journal.official_journal.issn_electronic
        try:
            response = fetch_data(
                url=settings.ISSUE_API_URL,
                params={
                    "issn_print": issn_print,
                    "issn_electronic": issn_electronic,
                    "number": number,
                    "supplement": suppl,
                    "volume": volume,
                },
                json=True,
            )

        except Exception as e:
            logging.exception(e)
            return

        issue = None
        for result in response.get("results"):
            issue = Issue.get_or_create(
                journal=journal,
                volume=result["volume"],
                supplement=result["supplement"],
                number=result["number"],
                publication_year=result["year"],
                user=user,
            )

            for journal_proc in JournalProc.objects.filter(journal=journal):
                try:
                    issue_proc = IssueProc.objects.get(
                        collection=journal_proc.collection, issue=issue
                    )
                except IssueProc.DoesNotExist:
                    issue_pid_suffix = str(issue.order).zfill(4)
                    issue_proc = IssueProc.get_or_create(
                        user,
                        journal_proc.collection,
                        pid=f"{journal_proc.pid}{issue.publication_year}{issue_pid_suffix}",
                    )
                    issue_proc.journal_proc = journal_proc
                    issue_proc.save()
        return issue
