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
              └─ task_sync_issue (publica artigos + sincroniza issue no site)
                  └─ task_publish_article (por artigo)

  Rastreamento de PIDs do site clássico:
    task_track_classic_website_article_pids
      └─ task_track_classic_website_article_pids_for_collection (por coleção)
          └─ task_track_article_page_url_and_content (por artigo)

  Utilitários:
    task_fetch_and_create_journal
    task_exclude_article_repetition_by_issue
    task_remove_duplicate_issues
"""

import logging
import sys
import traceback
import json

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from article.models import Article
from journal.models import Journal
from issue.models import Issue
from collection.choices import PUBLIC, QA
from collection.models import Collection, WebSiteConfiguration
from config import celery_app
from migration import controller
from migration import choices as migration_choices
from proc.controller import (
    create_or_update_migrated_issue,
    create_or_update_migrated_journal,
    fetch_and_create_journal,
    migrate_issue,
)
from proc.article_controller import ClassicWebsiteArticlePidTracker
from proc.models import ArticleProc, IssueProc, JournalProc
from publication.models import ArticleAvailability
from publication.api.document import publish_article
from publication.api.issue import publish_issue, sync_issue
from publication.api.journal import publish_journal
from publication.api.publication import get_api_data
from tracker import choices as tracker_choices
from tracker.models import TaskTracker, UnexpectedEvent

User = get_user_model()

class NothingToProcess(Exception):
    """Sinaliza que não há itens pendentes para processamento."""
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
        self.exceptions.append({"type": str(type(exception)), "message": str(exception)})

    def add_event(self, event):
        if isinstance(event, list):
            self.events.extend(event)
        else:
            self.events.append(event)

    def add_number(self, name, number):
        self.stats[name] = number

    def finish(self, exception=None, exc_traceback=None):
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
        # adiciona este tratamento para garantir que o detail seja serializável, evitando que a task fique travada tentando salvar um detail com dados não serializáveis
        try:
            json.dumps(detail)
        except Exception as exc_detail:
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
    """Obtém usuário por ID ou username. Retorna None e registra evento se falhar."""
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
    """Retorna iterator de coleções filtradas por acrônimo, ou todas se None."""
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
    """Descontinuada. Usar task_migrate_and_publish_journals/issues/articles."""
    logging.info("task_migrate_and_publish is discontinued")
    logging.info("Use task_migrate_and_publish_journals")
    logging.info("Use task_migrate_and_publish_issues")
    logging.info("Use task_migrate_and_publish_articles")


############################################
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
    Orquestra migração e publicação de periódicos.

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

    1. Importa dados do site clássico (create_or_update_migrated_journal)
    2. Para cada JournalProc com status pendente:
       - Cria/atualiza o Journal
       - Sincroniza com Core API (se necessário)
       - Agenda publicação nos sites QA e PUBLIC
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
            user,
            collection,
            classic_website,
            force_update,
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

        for journal_proc in items_to_process:
            try:
                detail = {}
                event = journal_proc.start(user, "migrate journal")
                # cria ou atualiza Journal e atualiza journal_proc
                completed = journal_proc.create_or_update_item(
                    user, force_update, controller.create_or_update_journal
                )
                # atualiza Journal e atualiza journal_proc com dados do Core
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
                task_exec.total_processed += 1
            except Exception as e:
                exc_type, exc_value, exc_traceback = sys.exc_info()
                if event:
                    event.finish(
                        user,
                        completed=False,
                        exception=e,
                        exc_traceback=exc_traceback,
                        detail=detail
                    )
                else:
                    UnexpectedEvent.create(
                        action="proc.tasks.task_migrate_and_publish_journals_by_collection",
                        item=f"{journal_proc}",
                        e=e,
                        exc_traceback=exc_traceback,
                        detail=detail,
                    )
        task_exec.finish()
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        try:
            task_exec.finish(
                exception=e,
                exc_traceback=exc_traceback,
            )
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

    Para cada coleção e website_kind, seleciona os JournalProcs pendentes
    e agenda task_publish_journal individualmente.
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
                        task_exec.total_processed += 1
                    except Exception as e:
                        exc_type, exc_value, exc_traceback = sys.exc_info()
                        UnexpectedEvent.create(
                            item=str(journal_proc),
                            action="task_publish_journal",
                            e=e,
                            exc_traceback=exc_traceback,
                            detail=task_params,
                        )
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
    """Publica um periódico individual no site QA ou PUBLIC via API."""
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
                user, completed=False, exception=e, exc_traceback=exc_traceback
            )
        except Exception as ignored_exception:
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
    Orquestra migração e publicação de fascículos.

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
            detail=task_params
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

    1. Importa dados de fascículos do site clássico
    2. Para cada IssueProc com status pendente:
       - Executa migrate_issue
       - Agenda publicação nos sites QA e PUBLIC
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

        task_exec.add_event("Read issue.id")
        # obtém os dados do site clássico
        classic_website = controller.get_classic_website(collection_acron)
        collection = Collection.objects.get(acron=collection_acron)
        create_or_update_migrated_issue(
            user,
            collection,
            classic_website,
            force_update,
        )
        
        # filtra os issues para processar
        task_exec.add_event("Select issue to process")
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
            query_by_status,
            collection=collection,
            **params,
        )
        task_exec.total_to_process = items.count()
        
        if not task_exec.total_to_process:
            task_exec.finish()
            return

        qa_api_data = get_api_data(collection, "issue", "QA")
        public_api_data = get_api_data(collection, "issue", "PUBLIC")

        for issue_proc in items:
            try:
                # issue_proc -> issue
                task_exec.add_event("issue_proc -> issue")
                migrate_issue(user, issue_proc, force_update)

                if qa_api_data and not qa_api_data.get("error"):
                    task_exec.add_event("Schedule to publish issue on QA")
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
                    task_exec.add_event("Schedule to publish issue on PUBLIC")
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
            task_exec.finish(
                exception=e,
                exc_traceback=exc_traceback,
            )
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

    Para cada coleção e website_kind, seleciona IssueProcs pendentes
    e agenda task_publish_issue individualmente.
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
    """Publica um fascículo individual no site QA ou PUBLIC via API."""
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
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        try:
            event.finish(
                user=user,
                completed=False,
                exception=e,
                exc_traceback=exc_traceback,
            )
        except Exception as ignored_exception:
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
    Orquestra migração e publicação de artigos.

    Seleciona fascículos ou periódicos conforme os filtros e agenda
    task_migrate_and_publish_articles_by_journal para cada periódico.
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
            task_exec.add_event(_("Select issues by {} and {}").format(issue_folder, publication_year))
            selected_issue_procs = IssueProc.select_items(
                collection_acron_list=collection_acron_list,
                journal_acron_list=journal_acron_list,
                publication_year=publication_year,
                issue_folder=issue_folder,
                status_list=status,
                force_update=force_migrate_document_records or force_migrate_document_files,
                to_migrate_articles=True,
            )
            issue_proc_ids = selected_issue_procs.values_list("journal_proc_id", "id").distinct()
            
            for journal_proc_id, issue_proc_id in issue_proc_ids:
                items_to_process.setdefault(journal_proc_id, []).append(issue_proc_id)
        else:
            task_exec.add_event(_("Select journals by collection"))
            journal_proc_ids = JournalProc.select_items(
                collection_acron_list=collection_acron_list,
                journal_acron_list=journal_acron_list,
            ).values_list("id", flat=True)
            items_to_process = {journal_proc_id: None for journal_proc_id in journal_proc_ids}

        total_journals_to_process = len(items_to_process)
        task_exec.add_number("total_journals_to_process", total_journals_to_process)

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
            task_exec.finish(
                exception=e,
                exc_traceback=exc_traceback,
            )
        except Exception as ignored_exception:
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

    1. Importa registros de acron_id do site clássico
    2. Identifica fascículos e artigos pendentes
    3. Agenda task_migrate_and_publish_articles_by_issue para cada fascículo
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
        name=f"proc.tasks.task_migrate_and_publish_articles_by_journal",
        item=title,
        params=task_params,
    )
    try:
        if not journal_proc_id:
            raise ValueError("journal_proc_id is required")

        journal_proc = JournalProc.objects.get(id=journal_proc_id)

        user = _get_user(user_id, username)

        task_exec.add_event("Read journal acron id file")
        response = controller.import_journal_acron_id_records(
            user,
            ArticleProc,
            journal_proc,
            force_update=force_import_acron_id_file,
        )

        qa_api_data = get_api_data(journal_proc.collection, "issue", "QA")
        public_api_data = get_api_data(journal_proc.collection, "issue", "PUBLIC")
        total_processed = 0
        total_to_process = 0

        selected_issue_procs = None
        if issue_proc_id_list:
            issue_proc_and_related_article_proc_id_list = {
                issue_proc_id: [] for issue_proc_id in issue_proc_id_list
            }
        else:
            # identifica os issue_procs para processar com base nos status
            selected_issue_procs = IssueProc.select_items(
                journal_proc_id_list=[journal_proc_id],
                status_list=status,
                force_update=force_migrate_document_records or force_migrate_document_files,
                to_migrate_articles=True,
            )
            issue_proc_id_list = list(selected_issue_procs.values_list("id", flat=True))
            issue_proc_and_related_article_proc_id_list = {
                issue_proc_id: [] for issue_proc_id in (issue_proc_id_list or [])
            }

            # identifica os article_procs e respectivo issue_proc_id para processar com base nos status dos article_proc
            selected_article_proc_items = ArticleProc.select_items(
                journal_proc_id_list=[journal_proc_id],
                exclude_issue_proc_id_list=list(issue_proc_id_list),
                status_list=status,
                force_update=force_update,
            ).values_list("issue_proc_id", "id").distinct()

            for issue_proc_id, article_proc_id in selected_article_proc_items:
                issue_proc_and_related_article_proc_id_list.setdefault(issue_proc_id, []).append(article_proc_id)

        total_to_process = len(issue_proc_and_related_article_proc_id_list)
        for issue_proc_id, article_proc_id_list in issue_proc_and_related_article_proc_id_list.items():
            total_processed += 1
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
        task_exec.finish(
            exception=e,
            exc_traceback=exc_traceback,
        )


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

    1. Remove artigos duplicados (task_exclude_article_repetition_by_issue)
    2. Migra registros e arquivos do site clássico (se necessário)
    3. Migra cada artigo (article_proc.migrate_article)
    4. Agenda task_sync_issue para QA e PUBLIC
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
        name=f"proc.tasks.task_migrate_and_publish_articles_by_issue",
        item=issue_proc_id,
        params=task_params,
    )
    try:
        user = _get_user(user_id, username)
        issue_proc = IssueProc.objects.select_related(
            "collection", "journal_proc",
        ).get(id=issue_proc_id)
        status = tracker_choices.get_valid_status(status, force_update)

        task_exec.item = str(issue_proc)

        # corrige defeito de repetição de artigos, executando de forma síncrona
        task_exclude_article_repetition_by_issue(
            issue_proc_id=issue_proc_id,
            username=username,
            user_id=user_id,
        )

        if article_proc_id_list:
            # supõe-se que os registros e arquivos já foram migrados
            # (issue_proc.docs_status e issue_proc.files_status estão como DONE)
            total_articles_to_process = len(article_proc_id_list)
            article_procs = ArticleProc.objects.select_related(
                "issue_proc",
            ).filter(
                id__in=article_proc_id_list
            )
        else:
            task_exec.add_event("Migrate document records")
            total_migrated_records = issue_proc.migrate_document_records(user, force_migrate_document_records)
            task_exec.add_number("total_migrated_records", total_migrated_records)

            task_exec.add_event("Migrate document files")
            total_migrated_files = issue_proc.migrate_document_files(
                user, force_migrate_document_files, controller.migrate_issue_files
            )
            task_exec.add_number("total_migrated_files", total_migrated_files)

            task_exec.add_event("Select articles to migrate")
            article_procs = ArticleProc.select_items(
                issue_proc_id_list=[issue_proc_id],
                status_list=status,
                force_update=force_update,
            )
            total_articles_to_process = article_procs.count()
        task_exec.total_to_process = total_articles_to_process

        task_exec.add_event("Migrate articles")
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
            
        article_ids_to_publish = ArticleProc.objects.select_related(
            "issue_proc", "sps_pkg",
        ).filter(
            Q(qa_ws_status__in=status) | Q(public_ws_status__in=status),
            issue_proc=issue_proc,
            sps_pkg__pid_v3__isnull=False,
        ).values_list("id", flat=True)
        total_articles_to_publish = article_ids_to_publish.count()
        task_exec.add_number("total_articles_to_publish", total_articles_to_publish)

        for website_label in (QA, PUBLIC):
            task_exec.add_event(f"Schedule Publish articles / sync issue tasks for {website_label}")
            task_sync_issue.apply_async(
                kwargs=dict(
                    user_id=user_id,
                    username=username,
                    issue_proc_id=issue_proc.id,
                    website_kind=website_label,
                    status=status,
                    force_update=force_update,
                )
            )

        task_exec.finish()
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        task_exec.finish(
            exception=e,
            exc_traceback=exc_traceback,
        )


@celery_app.task(bind=True)
def task_sync_issue(
    self,
    user_id=None,
    username=None,
    issue_proc_id=None,
    website_kind=None,
    status=None,
    force_update=False,
):
    """
    Publica artigos de um fascículo e sincroniza o fascículo no site.

    1. Publica cada artigo pendente via task_publish_article (síncrono)
    2. Sincroniza o fascículo no site via sync_issue
    """
    task_params = {
        "user_id": user_id,
        "username": username,
        "issue_proc_id": issue_proc_id,
        "website_kind": website_kind,
        "status": status,
        "force_update": force_update,
    }
    task_exec = TaskExecution(
        name="proc.tasks.task_sync_issue",
        item=f"{issue_proc_id}",
        params=task_params,
    )
    try:
        user = _get_user(user_id, username)
        issue_proc = IssueProc.objects.select_related(
            "collection", "journal_proc", "issue"
        ).get(id=issue_proc_id)
        
        task_exec.item = f"{issue_proc} {website_kind}"
        
        status = tracker_choices.get_valid_status(status, force_update)
        task_exec.add_event(f"Publishing articles for {website_kind} with status {status}")

        query_by_status = Q()
        if website_kind == QA:
            query_by_status = Q(qa_ws_status__in=status)
        elif website_kind == PUBLIC:
            query_by_status = Q(public_ws_status__in=status)

        article_ids_to_publish = ArticleProc.objects.select_related(
            "issue_proc", "sps_pkg",
        ).filter(
            query_by_status,
            issue_proc=issue_proc,
            sps_pkg__pid_v3__isnull=False,
        ).values_list("id", flat=True)

        task_exec.total_to_process = article_ids_to_publish.count()
        total_processed = 0

        api_data = get_api_data(issue_proc.collection, "article", website_kind)
        if not api_data or api_data.get("error"):
            task_exec.add_event(f"API data not available for {website_kind} {api_data}")
            task_exec.finish()
            return

        for article_proc_id in article_ids_to_publish:
            try:
                # executa de forma síncrona para evitar muitos processos em paralelo, o que pode causar lentidão e instabilidade no ambiente de origem (ex: site clássico)
                task_publish_article(
                    user_id=user_id,
                    username=username,
                    website_kind=website_kind,
                    article_proc_id=article_proc_id,
                    api_data=api_data,
                    force_update=force_update,
                )
                total_processed += 1
            except Exception as e:
                exc_type, exc_value, exc_traceback = sys.exc_info()
                task_exec.add_exception(traceback.format_exc())
        task_exec.total_processed = total_processed

        api_data = get_api_data(issue_proc.collection, "issue", website_kind)
        if not api_data or api_data.get("error"):
            task_exec.add_event(f"API data not available for {website_kind} {api_data}")
            task_exec.finish()
            return

        task_exec.add_event(f"Syncing issue in {website_kind} website")
        sync_issue(issue_proc, api_data)
        task_exec.add_event(f"Issue synced in {website_kind} website")
        
        task_exec.finish()
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        task_exec.finish(
            exception=e,
            exc_traceback=exc_traceback,
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
    force_update=False,
    verify=False,
):
    """
    Agenda publicação de artigos pendentes nos sites QA e PUBLIC.

    Para cada coleção e website_kind, seleciona ArticleProcs pendentes
    e agenda task_publish_article individualmente (assíncrono).
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
    try:
        params = {}
        total_scheduled = 0

        if journal_acron:
            params["issue_proc__journal_proc__acron"] = journal_acron
        if issue_folder:
            params["issue_proc__issue_folder"] = issue_folder
        if publication_year:
            params["issue_proc__issue__publication_year"] = publication_year

        for collection in _get_collections(collection_acron):
            for website_kind in (QA, PUBLIC):
                api_data = get_api_data(collection, "article", website_kind)
                if not api_data or api_data.get("error"):
                    continue
                api_data["verify"] = verify

                task_exec = TaskExecution(
                    name="proc.tasks.task_publish_articles",
                    item=f"{title} {website_kind}",
                    params=task_params,
                )
                items_to_publish = ArticleProc.items_to_publish(
                    website_kind=website_kind,
                    content_type="article",
                    collection=collection,
                    force_update=force_update,
                    params=params,
                )
                total_scheduled = 0
                task_exec.total_to_process = items_to_publish.count()
                for article_proc in items_to_publish:
                    task_publish_article.delay(
                        user_id=user_id,
                        username=username,
                        website_kind=website_kind,
                        article_proc_id=article_proc.id,
                        api_data=api_data,
                        force_update=force_update,
                    )
                    total_scheduled += 1
                task_exec.total_processed = total_scheduled
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
    article_proc_id=None,
    api_data=None,
    force_update=None,
):
    """
    Publica um artigo individual no site QA ou PUBLIC e verifica disponibilidade.

    1. Publica o artigo via API (article_proc.publish)
    2. Se publicação OK, verifica disponibilidade das URLs (check_availability)
       usando o modelo legado ArticleAvailability
    """
    user = None
    detail = {"published": False, "available": False}
    article_proc = None
    event = None
    
    try:
        user = _get_user(user_id, username)
        article_proc = ArticleProc.objects.get(pk=article_proc_id)
        event = article_proc.start(user, "publish article / check availability")
        
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
            website_url = WebSiteConfiguration.objects.filter(
                collection=article_proc.collection,
                purpose=website_kind,
            ).values_list("url", flat=True).first()

            detail["available"] = article_proc.article.check_availability(
                user,
                website_url,
                ArticleAvailability,
                published_by="MIGRATION",
                publication_rule="MIGRATION",
            )
            
        event.finish(user, detail=detail, completed=True)
        
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        try:
            if event and user:
                event.finish(user, exc_traceback=exc_traceback, exception=e, detail=detail)
            else:
                raise e
        except Exception as ignored_exception:
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
    """Busca dados de periódico na Core API e cria/atualiza o registro local."""
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
        task_exec.finish(
            exception=e,
            exc_traceback=exc_traceback,
        )

###############################


@celery_app.task(bind=True)
def task_exclude_article_repetition_by_issue(self, issue_proc_id, username=None, user_id=None, timeout=None):
    """
    Remove artigos duplicados e inconsistentes de um fascículo.

    Para o IssueProc indicado:
    1. Corrige nomes de sps_pkg de artigos de suplemento do fascículo que
       estejam sem o sufixo "-s" (fix_sps_pkg_names).
    2. Exclui artigos "inconvenientes" — duplicatas ou registros que não
       devem estar associados ao fascículo (exclude_inconvenient_articles).

    Args:
        issue_proc_id: ID do IssueProc a processar.
        username: Nome do usuário responsável pela operação.
        user_id: ID do usuário responsável pela operação.
        timeout: Tempo máximo (segundos) para a etapa de exclusão; None = sem limite.
    """
    task_params = {
        "issue_proc_id": issue_proc_id,
    }
    issue_proc_str = str(issue_proc_id)
    task_exec = TaskExecution(
        name="task_exclude_article_repetition_by_issue",
        item=issue_proc_str,
        params=task_params,
    )
    try:
        user = _get_user(user_id=user_id, username=username)
        issue_proc = IssueProc.objects.select_related(
            "issue",
        ).get(id=issue_proc_id)
        issue = issue_proc.issue

        task_exec.item = str(issue_proc)
        issue_proc_str = str(issue_proc)

        response = Article.fix_sps_pkg_names(issue)
        task_exec.add_event(f"fixed sps_pkg_names: {response}")

        # Remove artigos duplicados ou indevidos; propaga eventos, números e exceções
        results = Article.exclude_inconvenient_articles(issue, user, timeout)
        for event in results["events"]:
            task_exec.add_event(event)
        for key, value in results["numbers"].items():
            task_exec.add_number(key, value)
        for exc in results["exceptions"]:
            task_exec.add_exception(exc)

        task_exec.finish()
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        try:
            task_exec.finish(
                exception=e,
                exc_traceback=exc_traceback,
            )
        except Exception:
            UnexpectedEvent.create(
                item=issue_proc_str,
                action="proc.tasks.task_exclude_article_repetition_by_issue",
                e=e,
                exc_traceback=exc_traceback,
                detail=task_params,
            )


@celery_app.task(bind=True)
def task_remove_duplicate_issues(
    self,
    user_id=None,
    username=None,
    journal_id=None,
):
    """
    Remove Issue duplicados.
    
    Args:
        dry_run: Se True, apenas identifica duplicatas sem remover.
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
        stats = {}
        journal = None
        if journal_id:
            journal = Journal.objects.get(id=journal_id)
        
        duplicates = Issue.get_duplicates(journal)
        stats["total_duplicated_issues"] = duplicates.count()
        task_exec.total_to_process = stats["total_duplicated_issues"]
        duplicated_issues = []
        for duplicated_issue_data in duplicates.iterator():
            try:
                duplicated_issues.append(duplicated_issue_data)
                issues = list(Issue.objects.filter(**duplicated_issue_data).order_by("-updated"))
                keep = issues[0]
                task_exec.add_event(f"Remove duplicated Issues, (keeping {keep})")
                for issue in issues[1:]:
                    try:
                        # Migra artigos para o Issue mantido
                        Article.objects.filter(issue=issue).update(issue=keep)
                        # Atualiza IssueProc se existir
                        IssueProc.objects.filter(issue=issue).update(issue=keep)
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


@celery_app.task(bind=True)
def task_track_classic_website_article_pids(
    self,
    username,
    user_id=None,
    collection_acron=None,
    timeout=None,
):
    """
    Orquestra o rastreamento de PIDs de artigos do site clássico.

    Agenda task_track_classic_website_article_pids_for_collection
    para cada coleção (ou para a coleção especificada).
    """
    task_params = {
        "username": username,
        "collection_acron": collection_acron,
        "timeout": timeout,
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
    force_check=None,
):
    """
    Rastreia PIDs e verifica URLs/conteúdo dos artigos de uma coleção.

    1. Reconcilia PIDs do site clássico com ArticleProcs
       (ClassicWebsiteArticlePidTracker.update_pid_status)
    2. Para cada artigo com status pendente de verificação, agenda
       task_track_article_page_url_and_content
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

        for item in ArticleProc.items_to_check_url_and_content(collection, force_check):
            task_track_article_page_url_and_content.delay(
                user_id=user_id,
                username=username,
                item_id=item.id,
                timeout=timeout,
            )
        

        task_exec.finish()
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        task_exec.finish(exception=e, exc_traceback=exc_traceback)


@celery_app.task(bind=True)
def task_track_article_page_url_and_content(
    self,
    username,
    user_id=None,
    item_id=None,
    timeout=None,
    force_update=None,
):
    """
    Verifica URL e conteúdo de um artigo individual.

    Chama ArticleProc.check_published_pid_v2, que verifica se o artigo
    está acessível no site clássico e no site público, comparando o
    conteúdo da página com os metadados do artigo.
    """
    task_params = {
        "username": username,
        "item_id": item_id,
        "timeout": timeout,
        "force_update": force_update,
    }
    task_exec = TaskExecution(
        name="proc.tasks.task_track_article_page_url_and_content",
        item=f"{item_id}",
        params=task_params,
    )

    try:
        user = _get_user(user_id=user_id, username=username)

        item = ArticleProc.objects.get(id=item_id)
        task_exec.item = str(item)
        item.check_published_pid_v2(user, timeout=timeout, force_update=force_update)
        task_exec.finish()
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        task_exec.finish(exception=e, exc_traceback=exc_traceback)