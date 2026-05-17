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
    task_check_classic_website_article

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

from article.models import Article, ArticleWebPage
from article import choices as article_choices
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

    Uso típico::

        task_exec = TaskExecution(name="minha.task", item="col-jrn", params={...})
        try:
            # lógica da task
            task_exec.total_to_process = n
            for item in items:
                process(item)
                task_exec.total_processed += 1
            task_exec.finish()
        except Exception as e:
            task_exec.finish(exception=e, exc_traceback=...)

    Attributes:
        params: Dicionário de parâmetros da task (persistido no detail).
        task_tracker: Instância de TaskTracker subjacente.
        events: Lista de strings descritivas acumuladas durante execução.
        stats: Dicionário nome→número com métricas coletadas.
        exceptions: Lista de dicionários {"type": ..., "message": ...}.
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
        """Registra uma exceção capturada (sem interromper a task)."""
        self.exceptions.append({"type": str(type(exception)), "message": str(exception)})

    def add_event(self, event):
        """Registra um ou mais eventos descritivos (string ou lista de strings)."""
        if isinstance(event, list):
            self.events.extend(event)
        else:
            self.events.append(event)

    def add_number(self, name, number):
        """Registra uma métrica numérica no dicionário ``stats``."""
        self.stats[name] = number

    def finish(self, exception=None, exc_traceback=None):
        """
        Persiste o resultado da execução no TaskTracker.

        Monta o ``detail`` com params, stats, events e exceptions.
        Caso o ``detail`` não seja serializável como JSON (ex: objetos
        lazy translation), faz fallback convertendo cada valor para string.

        Args:
            exception: Exceção capturada (se houver).
            exc_traceback: Traceback associado à exceção.
        """
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
    """
    Obtém usuário por ID ou username.

    Retorna None se ambos forem None ou se o usuário não for encontrado.
    Em caso de erro, registra UnexpectedEvent e retorna None.
    """
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
    """
    Retorna iterator de coleções filtradas por acrônimo, ou todas se None.

    Em caso de erro, registra UnexpectedEvent e retorna lista vazia.
    """
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
    """
    Descontinuada. Usar task_migrate_and_publish_journals,
    task_migrate_and_publish_issues e task_migrate_and_publish_articles.
    """
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
    Ponto de entrada para migração e publicação de periódicos.

    Itera sobre as coleções selecionadas e agenda
    ``task_migrate_and_publish_journals_by_collection`` (assíncrono)
    para cada uma.
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

    Etapas:
    1. Importa dados do site clássico (create_or_update_migrated_journal).
    2. Filtra JournalProcs com status pendente (migration, qa_ws, public_ws).
    3. Para cada JournalProc:
       a. Cria/atualiza o Journal via controller.
       b. Se necessário, sincroniza com a Core API (fetch_and_create_journal).
       c. Agenda task_publish_journal para QA e PUBLIC.
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

    Para cada coleção e website_kind, seleciona JournalProcs com status
    pendente (via ``JournalProc.items_to_publish``) e agenda
    ``task_publish_journal`` individualmente.

    Não executa migração — apenas publicação.
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
    """
    Publica um periódico individual no site QA ou PUBLIC via API.

    Delega para ``journal_proc.publish(publish_journal, ...)``.
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
    Ponto de entrada para migração e publicação de fascículos.

    Itera sobre as coleções selecionadas e agenda
    ``task_migrate_and_publish_issues_by_collection`` (assíncrono)
    para cada uma.
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

    Etapas:
    1. Importa dados de fascículos do site clássico
       (create_or_update_migrated_issue).
    2. Filtra IssueProcs com status pendente (migration, docs, files,
       qa_ws, public_ws).
    3. Para cada IssueProc:
       a. Executa migrate_issue (cria/atualiza Issue).
       b. Agenda task_publish_issue para QA e PUBLIC.
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

    Para cada coleção e website_kind, seleciona IssueProcs com status
    pendente (via ``IssueProc.items_to_publish``) e agenda
    ``task_publish_issue`` individualmente.

    Não executa migração — apenas publicação.
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

    Delega para ``issue_proc.publish(publish_issue, ...)``.
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
        event.finish()
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
    Ponto de entrada para migração e publicação de artigos.

    Estratégia de seleção:
    - Se ``publication_year`` ou ``issue_folder`` fornecidos: seleciona
      IssueProcs específicos e agrupa por journal_proc_id.
    - Caso contrário: seleciona todos os JournalProcs das coleções.

    Agenda ``task_migrate_and_publish_articles_by_journal`` para cada
    periódico identificado.
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

    Etapas:
    1. Importa registros de acron_id do site clássico
       (controller.import_journal_acron_id_records).
    2. Identifica fascículos a processar:
       - Se ``issue_proc_id_list`` fornecida: usa diretamente.
       - Senão: seleciona IssueProcs com status pendente e complementa
         com ArticleProcs pendentes de issues já processados.
    3. Agenda ``task_migrate_and_publish_articles_by_issue`` para cada
       fascículo.
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

    Etapas:
    1. Remove artigos duplicados/inconsistentes via
       ``task_exclude_invalid_issue_articles`` (síncrono).
    2. Se ``article_proc_id_list`` fornecida: usa diretamente (pressupõe
       que registros e arquivos já foram migrados).
       Senão: migra registros e arquivos do site clássico, depois seleciona
       ArticleProcs pendentes.
    3. Migra cada artigo (``article_proc.migrate_article``).
    4. Agenda ``task_publish_issue_articles`` para publicação e sincronização.
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
        task_exclude_invalid_issue_articles(
            issue_proc_id=issue_proc_id,
            username=username,
            user_id=user_id,
            public_api_data=public_api_data
        )

        total_articles_to_process = 0
        if article_proc_id_list:
            # supõe-se que os registros e arquivos já foram migrados
            # (issue_proc.docs_status e issue_proc.files_status estão como DONE)
            article_procs = ArticleProc.objects.select_related(
                "issue_proc",
            ).filter(
                id__in=article_proc_id_list
            )
            total_articles_to_process = article_procs.count()
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
        task_exec.add_number("total_processed", total_processed)

        task_exec.add_event(f"Schedule article publication {issue_proc} ({total_processed})")
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
        task_exec.finish(
            exception=e,
            exc_traceback=exc_traceback,
        )


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
    1. Filtra ArticleProcs com pid_v3 e status pendente no website_kind.
    2. Publica cada artigo via ``task_publish_article`` — chamada direta
       (síncrona), não ``.delay()``, para evitar sobrecarga no ambiente
       de origem (ex: site clássico).
    3. Agenda ``task_sync_issue`` (assíncrono) para sincronizar o
       fascículo no site.
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
        task_exec.add_event(f"Publishing {issue_proc} articles which status is {status}")

        articles = ArticleProc.objects.select_related(
            "issue_proc", "sps_pkg",
        ).filter(
            issue_proc=issue_proc,
            sps_pkg__pid_v3__isnull=False,
        ).values_list("id", flat=True)

        collection = issue_proc.collection
        total_processed = 0
        total_to_process = 0
        for website in WebSiteConfiguration.objects.filter(
            collection=collection,
            enabled=True,
        ):
            api_data = website.get_data(content_type="article")
            website_kind = website.purpose
        
            query_by_status = Q()
            if website_kind == QA:
                query_by_status = Q(qa_ws_status__in=status)
            elif website_kind == PUBLIC:
                query_by_status = Q(public_ws_status__in=status)

            article_ids_to_publish = articles.filter(
                query_by_status
            )
            total_to_process += article_ids_to_publish.count()

            for article_proc_id in article_ids_to_publish:
                # executa de forma síncrona para evitar muitos processos em paralelo, o que pode causar lentidão e instabilidade no ambiente de origem (ex: site clássico)
                try:
                    # publica (síncrono dentro de task_publish_article)
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

            task_exec.add_event(f"Schedule sync_issue {issue_proc} {website_kind}")
            task_sync_issue.delay(
                user_id=user_id,
                username=username,
                website_kind=website_kind,
                issue_proc_id=issue_proc_id,
                api_data=api_data,
            )
            task_exec.add_event(f"Scheduled sync_issue {issue_proc} {website_kind}")
        task_exec.total_to_process = total_to_process
        task_exec.total_processed = total_processed
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
    api_data=None,
):
    """
    Sincroniza um fascículo no site (QA ou PUBLIC).

    Chama ``sync_issue(issue_proc, api_data)`` para atualizar o
    fascículo no website após a publicação dos artigos.

    Nota: a docstring original repetia incorretamente a descrição de
    task_publish_issue_articles. Esta task apenas sincroniza o fascículo.
    """
    task_params = {
        "user_id": user_id,
        "username": username,
        "issue_proc_id": issue_proc_id,
        "website_kind": website_kind,
    }
    task_exec = TaskExecution(
        name="proc.tasks.task_sync_issue",
        item=f"{issue_proc_id}",
        params=task_params,
    )
    try:
        user = _get_user(user_id, username)
        issue_proc = IssueProc.objects.get(id=issue_proc_id)
        task_exec.item = f"{issue_proc}"
        task_exec.add_event(f"Syncing {issue_proc} {website_kind} website")
        sync_issue(issue_proc, api_data)
        task_exec.add_event(f"Issue synced {website_kind} website")
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
    issue_proc_id=None,
    force_update=False,
    status=None,
    verify=False,
    timeout=None,
):
    """
    Agenda publicação de artigos pendentes nos sites QA e PUBLIC.

    Seleciona IssueProcs pelos filtros e agenda
    ``task_publish_issue_articles`` para cada um.

    Não executa migração — apenas publicação.
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

    Etapas:
    1. Publica o artigo via ``article_proc.publish(publish_article, ...)``.
    2. Se publicação bem-sucedida (``response["completed"]``), agenda
       ``task_check_article_webpages`` (assíncrono) para verificar
       disponibilidade das URLs geradas.
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
            task_check_article_webpages.delay(
                user_id=user_id,
                username=username,
                article_proc_id=article_proc_id,
                article_id=article_proc.article.id,
                website_id=website_id,
                timeout=timeout,
                force_update=force_update,
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
    """
    Busca dados de periódico na Core API e cria/atualiza o registro local.

    Delega para ``fetch_and_create_journal()``.
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
        task_exec.finish(
            exception=e,
            exc_traceback=exc_traceback,
        )

###############################


@celery_app.task(bind=True)
def task_exclude_invalid_issue_articles(self, issue_proc_id, username=None, user_id=None, timeout=None, public_api_data=None):
    """
    Remove artigos duplicados e inconsistentes de um fascículo.

    Etapas:
    1. Corrige nomes de sps_pkg de artigos de suplemento que estejam
       sem o sufixo "-s" (``Article.fix_sps_pkg_names``).
    2. Exclui artigos duplicados ou que não devem estar associados ao
       fascículo (``Article.exclude_inconvenient_articles``).

    Args:
        issue_proc_id: ID do IssueProc a processar.
        username: Nome do usuário responsável pela operação.
        user_id: ID do usuário responsável pela operação.
        timeout: Tempo máximo (segundos) para a etapa de exclusão;
            None = sem limite.
        public_api_data: Dados da API pública (não utilizado diretamente
            nesta task, mas presente na assinatura por consistência com
            o caller).
    """
    task_params = {
        "issue_proc_id": issue_proc_id,
    }
    issue_proc_str = str(issue_proc_id)
    task_exec = TaskExecution(
        name="task_exclude_invalid_issue_articles",
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
                action="proc.tasks.task_exclude_invalid_issue_articles",
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
    Remove Issues duplicados de um periódico (ou de todos).

    Identifica Issues com mesmos campos-chave via ``Issue.get_duplicates``.
    Para cada grupo de duplicatas, mantém o mais recente (por ``updated``)
    e para os demais:
    - Migra Articles para o Issue mantido.
    - Atualiza IssueProc para apontar ao Issue mantido.
    - Exclui o Issue duplicado.
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
    Ponto de entrada para rastreamento de PIDs de artigos do site clássico.

    Agenda ``task_track_classic_website_article_pids_for_collection``
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

    Etapas:
    1. Reconcilia PIDs do site clássico com ArticleProcs via
       ``ClassicWebsiteArticlePidTracker.update_pid_status``.
    2. Para cada artigo com verificação pendente, agenda
       ``task_track_article_page_url_and_content`` (assíncrono).
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
def task_check_article_webpages(
    self,
    user_id=None,
    username=None,
    article_proc_id=None,
    article_id=None,
    website_id=None,
    timeout=None,
    force_update=None,
):
    """
    Garante existência de ArticleWebPages e verifica disponibilidade.

    Etapas:
    1. Cria/atualiza webpages para o artigo no website
       (``article.create_or_update_urls``).
    2. Calcula metadata por idioma uma vez
       (``article.get_metadata_by_lang``).
    3. Para cada webpage pendente, executa
       ``task_check_article_page_availability`` (síncrono).
    4. Se ``article_proc_id`` presente (artigos migrados), agenda
       ``task_update_article_proc_availability`` (assíncrono) como
       callback para atualizar pid_status.
    """
    try:
        user = _get_user(user_id, username)
        article = Article.objects.select_related("journal").get(id=article_id)

        website = WebSiteConfiguration.objects.select_related("collection").get(
            id=website_id,
        )
        # cria/atualiza webpages (idempotente)
        article.create_or_update_urls(user, website)

        # calcula metadata uma vez
        article_metadata = article.get_metadata_by_lang()

        # seleciona webpages a verificar
        wp_filter = {"website": website}
        excluded_items = {}
        if not force_update:
            excluded_items["status"] = article_choices.ARTICLE_WEBPAGE_STATUS_AVAILABLE

        for webpage in article.article_webpages.filter(**wp_filter).exclude(**excluded_items):
            lang_code = webpage.lang.code2 if webpage.lang else None
            # executar sincronamente
            task_check_article_page_availability(
                user_id=user_id,
                username=username,
                webpage_id=webpage.id,
                article_metadata=article_metadata.get(lang_code),
                timeout=timeout,
                force_update=force_update,
            )

        # callback pós-migração
        if article_proc_id:
            task_update_article_proc_availability.delay(
                user_id=user_id,
                username=username,
                article_proc_id=article_proc_id,
                website_id=website.id,
        )

    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "publication.tasks.task_check_article_webpages",
                "article_id": article_id,
                "article_proc_id": article_proc_id,
                "website_id": website_id,
            },
        )


# ============================================================
# VERIFICAÇÃO ATÔMICA POR WEBPAGE
# ============================================================

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
    Verifica disponibilidade e conteúdo de uma única ArticleWebPage.

    Delega para ``webpage.check_availability(user, timeout,
    article_metadata, force_update)``.

    Raises:
        ValueError: Se ``webpage_id`` não fornecido.
    """
    try:
        if not webpage_id:
            raise ValueError("webpage_id must be provided")
        user = _get_user(user_id, username)
        webpage = ArticleWebPage.objects.get(id=webpage_id)
        webpage.check_availability(user, timeout, article_metadata, force_update)
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "publication.tasks.task_check_article_page_availability",
                "webpage_id": webpage_id,
            },
        )


# ============================================================
# CALLBACK PÓS-MIGRAÇÃO
# ============================================================

@celery_app.task(bind=True)
def task_update_article_proc_availability(
    self,
    user_id=None,
    username=None,
    article_proc_id=None,
    website_id=None,
):
    """
    Callback pós-verificação: atualiza pid_status no ArticleProc.

    Se todas as webpages do artigo estão disponíveis no website,
    atualiza ``article_proc.pid_status`` para ``PID_STATUS_PUBLIC_VALID``.
    """
    try:
        user = _get_user(user_id, username)
        article_proc = ArticleProc.objects.select_related(
            "collection", "sps_pkg",
        ).get(pk=article_proc_id)

        if article_proc.all_webpage_available(website_id=website_id):
            from migration.choices import PID_STATUS_PUBLIC_VALID
            article_proc.set_pid_status(user, PID_STATUS_PUBLIC_VALID)

    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "publication.tasks.task_update_article_proc_availability",
                "article_proc_id": article_proc_id,
            },
        )


# ============================================================
# VERIFICAÇÃO EM LOTE (busca por filtros)
# ============================================================

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
    article_id=None,
    article_proc_id=None,
    collection_acron=None,
    website_id=None,
    timeout=None,
    force_update=None,
):
    """
    Verificação em lote: busca artigos por filtros e agenda verificação.

    Monta query dinâmica com os filtros fornecidos (ISSN, issue_folder,
    publication_year, pid_v3, article_id, collection_acron) e para cada
    par (artigo, website habilitado) agenda
    ``task_check_article_webpages`` (assíncrono).
    """
    try:
        article_params = {}
        j_query = Q()

        if article_id:
            article_params["id"] = article_id
        if article_pid_v3:
            article_params["pid_v3"] = article_pid_v3
        if publication_year:
            article_params["issue__publication_year"] = publication_year
        if issue_folder:
            article_params["issue__issue_folder"] = issue_folder

        if collection_acron or issn_electronic or issn_print:
            j_params = {}
            if collection_acron:
                j_params["collection__acron"] = collection_acron
            if issn_print:
                j_query |= Q(journal__official_journal__issn_print=issn_print)
            if issn_electronic:
                j_query |= Q(journal__official_journal__issn_electronic=issn_electronic)

            article_params["journal__id__in"] = JournalProc.objects.filter(
                j_query, **j_params
            ).values_list("journal__id", flat=True).distinct()

        ws_filter = {"enabled": True}
        if collection_acron:
            ws_filter["collection__acron"] = collection_acron
        if website_id:
            ws_filter["id"] = website_id

        for website in WebSiteConfiguration.objects.filter(**ws_filter).select_related("collection"):
            for article_id in Article.objects.filter(
                journal__isnull=False, **article_params
            ).values_list("id", flat=True):
                task_check_article_webpages.apply_async(
                    kwargs=dict(
                        user_id=user_id,
                        username=username,
                        article_id=article_id,
                        article_proc_id=article_proc_id,
                        website_id=website.id,
                        timeout=timeout,
                        force_update=force_update,
                    )
                )

    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "publication.tasks.task_check_articles_availability",
            },
        )


# ============================================================
# VERIFICAÇÃO NO SITE CLÁSSICO (somente migração)
# ============================================================

@celery_app.task(bind=True)
def task_check_classic_website_article(
    self,
    user_id=None,
    username=None,
    article_proc_id=None,
    timeout=None,
    force_update=None,
):
    """
    Confronta metadados do artigo com a página do site clássico.

    Passo extra de migração que verifica se o conteúdo da página HTML
    do site clássico confere com os metadados do artigo migrado.

    Atualiza ``article_proc.pid_status`` conforme resultado:
    - ``CLASSIC_MATCHED``: conteúdo confere.
    - ``CLASSIC_MISMATCHED``: conteúdo diverge.
    - ``CLASSIC_NOT_FOUND``: página não encontrada.

    Returns:
        Resultado da verificação (dicionário retornado por
        ``article_proc.check_classic_website_content``), ou None em
        caso de erro.
    """
    try:
        user = _get_user(user_id, username)
        article_proc = ArticleProc.objects.select_related(
            "collection", "sps_pkg", "issue_proc__journal_proc",
        ).get(pk=article_proc_id)

        article = article_proc.article
        if not article:
            raise ValueError(f"ArticleProc {article_proc_id} has no article")

        article_metadata_by_lang = article.get_metadata_by_lang()
        response = article_proc.check_classic_website_content(
            user, timeout, article_metadata_by_lang, force_update,
        )

        return response

    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "publication.tasks.task_check_classic_website_article",
                "article_proc_id": article_proc_id,
            },
        )


@celery_app.task(bind=True)
def task_check_main_article_page_availability(
    self,
    article_id,
    website_id,
):
    """
    Verifica se alguma webpage do artigo está disponível no website.

    Returns:
        True se ao menos uma webpage está disponível, False caso
        contrário, ou None em caso de erro.
    """
    try:
        article = Article.objects.get(id=article_id)
        return article.any_webpage_available(website=website_id)
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "publication.tasks.task_check_main_article_page_availability",
                "article_id": article_id,
                "website_id": website_id,
            },
        )