import logging
import sys

from django.conf import settings
from django.db.models import Q
from requests.exceptions import HTTPError 

from collection.models import Collection
from collection.choices import PUBLIC, QA
from core.utils.requester import fetch_data
from issue.models import Issue
from journal.models import (
    Journal,
    OfficialJournal,
    Subject,
    Institution,
    Publisher,
    Owner,
    JournalCollection,
    JournalHistory,
)
from migration import controller
from pid_provider.models import PidProviderConfig
from proc.models import IssueProc, JournalProc, ArticleProc
from publication.api.issue import publish_issue
from publication.api.journal import publish_journal
from publication.api.publication import get_api_data, PublicationAPI
from tracker import choices as tracker_choices
from tracker.models import UnexpectedEvent


class FetchMultipleJournalsError(Exception):
    pass


class UnableToGetJournalDataFromCoreError(Exception):
    pass


class UnableToCreateIssueProcsError(Exception):
    pass


class FetchJournalDataException(Exception):
    pass


class FetchIssueDataException(Exception):
    pass


try:
    DEFAULT_CORE_TIMEOUT = 15
    CORE_TIMEOUT = int(PidProviderConfig.objects.filter(timeout__isnull=False).first().timeout or DEFAULT_CORE_TIMEOUT)
except Exception as e:
    CORE_TIMEOUT = DEFAULT_CORE_TIMEOUT


def create_or_update_journal(
    journal_title, issn_electronic, issn_print, user, force_update=None
):
    # esta função por enquanto é chamada somente no fluxo de ingresso de conteúdo novo
    # no fluxo de migração, existe migration.controller.create_or_update_journal
    force_update = force_update or not JournalProc.objects.filter(
        Q(journal__official_journal__issn_electronic=issn_electronic) |
        Q(journal__official_journal__issn_print=issn_print)
    ).exists()

    if not force_update:
        try:
            return Journal.get_registered(journal_title, issn_electronic, issn_print)
        except Journal.DoesNotExist:
            pass

    try:
        fetch_and_create_journal(
            journal_title, issn_electronic, issn_print, user, force_update
        )
    except FetchMultipleJournalsError as exc:
        raise exc
    except FetchJournalDataException as exc:
        pass

    try:
        return Journal.get_registered(journal_title, issn_electronic, issn_print)
    except Journal.DoesNotExist as exc:
        return None


def fetch_and_create_journal(
    journal_title,
    issn_electronic,
    issn_print,
    user,
    force_update=None,
):
    try:
        params = {
            "issn_print": issn_print,
            "issn_electronic": issn_electronic,
        }
        params = {k: v for k, v in params.items() if v}
        response = fetch_data(
            url=settings.JOURNAL_API_URL,
            params=params,
            json=True,
            timeout=CORE_TIMEOUT,
        )
    except Exception as e:
        raise FetchJournalDataException(f"fetch_and_create_journal: {settings.JOURNAL_API_URL} {params} {e}")

    if response["count"] > 1:
        raise FetchMultipleJournalsError(f"{settings.JOURNAL_API_URL} with {params} returned {response['count']} journals. Ask for support to solve this issue")

    for result in response.get("results") or []:
        logging.info(f"fetch_and_create_journal {params}: {result}")

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
        official_journal.add_related_journal(
            result.get("previous_journal_title"),
            result.get("next_journal_title"),
        )
        journal = Journal.create_or_update(
            user=user,
            official_journal=official_journal,
            title=result.get("title"),
            short_title=result.get("short_title"),
        )
        journal.license_code = (result.get("journal_use_license") or {}).get("license_type")
        journal.nlm_title = result.get("nlm_title")
        journal.doi_prefix = result.get("doi_prefix")
        journal.wos_areas = result["wos_areas"]
        journal.logo_url = result["url_logo"]
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
            journal.publisher.add(Publisher.create_or_update(user, journal, institution))

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
            journal.owner.add(Owner.create_or_update(user, journal, institution))

        for item in result.get("scielo_journal") or []:
            logging.info(f"fetch_and_create_journal {params}: scielo_journal {item}")
            try:
                collection = Collection.objects.get(acron=item["collection_acron"])
            except Collection.DoesNotExist:
                continue

            journal_proc = JournalProc.get_or_create(user, collection, item["issn_scielo"])
            journal_proc.update(
                user=user,
                journal=journal,
                acron=item["journal_acron"],
                title=journal.title,
                availability_status=item.get("availability_status") or "C",
                migration_status=tracker_choices.PROGRESS_STATUS_DONE,
                force_update=force_update,
            )
            journal.journal_acron = item.get("journal_acron")
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


def create_or_update_issue(journal, pub_year, volume, suppl, number, user, force_update=None):
    # esta função por enquanto é chamada somente no fluxo de ingresso de conteúdo novo
    # no fluxo de migração, existe migration.controller.create_or_update_issue
    force_update = force_update or not IssueProc.objects.filter(
        journal_proc__journal=journal,
        issue__publication_year=pub_year,
        issue__volume=volume,
        issue__number=number,
        issue__supplement=suppl,
    ).exists()

    if not force_update:
        try:
            return Issue.get(
                journal=journal,
                volume=volume,
                supplement=suppl,
                number=number,
            )
        except Issue.DoesNotExist:
            pass

    try:
        fetch_and_create_issues(
            journal, pub_year, volume, suppl, number, user)
    except FetchIssueDataException as exc:
        pass

    try:
        return Issue.get(
            journal=journal,
            volume=volume,
            supplement=suppl,
            number=number,
        )
    except Issue.DoesNotExist as exc:
        return None


@staticmethod
def fetch_and_create_issues(journal, pub_year, volume, suppl, number, user):
    if journal:
        issn_print = journal.official_journal.issn_print
        issn_electronic = journal.official_journal.issn_electronic
        try:
            params = {
                "issn_print": issn_print,
                "issn_electronic": issn_electronic,
                "volume": volume,
            }
            params = {k: v for k, v in params.items() if v}
            response = fetch_data(
                url=settings.ISSUE_API_URL,
                params=params,
                json=True,
                timeout=CORE_TIMEOUT,
            )

        except Exception as e:
            raise FetchIssueDataException(f"fetch_and_create_issue: {settings.ISSUE_API_URL} {params} {e}")

        issue = None
        for result in response.get("results") or []:
            logging.info(f"fetch_and_create_issues {params}: {result}")
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
                    issue_proc.issue = issue
                    issue_proc.journal_proc = journal_proc
                    issue_proc.save()


def create_or_update_migrated_journal(
    user,
    collection,
    classic_website,
    force_update,
):
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
                    "task": "proc.controller.create_or_update_migrated_journal",
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
                    "task": "proc.controller.create_or_update_migrated_issue",
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
            # para cada registro da base de dados "title",
            # cria um registro MigratedData (source="journal")
            pids = fp.readlines()

        for pid in pids:
            pid = pid.strip() or ''
            if not len(pid) == 23:
                continue
            ArticleProc.register_pid(
                user,
                collection,
                pid,
                force_update=False,
            )
            issue_pid = pid[1:-5]
            if issue_pid not in issue_pids:
                issue_pids.add(issue_pid)
                IssueProc.register_pid(
                    user,
                    collection,
                    issue_pid,
                    force_update=False,
                )

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
                "task": "proc.controller.create_collection_procs_from_pid_list",
                "user_id": user.id,
                "username": user.username,
                "collection": collection.acron,
                "pid_list_path": pid_list_path,
                "force_update": force_update,
            },
        )


def migrate_journal(
    user, journal_proc, force_update,
):
    try:
        event = None
        detail = None
        detail = {
            "journal_proc": str(journal_proc),
            "force_update": force_update,
        }
        event = journal_proc.start(user, "create or update journal")

        # cria ou atualiza Journal e atualiza journal_proc
        journal_proc.create_or_update_item(
            user, force_update, controller.create_or_update_journal
        )
        event.finish(user, completed=True, detail=detail)

    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        if event:
            event.finish(user, completed=False, detail=detail, exception=e, exc_traceback=exc_traceback)
            return

        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "proc.controller.migrate_journal",
                "user_id": user.id,
                "username": user.username,
                "collection": journal_proc.collection.acron,
                "pid": journal_proc.pid,
                "issue_filter": issue_filter,
                "force_update": force_update,
                "force_import_acron_id_file": force_import_acron_id_file,
                "force_migrate_document_records": force_migrate_document_records,
                "migrate_issues": migrate_issues,
                "migrate_articles": migrate_articles,
            },
        )


def create_or_update_journal_acron_id_file(
    user, query_by_status, collection, journal_filter, force_update=None
):
    for journal_proc in JournalProc.objects.filter(
        query_by_status, collection=collection, **journal_filter
    ):
        controller.register_acron_id_file_content(
            user,
            journal_proc,
            force_update=force_update,
        )


def migrate_issue(user, issue_proc, force_update, force_migrate_document_records, migrate_articles):
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

        issue_proc.migrate_document_records(
            user,
            force_update=force_migrate_document_records,
        )

        issue_proc.get_files_from_classic_website(
            user, force_update, controller.import_one_issue_files
        )

        if migrate_articles:
            article_filter = {"issue_proc": issue_proc}
            items = ArticleProc.items_to_process(issue_proc.collection, "article", article_filter, force_update)
            logging.info(f"articles to process: {items.count()}")
            logging.info(f"article_filter: {article_filter}")
            for article_proc in items:
                article_proc.migrate_article(user, force_update)
        event.finish(user, completed=True, detail=detail)
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        if event:
            event.finish(user, completed=False, detail=detail, exception=e, exc_traceback=exc_traceback)
            return

        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "proc.controller.migrate_issue",
                "user_id": user.id,
                "username": user.username,
                "collection": issue_proc.collection.acron,
                "pid": issue_proc.pid,
                "force_update": force_update,
                "force_migrate_document_records": force_migrate_document_records,
                "migrate_articles": migrate_articles,
            },
        )


def publish_journals(
    user,
    website_kind,
    collection,
    journal_filter,
    issue_filter,
    force_update,
    run_publish_issues,
    run_publish_articles,
    task_publish_article,
):
    params = dict(
        website_kind=website_kind,
        collection=collection,
        journal_filter=journal_filter,
        issue_filter=issue_filter,
        force_update=force_update,
        run_publish_issues=run_publish_issues,
        run_publish_articles=run_publish_articles,
        task_publish_article="call task_publish_article" if task_publish_article else None
    )
    logging.info(f"publish_journals {params}")
    api_data = get_api_data(collection, "journal", website_kind)

    if api_data.get("error"):
        logging.error(api_data)
    else:
        items = JournalProc.items_to_publish(
            website_kind=website_kind,
            content_type="journal",
            collection=collection,
            force_update=force_update,
            params=journal_filter,
        )
        logging.info(f"publish_journals: {items.count()}")
        for journal_proc in items:
            response = journal_proc.publish(
                user,
                publish_journal,
                website_kind=website_kind,
                api_data=api_data,
                force_update=force_update,
            )
            if run_publish_issues and response.get("completed"):
                publish_issues(
                    user,
                    website_kind,
                    journal_proc,
                    issue_filter,
                    force_update,
                    run_publish_articles,
                    task_publish_article,
                )


def publish_issues(
    user,
    website_kind,
    journal_proc,
    issue_filter,
    force_update,
    run_publish_articles,
    task_publish_article,
):
    collection = journal_proc.collection
    params = dict(
        website_kind=website_kind,
        collection=collection,
        journal_proc=journal_proc,
        issue_filter=issue_filter,
        force_update=force_update,
        run_publish_articles=run_publish_articles,
        task_publish_article="call task_publish_article" if task_publish_article else None
    )
    logging.info(f"publish_issues {params}")
    api_data = get_api_data(collection, "issue", website_kind)

    if api_data.get("error"):
        logging.error(api_data)
    else:
        issue_filter["journal_proc"] = journal_proc
        items = IssueProc.items_to_publish(
            website_kind=website_kind,
            content_type="issue",
            collection=collection,
            force_update=force_update,
            params=issue_filter,
        )
        logging.info(f"publish_issues: {items.count()}")
        for issue_proc in items:
            response = issue_proc.publish(
                user,
                publish_issue,
                website_kind=website_kind,
                api_data=api_data,
                force_update=force_update,
            )
            if run_publish_articles and response.get("completed"):
                publish_articles(
                    user,
                    website_kind,
                    issue_proc,
                    force_update,
                    task_publish_article,
                )


def publish_articles(
    user, website_kind, issue_proc, force_update, task_publish_article
):
    collection = issue_proc.collection
    params = dict(
        website_kind=website_kind,
        collection=collection,
        issue_proc=issue_proc,
        force_update=force_update,
        task_publish_article="call task_publish_article" if task_publish_article else None
    )
    logging.info(f"publish_articles {params}")
    api_data = get_api_data(collection, "article", website_kind)
    if api_data.get("error"):
        logging.error(api_data)
    else:
        items = ArticleProc.items_to_publish(
            website_kind=website_kind,
            content_type="article",
            collection=collection,
            force_update=force_update,
            params={"issue_proc": issue_proc},
        )
        logging.info(f"publish_articles: {items.count()}")
        for article_proc in items:
            task_publish_article.apply_async(
                kwargs=dict(
                    user_id=user.id,
                    username=user.username,
                    website_kind=website_kind,
                    article_proc_id=article_proc.id,
                    api_data=api_data,
                    force_update=force_update,
                )
            )
