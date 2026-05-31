"""
Tasks Celery do módulo proc.

Organização hierárquica das tasks de migração e publicação:

  Journals:
    task_migrate_and_publish_journals
      └─ task_migrate_and_publish_journals_by_collection (por coleção)
    task_publish_journals
      └─ task_publish_journal (por periódico)

  Issues:
    task_migrate_and_publish_issues
      └─ task_migrate_and_publish_issues_by_collection (por coleção)
    task_publish_issues
      └─ task_publish_issue (por fascículo)

  Articles:
    task_migrate_and_publish_articles
      └─ task_migrate_and_publish_articles_by_journal (por periódico)
          └─ task_migrate_and_publish_articles_by_issue (por fascículo)
              └─ task_publish_issue_articles (publica artigos + sincroniza issue)
                  ├─ task_publish_article (por artigo, síncrono)
                  │   └─ task_check_article_webpages (verifica disponibilidade)
                  │       ├─ task_check_article_page_availability (por webpage, síncrono)
                  │       └─ task_update_article_proc_availability (callback)
                  └─ task_sync_issue (sincroniza fascículo no site)

  Publicação avulsa (somente publicação, sem migração):
    task_publish_articles
      └─ task_publish_issue_articles (por fascículo)

  Verificação de disponibilidade (em lote):
    task_check_articles_availability
      └─ task_check_article_webpages (por artigo × website)
          ├─ task_check_article_page_availability (por webpage)
          └─ task_update_article_proc_availability (callback)

  Rastreamento de PIDs do site clássico:
    task_track_classic_website_article_pids
      └─ task_track_classic_website_article_pids_for_collection (por coleção)
          └─ task_track_article_page_url_and_content (por artigo)

  Verificação no site clássico (migração):
    task_check_migrated_article

  Utilitários:
    task_fetch_and_create_journal
    task_exclude_invalid_issue_articles
    task_remove_duplicate_issues
    task_check_main_article_page_availability
"""

import logging
import sys
import traceback
import json

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from article.models import Article, ArticleCollection, ArticleWebPage, get_pid_status_from_webpage_status
from article import choices as article_choices
from journal.models import Journal
from issue.models import Issue
from collection.choices import PUBLIC, QA
from collection.models import Collection, WebSiteConfiguration
from config import celery_app
from migration import controller
from migration import choices as migration_choices
from package.models import SPSPkg
from proc.controller import (
    create_or_update_migrated_issue,
    create_or_update_migrated_journal,
    fetch_and_create_journal,
    migrate_issue,
)
from proc.article_controller import ClassicWebsiteArticlePidTracker
from proc.models import ArticleProc, IssueProc, JournalProc
from publication.api.document import publish_article
from publication.api.issue import publish_issue, sync_issue
from publication.api.journal import publish_journal
from publication.api.publication import get_api_data
from tracker import choices as tracker_choices
from tracker.models import TaskTracker, UnexpectedEvent

User = get_user_model()


class NothingToProcess(Exception):
    ...


class TaskExecution:
    """
    Wrapper para TaskTracker que acumula eventos, estatísticas e exceções
    durante a execução de uma task, e persiste tudo ao finalizar.
    """

    def __init__(self, name, item, params):
        self.params = params
        self.task_tracker = TaskTracker.create(
            name=name,
            item=item,
        )
        self.events = []
        self.stats = {}
        self.exceptions = []

    @property
    def item(self):
        return self.task_tracker.item

    @item.setter
    def item(self, value):
        self.task_tracker.item = value

    @property
    def total_to_process(self):
        return self.task_tracker.total_to_process

    @total_to_process.setter
    def total_to_process(self, value):
        self.task_tracker.total_to_process = value

    @property
    def total_processed(self):
        return self.task_tracker.total_processed

    @total_processed.setter
    def total_processed(self, value):
        self.task_tracker.total_processed = value

    def add_exception(self, exception):
        self.exceptions.append(
            {"type": str(type(exception)), "message": str(exception)}
        )

    def add_event(self, event):
        if isinstance(event, list):
            self.events.extend(event)
        else:
            self.events.append(event)

    def add_number(self, name, number):
        self.stats[name] = number

    def finish(self, exception=None, exc_traceback=None):
        """Persiste o TaskTracker com stats, eventos e exceções acumulados."""
        if exception or exc_traceback or self.exceptions:
            completed = False
        else:
            completed = True
        self.params["item"] = self.item

        self.stats["total_to_process"] = self.total_to_process
        self.stats["total_processed"] = self.total_processed

        detail = {
            "params": self.params,
            "stats": self.stats,
            "events": self.events,
            "exceptions": self.exceptions,
        }
        try:
            json.dumps(detail)
        except Exception:
            fixed_detail = {}
            for key, value in detail.items():
                try:
                    json.dumps(value)
                    fixed_detail[key] = value
                except Exception:
                    fixed_detail[key] = str(value)
            detail = fixed_detail

        self.task_tracker.finish(
            completed=completed,
            exception=exception,
            exc_traceback=exc_traceback,
            detail=detail,
        )


def _get_user(user_id, username):
    """Retorna o User por pk ou username; retorna None em caso de falha."""
    try:
        if user_id:
            return User.objects.get(pk=user_id)
        if username:
            return User.objects.get(username=username)
        return None
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "proc.tasks._get_user",
                "user_id": user_id,
                "username": username,
            },
        )
        return None


def _get_collections(collection_acron):
    """Retorna iterator de Collections filtrado por acron, ou todas se acron for None."""
    try:
        if collection_acron:
            return Collection.objects.filter(acron=collection_acron).iterator()
        else:
            return Collection.objects.iterator()
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "proc.tasks._get_collections",
                "collection_acron": collection_acron,
            },
        )
        return []


############################################
# JOURNALS
############################################


@celery_app.task(bind=True)
def task_migrate_and_publish(
    self,
    user_id=None,
    username=None,
    collection_acron=None,
    journal_acron=None,
    publication_year=None,
    issue_folder=None,
    force_update=False,
    force_import_acron_id_file=False,
    force_migrate_document_records=False,
):
    """Obsoleta. Use task_migrate_and_publish_journals, _issues ou _articles."""
    logging.info("task_migrate_and_publish is discontinued")
    logging.info("Use task_migrate_and_publish_journals")
    logging.info("Use task_migrate_and_publish_issues")
    logging.info("Use task_migrate_and_publish_articles")


@celery_app.task(bind=True)
def task_migrate_and_publish_journals(
    self,
    user_id=None,
    username=None,
    collection_acron=None,
    journal_acron=None,
    force_update=False,
    status=None,
    valid_status=None,
    force_import_acron_id_file=False,
):
    """
    Ponto de entrada para migração e publicação de periódicos.

    Agenda task_migrate_and_publish_journals_by_collection para cada coleção.
    """
    try:
        task_params = {
            "task": "proc.tasks.task_migrate_and_publish_journals",
            "user_id": user_id,
            "username": username,
            "collection_acron": collection_acron,
            "journal_acron": journal_acron,
            "force_update": force_update,
            "status": status,
            "force_import_acron_id_file": force_import_acron_id_file,
        }
        for collection in _get_collections(collection_acron):
            task_migrate_and_publish_journals_by_collection.delay(
                user_id=user_id,
                username=username,
                collection_acron=collection.acron,
                journal_acron=journal_acron,
                force_update=force_update,
                status=status,
                force_import_acron_id_file=force_import_acron_id_file,
            )
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            action="proc.tasks.task_migrate_and_publish_journals",
            item=f"{collection_acron}-{journal_acron}",
            e=e,
            exc_traceback=exc_traceback,
            detail={"task_params": task_params},
        )


@celery_app.task(bind=True)
def task_migrate_and_publish_journals_by_collection(
    self,
    user_id=None,
    username=None,
    collection_acron=None,
    journal_acron=None,
    force_update=False,
    status=None,
    force_import_acron_id_file=False,
):
    """
    Migra e publica periódicos de uma coleção.

    Importa dados do site clássico via ``create_or_update_migrated_journal``,
    atualiza cada ``JournalProc`` e agenda ``task_publish_journal`` nos
    websites QA e PUBLIC.
    """
    task_params = {
        "task": "proc.tasks.task_migrate_and_publish_journals",
        "user_id": user_id,
        "username": username,
        "collection_acron": collection_acron,
        "journal_acron": journal_acron,
        "force_update": force_update,
        "status": status,
        "force_import_acron_id_file": force_import_acron_id_file,
    }
    task_exec = TaskExecution(
        name="proc.tasks.task_migrate_and_publish_journals_by_collection",
        item=f"{collection_acron}-{journal_acron}",
        params=task_params,
    )
    try:
        user = _get_user(user_id, username)

        classic_website = controller.get_classic_website(collection_acron)
        collection = Collection.objects.get(acron=collection_acron)
        create_or_update_migrated_journal(
            user, collection, classic_website, force_update
        )

        journal_filter = {}
        if journal_acron:
            journal_filter["acron"] = journal_acron
        status = tracker_choices.get_valid_status(status, force_update)
        query_by_status = (
            Q(migration_status__in=status)
            | Q(qa_ws_status__in=status)
            | Q(public_ws_status__in=status)
        )
        items_to_process = JournalProc.objects.filter(
            query_by_status, collection=collection, **journal_filter
        )
        task_exec.total_to_process = items_to_process.count()
        if not task_exec.total_to_process:
            task_exec.finish()
            return

        qa_api_data = get_api_data(collection, "journal", "QA")
        public_api_data = get_api_data(collection, "journal", "PUBLIC")
        total_processed = 0
        for journal_proc in items_to_process:
            try:
                detail = {}
                event = journal_proc.start(user, "migrate journal")
                completed = journal_proc.create_or_update_item(
                    user, force_update, controller.create_or_update_journal
                )
                if force_update or not journal_proc.journal.core_synchronized:
                    fetch_and_create_journal(
                        user,
                        collection_acron=collection.acron,
                        issn_electronic=journal_proc.issn_electronic,
                        issn_print=journal_proc.issn_print,
                        force_update=force_update,
                    )
                if qa_api_data and not qa_api_data.get("error"):
                    task_publish_journal.apply_async(
                        kwargs=dict(
                            user_id=user_id,
                            username=username,
                            website_kind="QA",
                            journal_proc_id=journal_proc.id,
                            api_data=qa_api_data,
                            force_update=force_update,
                        )
                    )
                if public_api_data and not public_api_data.get("error"):
                    task_publish_journal.apply_async(
                        kwargs=dict(
                            user_id=user_id,
                            username=username,
                            website_kind="PUBLIC",
                            journal_proc_id=journal_proc.id,
                            api_data=public_api_data,
                            force_update=force_update,
                        )
                    )
                event.finish(user, completed=True, detail=detail)
                total_processed += 1
            except Exception as e:
                exc_type, exc_value, exc_traceback = sys.exc_info()
                if event:
                    event.finish(
                        user,
                        completed=False,
                        exception=e,
                        exc_traceback=exc_traceback,
                        detail=detail,
                    )
                else:
                    UnexpectedEvent.create(
                        action="proc.tasks.task_migrate_and_publish_journals_by_collection",
                        item=f"{journal_proc}",
                        e=e,
                        exc_traceback=exc_traceback,
                        detail=detail,
                    )
        task_exec.total_processed = total_processed
        task_exec.finish()
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        try:
            task_exec.finish(exception=e, exc_traceback=exc_traceback)
        except Exception:
            UnexpectedEvent.create(
                action="proc.tasks.task_migrate_and_publish_journals_by_collection",
                item=f"{collection_acron}-{journal_acron}",
                e=e,
                exc_traceback=exc_traceback,
                detail=task_params,
            )


@celery_app.task(bind=True)
def task_publish_journals(
    self,
    user_id=None,
    username=None,
    collection_acron=None,
    journal_acron=None,
    force_update=False,
    verify=False,
):
    """
    Agenda publicação de periódicos pendentes nos sites QA e PUBLIC.
    """
    task_params = {
        "task": "proc.tasks.task_publish_journals",
        "user_id": user_id,
        "username": username,
        "collection_acron": collection_acron,
        "journal_acron": journal_acron,
        "force_update": force_update,
    }
    try:
        user = _get_user(user_id, username)
        params = {}
        if journal_acron:
            params["acron"] = journal_acron

        for collection in _get_collections(collection_acron):
            for website_kind in (QA, PUBLIC):
                api_data = get_api_data(collection, "journal", website_kind)
                if not api_data or api_data.get("error"):
                    continue
                api_data["verify"] = verify
                task_exec = TaskExecution(
                    name="proc.tasks.task_publish_journals",
                    item=f"{collection_acron}-{journal_acron} {website_kind}",
                    params=task_params,
                )
                total_processed = 0
                items = JournalProc.items_to_publish(
                    website_kind=website_kind,
                    content_type="journal",
                    collection=collection,
                    force_update=force_update,
                    params=params,
                )
                task_exec.total_to_process = items.count()
                for journal_proc in items:
                    try:
                        task_publish_journal.apply_async(
                            kwargs=dict(
                                user_id=user_id,
                                username=username,
                                website_kind=website_kind,
                                journal_proc_id=journal_proc.id,
                                api_data=api_data,
                                force_update=force_update,
                            )
                        )
                        total_processed += 1
                    except Exception as e:
                        exc_type, exc_value, exc_traceback = sys.exc_info()
                        UnexpectedEvent.create(
                            item=str(journal_proc),
                            action="task_publish_journal",
                            e=e,
                            exc_traceback=exc_traceback,
                            detail=task_params,
                        )
                task_exec.total_processed = total_processed
                task_exec.finish()
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            item=f"{collection_acron}-{journal_acron}",
            action="task_publish_journal",
            e=e,
            exc_traceback=exc_traceback,
            detail=task_params,
        )


@celery_app.task(bind=True)
def task_publish_journal(
    self,
    user_id=None,
    username=None,
    website_kind=None,
    journal_proc_id=None,
    api_data=None,
    force_update=None,
):
    """
    Publica um periódico individual no site QA ou PUBLIC via API.

    Delega para ``JournalProc.publish``, que atualiza ``qa_ws_status`` ou
    ``public_ws_status`` conforme o resultado da chamada à API.
    """
    try:
        user = _get_user(user_id, username)
        journal_proc = JournalProc.objects.get(pk=journal_proc_id)
        event = journal_proc.start(user, "proc.tasks.publish_journal")
        journal_proc.publish(
            user,
            publish_journal,
            content_type="journal",
            website_kind=website_kind,
            api_data=api_data,
            force_update=force_update,
        )
        event.finish(user, completed=True)
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        try:
            event.finish(
                user,
                completed=False,
                exception=e,
                exc_traceback=exc_traceback,
            )
        except Exception:
            UnexpectedEvent.create(
                action="proc.tasks.publish_journal",
                item=f"{journal_proc_id}",
                e=e,
                exc_traceback=exc_traceback,
                detail={
                    "task": "proc.tasks.publish_journal",
                    "user_id": user_id,
                    "username": username,
                    "website_kind": website_kind,
                    "journal_proc_id": journal_proc_id,
                },
            )


############################################
# ISSUES
############################################


@celery_app.task(bind=True)
def task_migrate_and_publish_issues(
    self,
    user_id=None,
    username=None,
    collection_acron=None,
    journal_acron=None,
    publication_year=None,
    issue_folder=None,
    status=None,
    valid_status=None,
    force_update=False,
    force_migrate_document_records=False,
):
    """
    Ponto de entrada para migração e publicação de fascículos.

    Agenda task_migrate_and_publish_issues_by_collection para cada coleção.
    """
    task_params = {
        "user_id": user_id,
        "username": username,
        "collection_acron": collection_acron,
        "journal_acron": journal_acron,
        "publication_year": publication_year,
        "issue_folder": issue_folder,
        "status": status,
        "force_update": force_update,
        "force_migrate_document_records": force_migrate_document_records,
    }
    try:
        user = _get_user(user_id, username)
        for collection in _get_collections(collection_acron):
            task_params["collection_acron"] = collection.acron
            task_migrate_and_publish_issues_by_collection.delay(**task_params)
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            action="proc.tasks.task_migrate_and_publish_issues",
            item=f"{collection_acron}-{journal_acron}-{issue_folder}-{publication_year}",
            e=e,
            exc_traceback=exc_traceback,
            detail=task_params,
        )


@celery_app.task(bind=True)
def task_migrate_and_publish_issues_by_collection(
    self,
    user_id=None,
    username=None,
    collection_acron=None,
    journal_acron=None,
    publication_year=None,
    issue_folder=None,
    status=None,
    valid_status=None,
    force_update=False,
    force_migrate_document_records=False,
):
    """
    Migra e publica fascículos de uma coleção.

    Importa dados do site clássico via ``create_or_update_migrated_issue``,
    executa ``migrate_issue`` para cada ``IssueProc`` e agenda
    ``task_publish_issue`` nos websites QA e PUBLIC.
    """
    task_params = {
        "user_id": user_id,
        "username": username,
        "collection_acron": collection_acron,
        "journal_acron": journal_acron,
        "publication_year": publication_year,
        "status": status,
        "force_update": force_update,
        "issue_folder": issue_folder,
        "force_migrate_document_records": force_migrate_document_records,
    }
    task_exec = TaskExecution(
        name="proc.tasks.task_migrate_and_publish_issues_by_collection",
        item=f"{collection_acron}-{journal_acron}-{issue_folder}-{publication_year}",
        params=task_params,
    )
    try:
        user = _get_user(user_id, username)

        classic_website = controller.get_classic_website(collection_acron)
        collection = Collection.objects.get(acron=collection_acron)
        create_or_update_migrated_issue(
            user, collection, classic_website, force_update
        )

        params = {}
        if journal_acron:
            params["journal_proc__acron"] = journal_acron
        if issue_folder:
            params["issue_folder"] = issue_folder
        if publication_year:
            params["issue__publication_year"] = publication_year
        status = tracker_choices.get_valid_status(status, force_update)
        query_by_status = (
            Q(migration_status__in=status)
            | Q(docs_status__in=status)
            | Q(files_status__in=status)
            | Q(qa_ws_status__in=status)
            | Q(public_ws_status__in=status)
        )
        items = IssueProc.objects.filter(
            query_by_status, collection=collection, **params
        )
        task_exec.total_to_process = items.count()

        if not task_exec.total_to_process:
            task_exec.finish()
            return

        qa_api_data = get_api_data(collection, "issue", "QA")
        public_api_data = get_api_data(collection, "issue", "PUBLIC")

        for issue_proc in items:
            try:
                migrate_issue(user, issue_proc, force_update)
                if qa_api_data and not qa_api_data.get("error"):
                    task_publish_issue.apply_async(
                        kwargs=dict(
                            user_id=user_id,
                            username=username,
                            website_kind="QA",
                            issue_proc_id=issue_proc.id,
                            api_data=qa_api_data,
                            force_update=force_update,
                        )
                    )
                if public_api_data and not public_api_data.get("error"):
                    task_publish_issue.apply_async(
                        kwargs=dict(
                            user_id=user_id,
                            username=username,
                            website_kind="PUBLIC",
                            issue_proc_id=issue_proc.id,
                            api_data=public_api_data,
                            force_update=force_update,
                        )
                    )
                task_exec.total_processed += 1
            except Exception as e:
                exc_type, exc_value, exc_traceback = sys.exc_info()
                task_exec.add_exception(traceback.format_exc())
        task_exec.finish()
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        try:
            task_exec.finish(exception=e, exc_traceback=exc_traceback)
        except Exception:
            UnexpectedEvent.create(
                action="proc.tasks.task_migrate_and_publish_issues_by_collection",
                item=f"{collection_acron}-{journal_acron}",
                e=e,
                exc_traceback=exc_traceback,
                detail=task_params,
            )


@celery_app.task(bind=True)
def task_publish_issues(
    self,
    user_id=None,
    username=None,
    collection_acron=None,
    journal_acron=None,
    issue_folder=None,
    publication_year=None,
    force_update=False,
    verify=False,
):
    """
    Agenda publicação de fascículos pendentes nos sites QA e PUBLIC.

    Itera coleções e tipos de website; para cada par agenda ``task_publish_issue``
    somente para os IssueProcs com status pendente.
    """
    task_params = {
        "collection_acron": collection_acron,
        "journal_acron": journal_acron,
        "issue_folder": issue_folder,
        "publication_year": publication_year,
        "force_update": force_update,
    }
    try:
        params = {}
        if journal_acron:
            params["journal_proc__acron"] = journal_acron
        if issue_folder:
            params["issue_folder"] = str(issue_folder)
        if publication_year:
            params["issue__publication_year"] = str(publication_year)

        for collection in _get_collections(collection_acron):
            for website_kind in (QA, PUBLIC):
                total_processed = 0
                api_data = get_api_data(collection, "issue", website_kind)
                if not api_data or api_data.get("error"):
                    continue
                api_data["verify"] = verify
                task_exec = TaskExecution(
                    name="proc.tasks.task_publish_issues",
                    item=f"{collection_acron}-{journal_acron}-{issue_folder}-{publication_year} {website_kind}",
                    params=task_params,
                )
                items = IssueProc.items_to_publish(
                    website_kind=website_kind,
                    content_type="issue",
                    collection=collection,
                    force_update=force_update,
                    params=params,
                )
                task_exec.total_to_process = items.count()
                for issue_proc in items:
                    try:
                        task_publish_issue.apply_async(
                            kwargs=dict(
                                user_id=user_id,
                                username=username,
                                website_kind=website_kind,
                                issue_proc_id=issue_proc.id,
                                api_data=api_data,
                                force_update=force_update,
                            )
                        )
                        total_processed += 1
                    except Exception as e:
                        exc_type, exc_value, exc_traceback = sys.exc_info()
                        task_exec.add_exception(traceback.format_exc())
                task_exec.total_processed = total_processed
                task_exec.finish()
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            item=f"{collection_acron}-{journal_acron}-{issue_folder}-{publication_year}",
            action="task_publish_issues",
            e=e,
            exc_traceback=exc_traceback,
            detail=task_params,
        )


@celery_app.task(bind=True)
def task_publish_issue(
    self,
    user_id=None,
    username=None,
    website_kind=None,
    issue_proc_id=None,
    api_data=None,
    force_update=None,
):
    """
    Publica um fascículo individual no site QA ou PUBLIC via API.

    Delega para ``IssueProc.publish``, que atualiza ``qa_ws_status`` ou
    ``public_ws_status`` conforme o resultado da chamada à API.
    """
    try:
        user = _get_user(user_id, username)
        issue_proc = IssueProc.objects.get(pk=issue_proc_id)
        event = issue_proc.start(user, "proc.tasks.publish_issue")
        issue_proc.publish(
            user,
            publish_issue,
            content_type="issue",
            website_kind=website_kind,
            api_data=api_data,
            force_update=force_update,
        )
        event.finish(user=user, completed=True)
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        try:
            event.finish(
                user=user,
                completed=False,
                exception=e,
                exc_traceback=exc_traceback,
            )
        except Exception:
            UnexpectedEvent.create(
                item=f"{issue_proc_id}",
                action="proc.tasks.publish_issue",
                e=e,
                exc_traceback=exc_traceback,
                detail={
                    "task": "proc.tasks.publish_issue",
                    "user_id": user_id,
                    "username": username,
                    "website_kind": website_kind,
                    "issue_proc_id": issue_proc_id,
                },
            )


############################################
# ARTICLES
############################################


@celery_app.task(bind=True)
def task_migrate_and_publish_articles(
    self,
    user_id=None,
    username=None,
    collection_acron=None,
    journal_acron=None,
    collection_acron_list=None,
    journal_acron_list=None,
    publication_year=None,
    issue_folder=None,
    status=None,
    valid_status=None,
    force_update=False,
    force_import_acron_id_file=False,
    force_migrate_document_records=False,
    force_migrate_document_files=False,
    skip_migrate_pending_document_records=False,
):
    """
    Ponto de entrada para migração e publicação de artigos.

    Consolida collection_acron_list/journal_acron_list, seleciona JournalProcs
    ou IssueProcs conforme os filtros fornecidos e agenda
    ``task_migrate_and_publish_articles_by_journal`` para cada periódico.
    """
    task_params = {
        "user_id": user_id,
        "username": username,
        "collection_acron": collection_acron,
        "journal_acron": journal_acron,
        "collection_acron_list": collection_acron_list,
        "journal_acron_list": journal_acron_list,
        "publication_year": publication_year,
        "issue_folder": issue_folder,
        "status": status,
        "force_update": force_update,
        "force_import_acron_id_file": force_import_acron_id_file,
        "force_migrate_document_records": force_migrate_document_records,
        "force_migrate_document_files": force_migrate_document_files,
    }
    title = f"{collection_acron or collection_acron_list}-{journal_acron or journal_acron_list}-{issue_folder}-{publication_year}"
    task_exec = TaskExecution(
        name="proc.tasks.task_migrate_and_publish_articles",
        item=title,
        params=task_params,
    )
    try:
        params = {}
        journal_acron_list = journal_acron_list or []
        if journal_acron:
            journal_acron_list += [journal_acron]
        collection_acron_list = collection_acron_list or []
        if collection_acron:
            collection_acron_list += [collection_acron]

        items_to_process = {}
        if publication_year or issue_folder:
            selected_issue_procs = IssueProc.select_items(
                collection_acron_list=collection_acron_list,
                journal_acron_list=journal_acron_list,
                publication_year=publication_year,
                issue_folder=issue_folder,
                status_list=status,
                force_update=force_migrate_document_records
                or force_migrate_document_files,
                to_migrate_articles=True,
            )
            issue_proc_ids = selected_issue_procs.values_list(
                "journal_proc_id", "id"
            ).distinct()
            for journal_proc_id, issue_proc_id in issue_proc_ids:
                items_to_process.setdefault(journal_proc_id, []).append(
                    issue_proc_id
                )
        else:
            journal_proc_ids = JournalProc.select_items(
                collection_acron_list=collection_acron_list,
                journal_acron_list=journal_acron_list,
            ).values_list("id", flat=True)
            items_to_process = {
                journal_proc_id: None
                for journal_proc_id in journal_proc_ids
            }

        total_journals_to_process = len(items_to_process)
        task_exec.add_number(
            "total_journals_to_process", total_journals_to_process
        )

        kwargs_ = {}
        kwargs_.update(task_params)
        kwargs_.pop("collection_acron_list", None)
        kwargs_.pop("journal_acron_list", None)

        task_exec.total_to_process = total_journals_to_process
        total_processed = 0
        for journal_proc_id, issue_proc_id_list in items_to_process.items():
            kwargs = {}
            kwargs.update(kwargs_)
            kwargs["journal_proc_id"] = journal_proc_id
            kwargs["issue_proc_id_list"] = issue_proc_id_list
            total_processed += 1
            task_migrate_and_publish_articles_by_journal.delay(**kwargs)

        task_exec.total_processed = total_processed
        task_exec.finish()

    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        try:
            task_exec.finish(exception=e, exc_traceback=exc_traceback)
        except Exception:
            UnexpectedEvent.create(
                item=title,
                action="proc.tasks.task_migrate_and_publish_articles",
                e=e,
                exc_traceback=exc_traceback,
                detail=task_params,
            )


@celery_app.task(bind=True)
def task_migrate_and_publish_articles_by_journal(
    self,
    user_id=None,
    username=None,
    journal_proc_id=None,
    issue_proc_id_list=None,
    collection_acron=None,
    journal_acron=None,
    publication_year=None,
    issue_folder=None,
    status=None,
    valid_status=None,
    force_update=False,
    force_import_acron_id_file=False,
    force_migrate_document_records=False,
    force_migrate_document_files=False,
):
    """
    Migra e publica artigos de um periódico.

    Importa o arquivo acron.id via ``controller.import_journal_acron_id_records``
    e agenda ``task_migrate_and_publish_articles_by_issue`` para cada
    ``IssueProc`` do periódico.
    """
    task_params = {
        "user_id": user_id,
        "username": username,
        "collection_acron": collection_acron,
        "journal_acron": journal_acron,
        "publication_year": publication_year,
        "issue_folder": issue_folder,
        "status": status,
        "force_update": force_update,
        "force_import_acron_id_file": force_import_acron_id_file,
        "force_migrate_document_records": force_migrate_document_records,
        "force_migrate_document_files": force_migrate_document_files,
    }
    title = f"{collection_acron}-{journal_acron}-{issue_folder}-{publication_year}"
    task_exec = TaskExecution(
        name="proc.tasks.task_migrate_and_publish_articles_by_journal",
        item=title,
        params=task_params,
    )
    try:
        if not journal_proc_id:
            raise ValueError("journal_proc_id is required")

        journal_proc = JournalProc.objects.get(id=journal_proc_id)
        user = _get_user(user_id, username)

        websites_to_ignore = ["PUBLIC", "QA"]
        for purpose in WebSiteConfiguration.objects.filter(collection=journal_proc.collection, enabled=True).values_list("purpose", flat=True):
            websites_to_ignore.remove(purpose)
        for purpose in websites_to_ignore:
            if purpose == "QA":
                JournalProc.objects.filter(
                    id=journal_proc.id,
                    qa_ws_status=tracker_choices.PROGRESS_STATUS_TODO).update(
                    qa_ws_status=tracker_choices.PROGRESS_STATUS_IGNORED
                )
                IssueProc.objects.filter(
                    journal_proc=journal_proc,
                    qa_ws_status=tracker_choices.PROGRESS_STATUS_TODO).update(
                    qa_ws_status=tracker_choices.PROGRESS_STATUS_IGNORED
                )
                ArticleProc.objects.filter(
                    issue_proc__journal_proc=journal_proc,
                    qa_ws_status=tracker_choices.PROGRESS_STATUS_TODO).update(
                    qa_ws_status=tracker_choices.PROGRESS_STATUS_IGNORED
                )
            elif purpose == "PUBLIC":
                JournalProc.objects.filter(
                    id=journal_proc.id,
                    public_ws_status=tracker_choices.PROGRESS_STATUS_TODO).update(
                    public_ws_status=tracker_choices.PROGRESS_STATUS_IGNORED
                )
                IssueProc.objects.filter(
                    journal_proc=journal_proc,
                    public_ws_status=tracker_choices.PROGRESS_STATUS_TODO).update(
                    public_ws_status=tracker_choices.PROGRESS_STATUS_IGNORED
                )
                ArticleProc.objects.filter(
                    issue_proc__journal_proc=journal_proc,
                    public_ws_status=tracker_choices.PROGRESS_STATUS_TODO).update(
                    public_ws_status=tracker_choices.PROGRESS_STATUS_IGNORED
                )

        response = controller.import_journal_acron_id_records(
            user,
            ArticleProc,
            journal_proc,
            force_update=force_import_acron_id_file,
        )

        qa_api_data = get_api_data(
            journal_proc.collection, "issue", "QA"
        )
        public_api_data = get_api_data(
            journal_proc.collection, "issue", "PUBLIC"
        )
        total_processed = 0
        total_to_process = 0

        if issue_proc_id_list:
            issue_proc_and_related_article_proc_id_list = {
                issue_proc_id: []
                for issue_proc_id in issue_proc_id_list
            }
        else:
            selected_issue_procs = IssueProc.select_items(
                journal_proc_id_list=[journal_proc_id],
                status_list=status,
                force_update=force_migrate_document_records
                or force_migrate_document_files,
                to_migrate_articles=True,
            )
            issue_proc_id_list = list(
                selected_issue_procs.values_list("id", flat=True)
            )
            issue_proc_and_related_article_proc_id_list = {
                issue_proc_id: []
                for issue_proc_id in (issue_proc_id_list or [])
            }

            selected_article_proc_items = (
                ArticleProc.select_items(
                    journal_proc_id_list=[journal_proc_id],
                    exclude_issue_proc_id_list=list(issue_proc_id_list),
                    status_list=status,
                    force_update=force_update,
                )
                .values_list("issue_proc_id", "id")
                .distinct()
            )

            for issue_proc_id, article_proc_id in (
                selected_article_proc_items
            ):
                issue_proc_and_related_article_proc_id_list.setdefault(
                    issue_proc_id, []
                ).append(article_proc_id)

        total_to_process = len(
            issue_proc_and_related_article_proc_id_list
        )
        for (
            issue_proc_id,
            article_proc_id_list,
        ) in issue_proc_and_related_article_proc_id_list.items():
            total_processed += 1
            # executa sincronamente a eliminação de registros ArticleProc e Article cujo conteúdo é defeituoso
            task_exclude_invalid_issue_articles(
                issue_proc_id=issue_proc_id,
                username=username,
                user_id=user_id,
                public_api_data=public_api_data,
            )

            task_migrate_and_publish_articles_by_issue.delay(
                user_id=user_id,
                username=username,
                issue_proc_id=issue_proc_id,
                article_proc_id_list=article_proc_id_list,
                status=status,
                force_update=force_update,
                force_migrate_document_records=force_migrate_document_records,
                force_migrate_document_files=force_migrate_document_files,
                qa_api_data=qa_api_data,
                public_api_data=public_api_data,
            )
        task_exec.total_processed = total_processed
        task_exec.total_to_process = total_to_process
        task_exec.finish()

    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        task_exec.finish(exception=e, exc_traceback=exc_traceback)


@celery_app.task(bind=True)
def task_migrate_and_publish_articles_by_issue(
    self,
    user_id=None,
    username=None,
    issue_proc_id=None,
    article_proc_id_list=None,
    status=None,
    force_update=False,
    force_migrate_document_records=False,
    force_migrate_document_files=False,
    qa_api_data=None,
    public_api_data=None,
):
    """
    Migra e publica artigos de um fascículo.

    Executa o pipeline completo de migração para cada artigo:
    migração de registros (``migrate_document_records``), migração de arquivos
    (``migrate_document_files``) e ``ArticleProc.migrate_article``.
    Ao final agenda ``task_publish_issue_articles``.
    """
    task_params = {
        "user_id": user_id,
        "username": username,
        "issue_proc_id": issue_proc_id,
        "article_proc_id_list": article_proc_id_list,
        "status": status,
        "force_update": force_update,
        "force_migrate_document_records": force_migrate_document_records,
        "force_migrate_document_files": force_migrate_document_files,
    }
    task_exec = TaskExecution(
        name="proc.tasks.task_migrate_and_publish_articles_by_issue",
        item=issue_proc_id,
        params=task_params,
    )
    try:
        user = _get_user(user_id, username)
        issue_proc = IssueProc.objects.select_related(
            "collection", "journal_proc"
        ).get(id=issue_proc_id)
        status = tracker_choices.get_valid_status(status, force_update)

        task_exec.item = str(issue_proc)

        total_articles_to_process = 0
        if article_proc_id_list:
            article_procs = ArticleProc.objects.select_related(
                "issue_proc",
            ).filter(id__in=article_proc_id_list)
            total_articles_to_process = article_procs.count()
        else:
            total_migrated_records = issue_proc.migrate_document_records(
                user, force_migrate_document_records
            )
            task_exec.add_number(
                "total_migrated_records", total_migrated_records
            )

            total_migrated_files = issue_proc.migrate_document_files(
                user,
                force_migrate_document_files,
                controller.migrate_issue_files,
            )
            task_exec.add_number(
                "total_migrated_files", total_migrated_files
            )

            article_procs = ArticleProc.select_items(
                issue_proc_id_list=[issue_proc_id],
                status_list=status,
                force_update=force_update,
            )
            total_articles_to_process = article_procs.count()
        task_exec.total_to_process = total_articles_to_process

        total_processed = 0
        exceptions = {}
        for article_proc in article_procs:
            try:
                article = article_proc.migrate_article(user, force_update)
                total_processed += 1
            except Exception as e:
                exc_type, exc_value, exc_traceback = sys.exc_info()
                exceptions[article_proc.pid] = traceback.format_exc()
                task_exec.add_exception(exceptions[article_proc.pid])

        task_exec.total_processed = total_processed
        task_exec.add_number("total_processed", total_processed)

        task_publish_issue_articles.delay(
            user_id=user_id,
            username=username,
            issue_proc_id=issue_proc_id,
            status=status,
            force_update=force_update,
        )

        task_exec.finish()
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        task_exec.finish(exception=e, exc_traceback=exc_traceback)


@celery_app.task(bind=True)
def task_publish_issue_articles(
    self,
    user_id=None,
    username=None,
    issue_proc_id=None,
    status=None,
    force_update=False,
):
    """
    Publica artigos de um fascículo e sincroniza o fascículo no site.

    Para cada WebSiteConfiguration habilitado da coleção:
    1. Publica cada artigo via task_publish_article (síncrono).
    2. Agenda task_sync_issue (assíncrono).
    """
    task_params = {
        "user_id": user_id,
        "username": username,
        "issue_proc_id": issue_proc_id,
        "status": status,
        "force_update": force_update,
    }
    task_exec = TaskExecution(
        name="proc.tasks.task_publish_issue_articles",
        item=f"{issue_proc_id}",
        params=task_params,
    )
    try:
        user = _get_user(user_id, username)
        issue_proc = IssueProc.objects.select_related(
            "collection", "journal_proc", "issue"
        ).get(id=issue_proc_id)

        task_exec.item = f"{issue_proc}"

        status = tracker_choices.get_valid_status(status, force_update)

        articles = (
            ArticleProc.objects.select_related("issue_proc", "sps_pkg")
            .filter(
                issue_proc=issue_proc,
                sps_pkg__pid_v3__isnull=False,
            )
            .values_list("id", flat=True)
        )

        collection = issue_proc.collection
        total_processed = 0
        total_to_process = 0
        for website in WebSiteConfiguration.objects.filter(
            collection=collection, enabled=True
        ):
            api_data = website.get_data(content_type="article")
            website_kind = website.purpose

            query_by_status = Q()
            if website_kind == QA:
                query_by_status = Q(qa_ws_status__in=status)
            elif website_kind == PUBLIC:
                query_by_status = Q(public_ws_status__in=status)

            article_ids_to_publish = articles.filter(query_by_status)
            total_to_process += article_ids_to_publish.count()

            for article_proc_id in article_ids_to_publish:
                try:
                    task_publish_article(
                        user_id=user_id,
                        username=username,
                        website_id=website.id,
                        website_kind=website_kind,
                        article_proc_id=article_proc_id,
                        api_data=api_data,
                        force_update=force_update,
                    )
                    total_processed += 1
                except Exception as e:
                    exc_type, exc_value, exc_traceback = sys.exc_info()
                    task_exec.add_exception(traceback.format_exc())

            task_sync_issue.delay(
                user_id=user_id,
                username=username,
                website_kind=website_kind,
                issue_proc_id=issue_proc_id,
                api_data=api_data,
            )
        task_exec.total_to_process = total_to_process
        task_exec.total_processed = total_processed
        task_exec.finish()
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        task_exec.finish(exception=e, exc_traceback=exc_traceback)


@celery_app.task(bind=True)
def task_sync_issue(
    self,
    user_id=None,
    username=None,
    issue_proc_id=None,
    website_kind=None,
    api_data=None,
):
    """
    Sincroniza a tabela de conteúdo de um fascículo no site (QA ou PUBLIC).

    Chamada de forma assíncrona após ``task_publish_issue_articles``
    para garantir que o fascículo apareça corretamente no TOC do site.
    """
    try:
        user = _get_user(user_id, username)
        issue_proc = IssueProc.objects.get(id=issue_proc_id)
        event = issue_proc.start(user, f"proc.tasks.task_sync_issue {website_kind}")
        if not api_data:
            api_data = get_api_data(issue_proc.collection, "issue", website_kind)
        response = sync_issue(issue_proc, api_data)
        event.finish(user=user, completed=True, detail=response)
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        try:
            event.finish(
                user=user,
                completed=False,
                exception=e,
                exc_traceback=exc_traceback,
            )
        except Exception:
            UnexpectedEvent.create(
                item=f"{issue_proc_id}",
                action="proc.tasks.task_sync_issue",
                e=e,
                exc_traceback=exc_traceback,
                detail={
                    "task": "proc.tasks.task_sync_issue",
                    "user_id": user_id,
                    "username": username,
                    "website_kind": website_kind,
                    "issue_proc_id": issue_proc_id,
                },
            )


@celery_app.task(bind=True)
def task_publish_articles(
    self,
    user_id=None,
    username=None,
    collection_acron=None,
    journal_acron=None,
    issue_folder=None,
    publication_year=None,
    issue_proc_id=None,
    force_update=False,
    status=None,
    verify=False,
    timeout=None,
):
    """
    Agenda publicação de artigos pendentes.

    Seleciona IssueProcs e agenda task_publish_issue_articles para cada um.
    """
    task_params = {
        "user_id": user_id,
        "username": username,
        "collection_acron": collection_acron,
        "journal_acron": journal_acron,
        "issue_folder": issue_folder,
        "publication_year": publication_year,
        "force_update": force_update,
    }
    title = f"{collection_acron}-{journal_acron}-{issue_folder}-{publication_year}"
    task_exec = TaskExecution(
        name="proc.tasks.task_publish_articles",
        item=title,
        params=task_params,
    )
    try:
        issue_procs = IssueProc.select_items(
            collection_acron=collection_acron,
            journal_acron=journal_acron,
            issue_folder=issue_folder,
            publication_year=publication_year,
            issue_proc_id=issue_proc_id,
            force_update=force_update,
            status_list=status,
        )
        total = issue_procs.count()
        task_exec.add_event(f"Publishing articles of {total} issues")

        for issue_proc in issue_procs:
            task_publish_issue_articles.delay(
                user_id=user_id,
                username=username,
                issue_proc_id=issue_proc.id,
                status=status,
                force_update=force_update,
            )
        task_exec.finish()
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            item=title,
            action="proc.tasks.task_publish_articles",
            e=e,
            exc_traceback=exc_traceback,
            detail=task_params,
        )


@celery_app.task(bind=True)
def task_publish_article(
    self,
    user_id=None,
    username=None,
    website_kind=None,
    website_id=None,
    article_proc_id=None,
    api_data=None,
    force_update=None,
    timeout=None,
):
    """
    Publica um artigo individual no site QA ou PUBLIC.

    Após publicação bem-sucedida, agenda task_check_article_webpages.
    """
    user = None
    detail = {"published": False, "available": False}
    article_proc = None
    event = None

    try:
        user = _get_user(user_id, username)
        article_proc = ArticleProc.objects.get(pk=article_proc_id)
        event = article_proc.start(
            user, "publish article / check availability"
        )

        response = article_proc.publish(
            user,
            publish_article,
            content_type="article",
            website_kind=website_kind,
            api_data=api_data,
            force_update=force_update,
        )
        detail["published"] = response.get("completed")
        detail["available"] = False

        if response.get("completed"):
            task_check_article_webpages.delay(
                user_id=user_id,
                username=username,
                collection_id=article_proc.collection.id,
                website_kind=website_kind,
                article_id=article_proc.article.id,
                timeout=timeout,
                force_update=force_update,
                article_proc_id=article_proc_id,
            )

        event.finish(user, detail=detail, completed=True)

    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        try:
            if event and user:
                event.finish(
                    user,
                    exc_traceback=exc_traceback,
                    exception=e,
                    detail=detail,
                )
            else:
                raise e
        except Exception:
            UnexpectedEvent.create(
                e=e,
                exc_traceback=exc_traceback,
                detail={
                    "task": "proc.task.publish_article",
                    "user_id": user_id,
                    "username": username,
                    "website_kind": website_kind,
                    "pid": article_proc.pid if article_proc else None,
                    "article_proc_id": article_proc_id,
                },
            )


############################################
# UTILITIES
############################################


@celery_app.task(bind=True)
def task_fetch_and_create_journal(
    self,
    user_id,
    username,
    collection_acron=None,
    issn_electronic=None,
    issn_print=None,
    force_update=None,
):
    """
    Busca dados de periódico na Core API e cria/atualiza o registro local.

    Utilizado para manter ``Journal`` sincronizado com a Core após migração
    ou quando ``journal.core_synchronized`` é False.
    """
    task_params = {
        "task": "proc.tasks.task_fetch_and_create_journal",
        "user_id": user_id,
        "username": username,
        "collection_acron": collection_acron,
        "issn_electronic": issn_electronic,
        "issn_print": issn_print,
        "force_update": force_update,
    }
    task_exec = TaskExecution(
        name="proc.tasks.task_fetch_and_create_journal",
        item=f"{collection_acron}-{issn_electronic or ''}-{issn_print or ''}",
        params=task_params,
    )
    try:
        user = _get_user(user_id=user_id, username=username)
        fetch_and_create_journal(
            user,
            collection_acron=collection_acron,
            issn_electronic=issn_electronic,
            issn_print=issn_print,
            force_update=force_update,
        )
        task_exec.finish()
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        task_exec.finish(exception=e, exc_traceback=exc_traceback)


@celery_app.task(bind=True)
def task_exclude_invalid_issue_articles(
    self,
    issue_proc_id,
    username=None,
    user_id=None,
    timeout=None,
    public_api_data=None,
):
    """
    Remove artigos duplicados e inconsistentes de um fascículo.

    Executa ``Article.fix_sps_pkg_names`` e ``Article.exclude_invalid_issue_articles``
    para o fascículo associado ao ``IssueProc`` informado.
    Chamada automaticamente por ``task_migrate_and_publish_articles_by_issue``
    antes de iniciar a migração dos artigos.
    """
    try:
        item = issue_proc_id
        detail = None
        event = None
        user = _get_user(user_id=user_id, username=username)
        issue_proc = IssueProc.objects.select_related("issue").get(
            id=issue_proc_id
        )
        item = str(issue_proc)
        event = issue_proc.start(user, "Exclude invalid articles")
        detail = []
        issue = issue_proc.issue
        response = ArticleProc.exclude_invalid_items(user, issue)
        detail.append({"Model": "ArticleProc", "response": response})
        response = Article.exclude_invalid_records(user, issue, response.get("sps_pkg_id_list"), timeout=timeout)
        detail.append({"Model": "Article", "response": response})
        if response.get("deleted_sps_pkg_ids"):
            response = ArticleProc.exclude_invalid_items(user, issue)
            detail.append({"Model": "ArticleProc", "response": response})
        event.finish(user, completed=True, detail=detail)
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        if event:
            event.finish(user, exception=e, exc_traceback=exc_traceback)
            return
        UnexpectedEvent.create(
            item=item,
            action="proc.tasks.task_exclude_invalid_issue_articles",
            e=e,
            exc_traceback=exc_traceback,
            detail=detail,
        )


@celery_app.task(bind=True)
def task_remove_duplicate_issues(
    self,
    user_id=None,
    username=None,
    journal_id=None,
):
    """
    Remove Issues duplicados de um periódico (ou de todos).

    Para cada grupo de duplicatas mantém o registro mais recente e
    redireciona os ``Article`` e ``IssueProc`` associados antes de
    apagar os duplicados.
    """
    task_params = {
        "user_id": user_id,
        "username": username,
        "journal_id": journal_id,
    }
    task_exec = TaskExecution(
        name="proc.tasks.task_remove_duplicate_issues",
        item=f"{journal_id or 'all'}",
        params=task_params,
    )
    try:
        user = _get_user(user_id, username)
        journal = None
        if journal_id:
            journal = Journal.objects.get(id=journal_id)

        duplicates = Issue.get_duplicates(journal)
        task_exec.total_to_process = duplicates.count()
        for duplicated_issue_data in duplicates.iterator():
            try:
                issues = list(
                    Issue.objects.filter(**duplicated_issue_data).order_by(
                        "-updated"
                    )
                )
                keep = issues[0]
                for issue in issues[1:]:
                    try:
                        Article.objects.filter(issue=issue).update(
                            issue=keep
                        )
                        IssueProc.objects.filter(issue=issue).update(
                            issue=keep
                        )
                        issue.delete()
                    except Exception as e:
                        exc_type, exc_value, exc_traceback = sys.exc_info()
                        task_exec.add_exception(
                            {
                                "duplicated_issue_data": duplicated_issue_data,
                                "issue_id": issue.id,
                                "traceback": traceback.format_exc(),
                            }
                        )
                task_exec.total_processed += 1
            except Exception as e:
                exc_type, exc_value, exc_traceback = sys.exc_info()
                task_exec.add_exception(
                    {
                        "duplicated_issue_data": duplicated_issue_data,
                        "traceback": traceback.format_exc(),
                    }
                )
        task_exec.finish()
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        task_exec.finish(exception=e, exc_traceback=exc_traceback)


############################################
# PID TRACKING (CLASSIC WEBSITE)
############################################


@celery_app.task(bind=True)
def task_track_classic_website_article_pids(
    self,
    username,
    user_id=None,
    collection_acron=None,
    timeout=None,
    force_update=None,
):
    """
    Agenda rastreamento de PIDs do site clássico para cada coleção.

    Itera as coleções e agenda
    ``task_track_classic_website_article_pids_for_collection`` para cada uma.
    """
    task_params = {
        "username": username,
        "collection_acron": collection_acron,
        "timeout": timeout,
        "force_update": force_update,
    }
    task_exec = TaskExecution(
        name="proc.tasks.task_track_classic_website_article_pids",
        item=f"{collection_acron or 'all'}",
        params=task_params,
    )
    try:
        user = _get_user(user_id=user_id, username=username)
        for collection in _get_collections(collection_acron):
            task_track_classic_website_article_pids_for_collection.delay(
                username=username,
                user_id=user_id,
                collection_acron=collection.acron,
                timeout=timeout,
                force_update=force_update,
            )
        task_exec.finish()
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        task_exec.finish(exception=e, exc_traceback=exc_traceback)


@celery_app.task(bind=True)
def task_track_classic_website_article_pids_for_collection(
    self,
    username,
    user_id=None,
    collection_acron=None,
    timeout=None,
    force_update=None,
):
    """
    Rastreia PIDs do site clássico para uma coleção e agenda verificação.

    Atualiza ``pid_status`` de cada ``ArticleProc`` via
    ``ClassicWebsiteArticlePidTracker.update_pid_status`` e agenda
    ``task_check_migrated_article`` para os artigos que precisam de
    verificação de URL e conteúdo.
    """
    task_params = {
        "username": username,
        "collection_acron": collection_acron,
        "timeout": timeout,
    }
    task_exec = TaskExecution(
        name="proc.tasks.task_track_classic_website_article_pids_for_collection",
        item=collection_acron,
        params=task_params,
    )
    try:
        user = _get_user(user_id=user_id, username=username)
        collection = Collection.objects.get(acron=collection_acron)
        tracker = ClassicWebsiteArticlePidTracker(user, collection)
        result = tracker.update_pid_status()
        task_exec.add_event(result)

        for article_proc in ArticleProc.items_to_check_url_and_content(
            collection, force_update
        ):
            for website in WebSiteConfiguration.objects.filter(
                collection=collection, enabled=True
            ):
                website_kind = website.purpose
                task_check_article_webpages.delay(
                    user_id=user_id,
                    username=username,
                    collection_id=article_proc.collection.id,
                    website_kind=website_kind,
                    article_id=article_proc.article.id,
                    timeout=timeout,
                    force_update=force_update,
                    article_proc_id=article_proc.id,
                )

        task_exec.finish()
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        task_exec.finish(exception=e, exc_traceback=exc_traceback)


############################################
# AVAILABILITY CHECKS (3-level model)
############################################


@celery_app.task(bind=True)
def task_check_article_webpages(
    self,
    user_id=None,
    username=None,
    article_id=None,
    collection_id=None,
    website_kind=None,
    collection_acron=None,
    timeout=None,
    force_update=None,
    article_proc_id=None,
):
    """
    Cria/atualiza ArticleCollections do artigo e verifica disponibilidade de páginas.

    1. Recupera o Article pelo id.
    2. Garante existência das ArticleCollections via
       ``article.create_or_update_article_collections``.
    3. Delega verificação para ``article.check_availability``, filtrada por
       collection_id e website_kind.
    """
    try:
        user = _get_user(user_id, username)
        event = None
        article_proc = ArticleProc.objects.get(pk=article_proc_id)
        event = article_proc.start(
            user, f"check availability {article_proc.collection} {website_kind}"
        )

        article = article_proc.article
        article.create_or_update_article_collections(user)
        collection = article_proc.collection
        data = {}
        article.check_availability(user, collection_id=collection_id, purpose=website_kind, force_update=force_update)
        responses = [
            article.available_on_classic_website(collection),
            article.available_on_public_website(collection),
        ]
        response = responses[-1]

        data["responses"] = responses
        data["availability"] = article.availability

        for response in responses:
            if response.get("valid"):
                article_proc.set_pid_status(user, response.get("new_pid_status"))
    
        event.finish(user, completed=True, detail=data)
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        if event:
            event.finish(user, exception=e, exc_traceback=exc_traceback)
            return
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "proc.tasks.task_check_article_webpages",
                "article_id": article_id,
                "collection_id": collection_id,
                "website_kind": website_kind,
            },
        )


@celery_app.task(bind=True)
def task_check_article_page_availability(
    self,
    user_id=None,
    username=None,
    webpage_id=None,
    article_metadata=None,
    timeout=None,
    force_update=None,
):
    """
    Verifica disponibilidade de uma única ArticleWebPage.

    Chama ``ArticleWebPage.check_availability`` e propaga o resultado
    automaticamente: Page → ArticleCollection.
    """
    try:
        if not webpage_id:
            raise ValueError("webpage_id must be provided")
        user = _get_user(user_id, username)
        page = ArticleWebPage.objects.get(id=webpage_id)
        page.check_page(
            user, timeout, article_metadata, force_update
        )
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "proc.tasks.task_check_article_page_availability",
                "webpage_id": webpage_id,
            },
        )


@celery_app.task(bind=True)
def task_update_article_proc_availability(
    self,
    user_id=None,
    username=None,
    article_proc_id=None,
    article_collection_id=None,
):
    """
    Callback pós-verificação: atualiza pid_status no ArticleProc.

    Consulta o ``ArticleCollection`` correspondente e, se todas as páginas
    estiverem válidas (status=VALID), define ``pid_status`` como
    PID_STATUS_PUBLIC_VALID via ``ArticleProc.set_pid_status``.
    """
    try:
        user = _get_user(user_id, username)
        article_proc = ArticleProc.objects.select_related(
            "collection", "sps_pkg"
        ).get(pk=article_proc_id)

        art_col = ArticleCollection.objects.get(id=article_collection_id)
        if art_col.is_available:
            article_proc.set_pid_status(
                user, migration_choices.PID_STATUS_PUBLIC_VALID
            )

    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "proc.tasks.task_update_article_proc_availability",
                "article_proc_id": article_proc_id,
                "article_collection_id": article_collection_id,
            },
        )


@celery_app.task(bind=True)
def task_check_articles_availability(
    self,
    username,
    user_id=None,
    issn_print=None,
    issn_electronic=None,
    issue_folder=None,
    publication_year=None,
    article_pid_v3=None,
    collection_acron=None,
    timeout=None,
    force_update=None,
):
    """
    Verificação em lote: busca artigos por filtros e agenda verificação.

    Resolve os artigos que correspondem aos filtros fornecidos, garante a
    existência de ``ArticleCollection`` para cada um e agenda
    ``task_check_article_webpages`` (assíncrono) por artigo.

    Parameters
    ----------
    username / user_id : str / int
        Identificação do usuário executor.
    issn_print / issn_electronic : str, optional
        Filtra por ISSN do periódico (OR lógico entre os dois).
    issue_folder / publication_year : str / int, optional
        Filtra por fascículo ou ano de publicação.
    article_pid_v3 / article_id : str / int, optional
        Filtra por artigo específico.
    collection_acron : str, optional
        Filtra artigos e restringe a verificação à coleção indicada.
    timeout : int, optional
        Timeout HTTP em segundos passado para cada verificação.
    force_update : bool, optional
        Se True, re-verifica mesmo páginas já válidas.
    """
    try:
        user = _get_user(user_id, username)
        article_params = {}
        q = Q()

        if article_pid_v3:
            article_params["sps_pkg__pid_v3"] = article_pid_v3
        if publication_year:
            article_params["issue_proc__issue__publication_year"] = publication_year
        if issue_folder:
            article_params["issue_proc__issue__issue_folder"] = issue_folder
        if collection_acron:
            article_params["collection__acron"] = collection_acron

        q = Q()
        if issn_print:
            q |= Q(
                issue_proc__journal_proc__journal__official_journal__issn_print=issn_print
            )
        if issn_electronic:
            q |= Q(
                issue_proc__journal_proc__journal__official_journal__issn_electronic=issn_electronic
            )

        for article_proc in ArticleProc.objects.filter(
            q, **article_params
        ):
            task_check_article_webpages.delay(
                user_id=user_id,
                username=username,
                article_proc_id=article_proc.id,
                article_id=article_proc.article.id,
                collection_id=article_proc.collection_id,
                timeout=timeout,
                force_update=force_update,
            )

    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        detail = {
            "task": "proc.tasks.task_check_articles_availability",
            "issn_print": issn_print,
            "issn_electronic": issn_electronic,
            "issue_folder": issue_folder,
            "publication_year": publication_year,
            "article_pid_v3": article_pid_v3,
            "article_id": article_id,
            "collection_acron": collection_acron,
            "timeout": timeout,
            "force_update": force_update,
        }
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail=detail,
        )


############################################
# CLASSIC WEBSITE CHECK (MIGRATION)
############################################


@celery_app.task(bind=True)
def task_check_migrated_article(
    self,
    user_id=None,
    username=None,
    article_proc_id=None,
    timeout=None,
    force_update=None,
):
    """
    Confronta metadados do artigo com a página do site clássico.

    Verifica cada página CLASSIC do artigo via ``Article.check_availability``
    e mapeia o ``webpage_status`` para ``pid_status`` no ``ArticleProc``.

    O ``pid_status`` reflete o resultado mais recente da verificação:
    CLASSIC_MATCHED, CLASSIC_MISMATCHED, CLASSIC_FOUND ou CLASSIC_NOT_FOUND.
    """
    try:
        user = _get_user(user_id, username)
        article_proc = ArticleProc.objects.select_related(
            "collection", "sps_pkg", "issue_proc__journal_proc"
        ).get(pk=article_proc_id)

        article = article_proc.article
        if not article:
            raise ValueError(
                f"ArticleProc {article_proc_id} has no article"
            )
        
        article.create_or_update_article_collections(user)
        article.check_availability(user)

        logging.info("pageslist(article.webpages): {}".format(list(article.webpages)))
        response = article.available_on_classic_website(article_proc.collection)
        if response.get("valid"):
            article_proc.set_pid_status(user, response.get("new_pid_status"))
        logging.info(
            f"Checked classic website for ArticleProc {article_proc_id}: {response}"
        )

        response = article.available_on_public_website(article_proc.collection)
        if response.get("valid"):
            article_proc.set_pid_status(user, response.get("new_pid_status"))
        logging.info(
            f"Checked public website for ArticleProc {article_proc_id}: {response}"
        )

    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "proc.tasks.task_check_migrated_article",
                "article_proc_id": article_proc_id,
            },
        )
