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
          ├─ task_fix_issue_articles (síncrono, por fascículo selecionado,
          │   antes de agendar a migração; corrige/exclui registros
          │   duplicados ou com sps_pkg.ppx ausente)
          └─ task_migrate_and_publish_articles_by_issue (por fascículo)
              └─ task_publish_issue_articles (publica artigos + sincroniza issue)
                  ├─ task_publish_article (por artigo, síncrono)
                  │   └─ task_check_article_webpages (verifica disponibilidade
                  │       e já atualiza o pid_status diretamente; ver nota)
                  └─ task_sync_issue (sincroniza fascículo no site)

  Publicação avulsa (somente publicação, sem migração):
    task_publish_articles
      └─ task_publish_issue_articles (por fascículo)

  Verificação de disponibilidade (em lote):
    task_check_articles_availability
      └─ task_check_article_webpages (por artigo × website; atualiza o
          pid_status diretamente ao final, sem despachar outra task)

  NOTA: neste arquivo, ``task_check_article_page_availability`` e
  ``task_update_article_proc_availability`` não são chamadas por nenhuma
  outra task (nenhum ``.delay``/``.apply_async``/chamada direta as
  referencia). Elas podem estar sendo usadas como callbacks de uma
  Celery chain/chord montada fora deste módulo (ex.: a partir de
  ``ArticleWebPage``/``Article.check_availability``) ou podem ser código
  órfão remanescente de uma versão anterior do fluxo — vale confirmar
  antes de assumir que compõem o pipeline ativo.

  Rastreamento de PIDs do site clássico:
    task_track_classic_website_article_pids
      └─ task_track_classic_website_article_pids_for_collection (por coleção)
          └─ task_track_article_page_url_and_content (por artigo)

  Verificação no site clássico (migração):
    task_check_migrated_article

  Utilitários:
    task_fetch_and_create_journal
    task_fix_issue_articles
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

from article.models import Article, ArticleCollection, ArticleWebPage
from journal.models import Journal
from issue.models import Issue
from collection.choices import PUBLIC, QA
from collection.models import Collection, WebSiteConfiguration
from config import celery_app
from migration import controller as migration_controller
from migration import choices as migration_choices
from package.models import SPSPkg
from proc.controller import (
    create_or_update_migrated_issue,
    create_or_update_migrated_journal,
    fetch_and_create_journal,
    migrate_issue,
    get_total_status_data,
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
        self.journal_proc_id = None
        self.status_changes = {}

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

    def finish(self, exception=None, exc_traceback=None, data=None):
        try:
            if exception or exc_traceback or self.exceptions:
                completed = False
            else:
                completed = True
            self.stats["total_to_process"] = self.total_to_process
            self.stats["total_processed"] = self.total_processed

            detail = {
                "params": self.params,
                "stats": self.stats,
                "events": self.events,
                "exceptions": self.exceptions,
                "status_changes": self.status_changes
            }
            if data:
                detail["data"] = data
            try:
                json.dumps(detail)
            except Exception as x:
                fixed_detail = {}
                for key, value in detail.items():
                    try:
                        json.dumps(value)
                        fixed_detail[key] = value
                    except Exception as exxx:
                        fixed_detail[key] = str(value)
                detail = fixed_detail

            self.task_tracker.finish(
                completed=completed,
                exception=exception,
                exc_traceback=exc_traceback,
                detail=detail,
            )
        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            UnexpectedEvent.create(
                action="proc.tasks.TaskExecution.finish",
                item=self.item,
                e=e,
                exc_traceback=exc_traceback,
            )

    def update_total_status(self, label, issue_proc_id=None):
        previous = {}
        for key, items in self.status_changes.items():
            try:
                previous[key] = items[-1]["total_status"]
            except (IndexError, KeyError):
                previous[key] = []

        result = get_total_status_data(previous, self.journal_proc_id, issue_proc_id)
        for key, items in result.items():
            data = {
                "label": label,
                "total_status": items
            }
            self.status_changes.setdefault(key, []).append(data)


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


def fix_publication_status(collection):
    """Para cada purpose (QA/PUBLIC) sem WebSiteConfiguration ativa, marca TODO → IGNORED."""
    field_map = {"QA": "qa_ws_status", "PUBLIC": "public_ws_status"}
    
    enabled_items = {"QA": False, "PUBLIC": False}
    for purpose in WebSiteConfiguration.objects.filter(
        collection=collection, enabled=True
    ).values_list("purpose", flat=True):
        enabled_items[purpose] = True
    
    for purpose, enabled in enabled_items.items():
        field = field_map[purpose]
        if enabled:
            filter_kwargs = {field: tracker_choices.PROGRESS_STATUS_IGNORED}
            update_kwargs = {field: tracker_choices.PROGRESS_STATUS_TODO}
        else:
            filter_kwargs = {field: tracker_choices.PROGRESS_STATUS_TODO}
            update_kwargs = {field: tracker_choices.PROGRESS_STATUS_IGNORED}
        JournalProc.objects.filter(collection=collection, **filter_kwargs).update(**update_kwargs)
        IssueProc.objects.filter(collection=collection, **filter_kwargs).update(**update_kwargs)
        ArticleProc.objects.filter(collection=collection, **filter_kwargs).update(**update_kwargs)


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
    force_core_sync=False,
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
            "force_core_sync": force_core_sync,
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
                force_core_sync=force_core_sync,
            )
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            action="proc.tasks.task_migrate_and_publish_journals",
            item=collection_acron,
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
    force_core_sync=False,
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
        "force_core_sync": force_core_sync,
    }
    task_exec = TaskExecution(
        name="proc.tasks.task_migrate_and_publish_journals_by_collection",
        item=f"{collection_acron}",
        params=task_params,
    )
    try:
        user = _get_user(user_id, username)

        classic_website = migration_controller.get_classic_website(collection_acron)
        collection = Collection.objects.get(acron=collection_acron)
        create_or_update_migrated_journal(
            user, collection, classic_website, force_import_acron_id_file
        )

        journal_filter = {}
        if journal_acron:
            journal_filter["acron"] = journal_acron

        status = tracker_choices.get_valid_status(status, force_update)
        query_by_status = (
            Q(qa_ws_status__in=status)
            | Q(public_ws_status__in=status)
        )
        if not force_core_sync:
            # seleciona também aqueles que não estão sincronizados
            query_by_status |= Q(migration_status__in=status)
            query_by_status |= Q(journal__core_synchronized=False)         

        # para force_core_sync=True, o filtro migration_status deixa de ser relevante

        fix_publication_status(collection)
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

                if force_core_sync:
                    fetch_and_create_journal(
                        user,
                        collection_acron=collection.acron,
                        issn_electronic=journal_proc.issn_electronic,
                        issn_print=journal_proc.issn_print,
                        force_update=force_core_sync,
                    )
                    detail["journal_data_source"] = "core data"
                else:
                    # cria journal a partir de migrated journal
                    journal_proc.create_or_update_item(
                        user, force_update, migration_controller.create_or_update_journal
                    )
                    detail["journal_data_source"] = "classic website data"
                if qa_api_data and not qa_api_data.get("error"):
                    detail["task_publish_journal_on_qa_website"] = "scheduled"
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
                    detail["task_publish_journal_on_public_website"] = "scheduled"
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
                item=f"{collection_acron}",
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
            fix_publication_status(collection)
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

        classic_website = migration_controller.get_classic_website(collection_acron)
        collection = Collection.objects.get(acron=collection_acron)
        create_or_update_migrated_issue(
            user, collection, classic_website, force_update
        )
        fix_publication_status(collection)
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
            fix_publication_status(collection)
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
    delete_article_which_is_duplicated=False,
    delete_article_which_sps_pkg_is_missing=False,
    delete_sps_pkg_which_is_duplicated=False,
    delete_sps_pkg_which_ppx_is_missing=False,
    delete_article_procs_which_sps_pkg_is_missing=False,
    delete_article_procs_which_is_duplicated=False,
):
    """
    Ponto de entrada para migração e publicação de artigos.

    Consolida ``collection_acron``/``collection_acron_list`` e
    ``journal_acron``/``journal_acron_list`` em listas únicas e resolve
    quais periódicos (e, opcionalmente, quais fascículos) serão
    processados:

    - Se ``publication_year`` ou ``issue_folder`` forem informados,
      seleciona ``IssueProc`` via ``IssueProc.select_items`` (filtrando
      também por ``article_status_list=PROGRESS_STATUS_REGULAR_TODO``,
      isto é, fascículos cujo ``docs_status``/``files_status`` indica que
      há artigos pendentes de migração ou reprocessamento) e agrupa os
      ``issue_proc_id`` por periódico.
    - Caso contrário, seleciona todos os ``JournalProc`` com
      ``has_issue_proc=True`` (nenhum fascículo específico é fixado; a
      seleção de fascículos/artigos fica a cargo de
      ``task_migrate_and_publish_articles_by_journal``).

    Para cada periódico resultante, agenda
    ``task_migrate_and_publish_articles_by_journal`` repassando
    ``issue_proc_id_list`` (quando aplicável) e os demais parâmetros de
    controle de migração/exclusão.

    Parameters
    ----------
    collection_acron / collection_acron_list : str / list, optional
        Coleção(ões) a processar; combinados em uma única lista.
    journal_acron / journal_acron_list : str / list, optional
        Periódico(s) a processar; combinados em uma única lista.
    publication_year / issue_folder : int / str, optional
        Quando informados, restringem o processamento a fascículos
        específicos (via ``IssueProc.select_items``) em vez de todos os
        fascículos do periódico.
    status : list, optional
        Lista de status usada para selecionar itens pendentes; resolvida
        por ``tracker_choices.get_valid_status(status, force_update)``.
    force_update : bool, default False
        Se True, ignora o filtro de status e força reprocessamento.
    force_import_acron_id_file : bool, default False
        Repassado até ``controller.import_journal_acron_id_records``
        (via ``task_migrate_and_publish_articles_by_journal``) para
        forçar a reimportação do arquivo acron.id.
    force_migrate_document_records / force_migrate_document_files : bool, default False
        Repassados até ``IssueProc.migrate_document_records`` /
        ``migrate_document_files`` para forçar a remigração de registros
        e arquivos de documento.
    skip_migrate_pending_document_records : bool, default False
        Reservado; não é utilizado no corpo atual desta task.
    delete_article_which_is_duplicated : bool, default False
        Repassado até ``task_fix_issue_articles`` / ``Article.exclude_invalid_records``:
        remove ``Article`` duplicados (mantém 1).
    delete_article_which_sps_pkg_is_missing : bool, default False
        Repassado até ``task_fix_issue_articles``: controla se a exclusão
        de registros inválidos deve ser executada mesmo quando a
        reconciliação de ``sps_pkg.ppx`` reportar falhas (ver docstring
        de ``task_fix_issue_articles``).
    delete_sps_pkg_which_is_duplicated / delete_sps_pkg_which_ppx_is_missing : bool, default False
        Repassados até ``task_fix_issue_articles`` / ``SPSPkg.exclude_invalid_records``:
        removem ``SPSPkg`` duplicados ou sem ``ppx`` associado.
    delete_article_procs_which_sps_pkg_is_missing / delete_article_procs_which_is_duplicated : bool, default False
        Repassados até ``task_fix_issue_articles`` / ``ArticleProc.exclude_invalid_records``:
        removem ``ArticleProc`` duplicados ou sem ``sps_pkg`` associado.
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
        "delete_article_which_is_duplicated": delete_article_which_is_duplicated,
        "delete_article_which_sps_pkg_is_missing": delete_article_which_sps_pkg_is_missing,
        "delete_sps_pkg_which_is_duplicated": delete_sps_pkg_which_is_duplicated,
        "delete_sps_pkg_which_ppx_is_missing": delete_sps_pkg_which_ppx_is_missing,
        "delete_article_procs_which_sps_pkg_is_missing": delete_article_procs_which_sps_pkg_is_missing,
        "delete_article_procs_which_is_duplicated": delete_article_procs_which_is_duplicated,
    }
    title = f"{collection_acron or collection_acron_list}-{journal_acron or journal_acron_list}-{issue_folder}-{publication_year}"
    task_exec = TaskExecution(
        name="proc.tasks.task_migrate_and_publish_articles",
        item=title,
        params=task_params,
    )
    try:
        journal_acron_list = journal_acron_list or []
        if journal_acron:
            journal_acron_list += [journal_acron]
        collection_acron_list = collection_acron_list or []
        if collection_acron:
            collection_acron_list += [collection_acron]

        status = tracker_choices.get_valid_status(status, force_update)

        items_to_process = ArticleProc.get_journal_and_issue_proc_ids(
            collection_acron_list=collection_acron_list,
            journal_acron_list=journal_acron_list,
            publication_year=publication_year,
            issue_folder=issue_folder,
            force_migrate_document_records=force_migrate_document_records,
            force_migrate_document_files=force_migrate_document_files,
            status_list=status,
        )

        total_journals_to_process = len(items_to_process)
        task_exec.add_number(
            "total_journals_to_process", total_journals_to_process
        )

        task_exec.total_to_process = total_journals_to_process
        total_processed = 0
        for (journal_proc_id, journal_acron), issue_proc_id_list in items_to_process.items():
            issue_proc_id_list = list(issue_proc_id_list)
            task_migrate_and_publish_articles_by_journal.delay(
                user_id=user_id,
                username=username,
                collection_acron=collection_acron,
                journal_acron=journal_acron,
                journal_proc_id=journal_proc_id,
                issue_folder=issue_folder,
                publication_year=publication_year,
                issue_proc_id_list=issue_proc_id_list,
                status=status,
                force_update=force_update,
                force_import_acron_id_file=force_import_acron_id_file,
                force_migrate_document_records=force_migrate_document_records,
                force_migrate_document_files=force_migrate_document_files,
            )
            total_processed += 1
            task_exec.add_event({
                "action": "scheduled task_migrate_and_publish_articles_by_journal",
                "item": journal_acron,
                "total_issues": len(issue_proc_id_list)
            })

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
    force_update=False,
    force_import_acron_id_file=False,
    force_migrate_document_records=False,
    force_migrate_document_files=False,
    delete_article_which_is_duplicated=False,
    delete_article_which_sps_pkg_is_missing=False,
    delete_sps_pkg_which_is_duplicated=False,
    delete_sps_pkg_which_ppx_is_missing=False,
    delete_article_procs_which_sps_pkg_is_missing=False,
    delete_article_procs_which_is_duplicated=False,
):
    """
    Migra e publica artigos de um periódico: seleciona fascículos/artigos
    pendentes, corrige inconsistências e agenda a migração por fascículo.

    Fluxo:

    1. ``fix_publication_status``: normaliza ``qa_ws_status``/``public_ws_status``
       de Journal/Issue/Article conforme os websites habilitados na coleção.
    2. ``controller.import_journal_acron_id_records``: importa/atualiza o
       arquivo acron.id do periódico (respeitando ``force_import_acron_id_file``).
    3. ``ArticleProc.mark_to_reproc_item_which_sps_pkg_pid_v2_is_incorrect``:
       marca para reprocessamento os ``ArticleProc`` cujo ``pid_v2`` do
       ``sps_pkg`` está incorreto (restrito a ``issue_proc_id_list``, quando
       informado).
    4. Seleção dos fascículos/artigos a processar:
       - Se ``issue_proc_id_list`` foi recebido (chamada originada de
         ``task_migrate_and_publish_articles`` com filtro de fascículo),
         processa apenas esses ``IssueProc``, sem artigos fixados
         individualmente.
       - Caso contrário, seleciona via ``IssueProc.select_items`` os
         fascículos com ``article_status_list=PROGRESS_STATUS_REGULAR_TODO``
         (isto é, cujo ``docs_status``/``files_status`` sinaliza documentos
         pendentes de migração ou reprocessamento) e, para os demais
         fascículos do periódico, seleciona diretamente os ``ArticleProc``
         pendentes via ``ArticleProc.select_items``.
    5. Para cada fascículo resultante, executa **de forma síncrona**
       ``task_fix_issue_articles`` (corrige/exclui ``SPSPkg``/``Article``/``ArticleProc``
       inconsistentes antes da migração) e então agenda, de forma
       assíncrona, ``task_migrate_and_publish_articles_by_issue`` repassando
       a resposta de ``task_fix_issue_articles`` em
       ``exclude_invalid_articles_response``.

    Importa o arquivo acron.id via ``migration_controller.import_journal_acron_id_records``
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
        "delete_article_which_is_duplicated": delete_article_which_is_duplicated,
        "delete_article_which_sps_pkg_is_missing": delete_article_which_sps_pkg_is_missing,
        "delete_sps_pkg_which_is_duplicated": delete_sps_pkg_which_is_duplicated,
        "delete_sps_pkg_which_ppx_is_missing": delete_sps_pkg_which_ppx_is_missing,
        "delete_article_procs_which_sps_pkg_is_missing": delete_article_procs_which_sps_pkg_is_missing,
        "delete_article_procs_which_is_duplicated": delete_article_procs_which_is_duplicated,
    }
    task_exec = TaskExecution(
        name="proc.tasks.task_migrate_and_publish_articles_by_journal",
        item=f"{collection_acron}-{journal_acron}",
        params=task_params,
    )
    try:
        if not journal_proc_id:
            raise ValueError("journal_proc_id is required")
        journal_proc = JournalProc.objects.get(id=journal_proc_id)

        user = _get_user(user_id, username)
        status = tracker_choices.get_valid_status(status, force_update)

        task_exec.journal_proc_id = journal_proc_id
        task_exec.update_total_status(("Start"))

        fix_publication_status(journal_proc.collection)
        task_exec.update_total_status(("Updated publication status"))

        # a partir de acron.id, cria ou atualiza JournalAcronIdFile e IdFileRecord,
        # fonte para criar/atualizar ArticleProc
        response = migration_controller.import_journal_acron_id_records(
            user,
            ArticleProc,
            journal_proc,
            force_update=force_import_acron_id_file,
        )

        task_exec.add_event({"operation": "import_journal_acron_id_records", "response": response})

        task_exec.update_total_status(label="Imported journal acron.id")

        qa_api_data = get_api_data(
            journal_proc.collection, "issue", "QA"
        )
        public_api_data = get_api_data(
            journal_proc.collection, "issue", "PUBLIC"
        )
        total_processed = 0
        issue_proc_id_list = list(issue_proc_id_list)
        total_to_process = len(issue_proc_id_list)

        for issue_proc_id in issue_proc_id_list:
            
            # executa sincronamente a eliminação de registros ArticleProc e Article cujo conteúdo é defeituoso
            response = task_fix_issue_articles(
                issue_proc_id=issue_proc_id,
                username=username,
                user_id=user_id,
                public_api_data=public_api_data,
                delete_article_which_is_duplicated=delete_article_which_is_duplicated,
                delete_article_which_sps_pkg_is_missing=delete_article_which_sps_pkg_is_missing,
                delete_sps_pkg_which_is_duplicated=delete_sps_pkg_which_is_duplicated,
                delete_sps_pkg_which_ppx_is_missing=delete_sps_pkg_which_ppx_is_missing,
                delete_article_procs_which_sps_pkg_is_missing=delete_article_procs_which_sps_pkg_is_missing,
                delete_article_procs_which_is_duplicated=delete_article_procs_which_is_duplicated,
            )

            task_migrate_and_publish_articles_by_issue.delay(
                user_id=user_id,
                username=username,
                issue_proc_id=issue_proc_id,
                status=status,
                force_update=force_update,
                force_migrate_document_records=force_migrate_document_records,
                force_migrate_document_files=force_migrate_document_files,
                qa_api_data=qa_api_data,
                public_api_data=public_api_data,
                exclude_invalid_articles_response=response,
            )
            total_processed += 1
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
    status=None,
    force_update=False,
    force_migrate_document_records=False,
    force_migrate_document_files=False,
    qa_api_data=None,
    public_api_data=None,
    exclude_invalid_articles_response=None,
):
    """
    Migra artigos de um fascículo e agenda a publicação deles.

    Se ``article_proc_id_list`` for informado (fascículo já teve seus
    ``ArticleProc`` selecionados por
    ``task_migrate_and_publish_articles_by_journal``), processa apenas
    esses registros diretamente, sem repetir a migração de
    registros/arquivos do fascículo. Caso contrário, executa o pipeline
    completo:

    1. ``issue_proc.migrate_document_records``: cria/atualiza os
       ``ArticleProc`` do fascículo a partir do site clássico.
    2. ``issue_proc.migrate_document_files``: cria/atualiza os
       ``MigratedFile`` (pacotes SPS) do fascículo via
       ``controller.migrate_issue_files``.
    3. ``ArticleProc.select_items``: seleciona os ``ArticleProc``
       pendentes (conforme ``status``/``force_update``) para migração.

    Para cada ``ArticleProc`` selecionado, chama
    ``article_proc.migrate_article`` (obtém o XML/pacote SPS e cria ou
    atualiza os registros ``SPSPkg``/``Article``); falhas individuais são
    registradas em ``task_exec`` mas não interrompem o loop.

    Ao final, agenda (assíncrono) ``task_publish_issue_articles`` para
    publicar os artigos do fascículo e sincronizar o TOC.

    Parameters
    ----------
    issue_proc_id : int
        ID do ``IssueProc`` cujo fascículo será migrado.
    article_proc_id_list : list[int], optional
        Quando informado, restringe a migração a esses ``ArticleProc``
        específicos (pula as etapas de migração de registros/arquivos do
        fascículo).
    status : list, optional
        Lista de status usada em ``ArticleProc.select_items`` quando
        ``article_proc_id_list`` não é informado.
    force_update : bool, default False
        Se True, ignora o filtro de status ao selecionar artigos e força
        remigração em ``migrate_article``.
    force_migrate_document_records / force_migrate_document_files : bool, default False
        Forçam a remigração de registros/arquivos do fascículo mesmo que
        já tenham sido migrados anteriormente.
    qa_api_data / public_api_data : dict, optional
        Recebidos de ``task_migrate_and_publish_articles_by_journal`` mas
        não utilizados no corpo atual desta task (não são repassados a
        ``task_publish_issue_articles``, que recalcula os dados de API
        por website habilitado).
    exclude_invalid_articles_response : list or dict, optional
        Resultado de ``task_fix_issue_articles`` executado antes desta
        task; apenas registrado no histórico de eventos (``task_exec``).
    """
    task_params = {
        "user_id": user_id,
        "username": username,
        "issue_proc_id": issue_proc_id,
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

        task_exec.item = f"{issue_proc} {issue_proc.collection}"

        task_exec.journal_proc_id = issue_proc.journal_proc_id
        task_exec.update_total_status(("Start"), issue_proc_id)

        task_exec.add_event(exclude_invalid_articles_response)

        # a partir do IdFileRecord, cria ou atualiza ArticleProc
        response = issue_proc.migrate_document_records(
            user, force_migrate_document_records
        )
        task_exec.add_event({"operation": "migrate_document_records", "response": response})
        task_exec.update_total_status(("Created or updated Article Processing records"), issue_proc_id)

        # cria ou atualiza MigratedFile
        response = issue_proc.migrate_document_files(
            user,
            force_migrate_document_files,
            migration_controller.migrate_issue_files,
        )
        task_exec.add_event({"operation": "migrate_document_files", "response": response})
        task_exec.update_total_status(("Created or updated Migrated file records"), issue_proc_id)

        article_procs = ArticleProc.select_items(
            issue_proc_id=issue_proc_id,
            status_list=None if force_update else status,
        )
        task_exec.total_to_process = article_procs.count()

        total_processed = 0
        exceptions = {}
        for article_proc in article_procs:
            try:
                # executa get_xml, generate_sps_pkg, cria / atualiza Article
                article = article_proc.migrate_article(user, force_update)
                total_processed += 1
            except Exception as e:
                exc_type, exc_value, exc_traceback = sys.exc_info()
                exceptions[article_proc.pid] = traceback.format_exc()
                task_exec.add_exception(exceptions[article_proc.pid])
        task_exec.update_total_status(("Created or updated SPS Package and Article records"), issue_proc_id)

        task_exec.total_processed = total_processed
        task_exec.add_number("total_processed", total_processed)
        task_exec.add_number("total_articleprocs", issue_proc.articleproc_set.count())

        task_publish_issue_articles.delay(
            user_id=user_id,
            username=username,
            issue_proc_id=issue_proc_id,
            status=status,
            force_update=force_update,
        )
        task_exec.add_event({"operation": "Scheduled articles publication"})
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

    Seleciona os ``ArticleProc`` do fascículo que já possuem
    ``sps_pkg.pid_v3`` (isto é, artigos com pacote SPS registrado no PID
    Provider) e, para cada ``WebSiteConfiguration`` habilitada da coleção
    (QA e/ou PUBLIC):

    1. Filtra os artigos pendentes de publicação naquele website
       (``qa_ws_status``/``public_ws_status`` em ``status``).
    2. Publica cada artigo pendente via ``task_publish_article``
       (chamada síncrona, artigo a artigo).
    3. Agenda (assíncrono) ``task_sync_issue`` para aquele website, para
       que o fascículo seja atualizado no TOC do site.

    Falhas de publicação de artigos individuais são registradas em
    ``task_exec`` e não interrompem o processamento dos demais artigos
    nem dos demais websites.

    Parameters
    ----------
    issue_proc_id : int
        ID do ``IssueProc`` cujos artigos serão publicados.
    status : list, optional
        Lista de status usada para filtrar artigos pendentes de
        publicação; resolvida por ``tracker_choices.get_valid_status``.
    force_update : bool, default False
        Se True, ignora o filtro de status (publica mesmo artigos já
        publicados).
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

        task_exec.journal_proc_id = issue_proc.journal_proc_id
        task_exec.update_total_status(("Start"), issue_proc_id)

        articles = (
            ArticleProc.objects.select_related("issue_proc", "sps_pkg")
            .filter(
                issue_proc=issue_proc,
                sps_pkg__pid_v3__isnull=False,
            )
        )

        collection = issue_proc.collection
        fix_publication_status(collection)
        task_exec.update_total_status(("Updated publication status"), issue_proc_id)

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

            total_published = 0
            total_to_publish = 0
            article_ids_to_publish = articles.filter(query_by_status).values_list("id", flat=True)
            total_to_publish = article_ids_to_publish.count()
            total_to_process += total_to_publish
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
                    total_published += 1
                except Exception as e:
                    exc_type, exc_value, exc_traceback = sys.exc_info()
                    task_exec.add_exception(traceback.format_exc())
            total_processed += total_published
            task_exec.update_total_status(
                (f"Total article published on {website_kind}: {total_published}/{total_to_publish}"),
                issue_proc_id
            )

            task_sync_issue.delay(
                user_id=user_id,
                username=username,
                website_kind=website_kind,
                issue_proc_id=issue_proc_id,
                api_data=api_data,
            )
            task_exec.add_event({"operation": "Scheduled issue synchronization"})
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
    Sincroniza a tabela de conteúdo (TOC) de um fascículo no site (QA ou PUBLIC).

    Delega para ``publication.api.issue.sync_issue``, usando ``api_data``
    se fornecido ou buscando via ``get_api_data`` caso contrário.
    Chamada de forma assíncrona por ``task_publish_issue_articles`` (uma
    vez por website habilitado) após a publicação dos artigos do
    fascículo, para garantir que o TOC reflita os artigos recém-publicados.

    Parameters
    ----------
    issue_proc_id : int
        ID do ``IssueProc`` cujo fascículo será sincronizado.
    website_kind : str
        ``QA`` ou ``PUBLIC``.
    api_data : dict, optional
        Dados de API pré-carregados; se omitido, obtidos via
        ``get_api_data(issue_proc.collection, "issue", website_kind)``.
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
    Publicação avulsa de artigos (sem etapa de migração).

    Ponto de entrada independente do fluxo de migração: normaliza o
    status de publicação das coleções selecionadas
    (``fix_publication_status``), seleciona ``IssueProc`` via
    ``IssueProc.select_items`` conforme os filtros fornecidos e agenda
    (assíncrono) ``task_publish_issue_articles`` para cada fascículo,
    reaproveitando artigos e pacotes SPS já migrados.

    Parameters
    ----------
    collection_acron / journal_acron : str, optional
        Filtram a coleção/periódico a processar.
    issue_folder / publication_year : str / int, optional
        Filtram fascículo(s) específico(s).
    issue_proc_id : int, optional
        Restringe a um único ``IssueProc``.
    status : list, optional
        Repassado a ``task_publish_issue_articles`` para filtrar artigos
        pendentes de publicação.
    force_update : bool, default False
        Repassado a ``task_publish_issue_articles``.
    verify : bool, optional
        Recebido mas não utilizado no corpo atual desta task.
    timeout : int, optional
        Recebido mas não utilizado no corpo atual desta task.
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
        for collection in _get_collections(collection_acron):
            fix_publication_status(collection)
        issue_procs = IssueProc.select_items(
            collection_acron=collection_acron,
            journal_acron=journal_acron,
            issue_folder=issue_folder,
            publication_year=publication_year,
            issue_proc_id=issue_proc_id,
        )
        total = issue_procs.count()

        for issue_proc in issue_procs:
            task_publish_issue_articles.delay(
                user_id=user_id,
                username=username,
                issue_proc_id=issue_proc.id,
                status=status,
                force_update=force_update,
            )
        task_exec.add_event({"operation": f"Scheduled article publication of {total} issues"})
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

    Delega para ``article_proc.publish`` (que chama
    ``publication.api.document.publish_article`` e atualiza
    ``qa_ws_status``/``public_ws_status`` conforme o resultado). Se a
    publicação for concluída com sucesso, agenda (assíncrono)
    ``task_check_article_webpages`` para verificar a disponibilidade da
    página recém-publicada.

    Note
    ----
    Executada de forma síncrona por ``task_publish_issue_articles``
    (chamada direta, não ``.delay``), artigo a artigo.

    Parameters
    ----------
    website_kind : str
        ``QA`` ou ``PUBLIC``.
    website_id : int, optional
        ID da ``WebSiteConfiguration`` correspondente; apenas informativo
        (não é usado para consulta nesta task).
    article_proc_id : int
        ID do ``ArticleProc`` a publicar.
    api_data : dict, optional
        Dados de API usados por ``publish_article``.
    force_update : bool, optional
        Se True, republica mesmo que já esteja marcado como publicado.
    timeout : int, optional
        Recebido e repassado a ``task_check_article_webpages``.
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
def task_fix_issue_articles(
    self,
    issue_proc_id,
    username=None,
    user_id=None,
    timeout=None,
    public_api_data=None,
    delete_article_which_is_duplicated=False,
    delete_article_which_sps_pkg_is_missing=False,
    delete_sps_pkg_which_is_duplicated=False,
    delete_sps_pkg_which_ppx_is_missing=False,
    delete_article_procs_which_sps_pkg_is_missing=False,
    delete_article_procs_which_is_duplicated=False,
):
    """
    Corrige e remove artigos duplicados/inconsistentes de um fascículo.

    Executa, para o fascículo associado ao ``IssueProc`` informado:
    1. ``ArticleProc.complete_sps_pkg_ppx``, que completa o vínculo
       ``sps_pkg.ppx`` dos ArticleProc do fascículo ainda sem PidProviderXML
       associado.
    2. ``Article.exclude_invalid_records``, que remove registros de Article
       inválidos ou duplicados.

    Chamada automaticamente por ``task_migrate_and_publish_articles_by_journal``
    antes de iniciar a migração dos artigos do fascículo.

    A etapa de exclusão (passo 2) é destrutiva: ela apaga definitivamente
    ``SPSPkg``/``Article`` cujo vínculo com ``PidProviderXML`` não pôde ser
    resolvido. Se a reconciliação do passo 1 (``ArticleProc.complete_sps_pkg_ppx``)
    reportar falhas (``response["failures"]``), isso pode significar apenas uma
    falha temporária (PID Provider fora do ar, ZIP inacessível, etc.) e não que
    o registro é de fato inválido. Por isso, quando há falhas na reconciliação,
    a exclusão só é executada se ``delete_article_which_sps_pkg_is_missing=True``; caso
    contrário, os ``ArticleProc`` correspondentes aos pacotes que falharam são
    marcados com ``migration_status=PROGRESS_STATUS_BLOCKED`` para revisão
    manual, e a etapa de exclusão é pulada. O usuário pode então investigar e,
    se confirmar que os registros são realmente inválidos, executar a task
    novamente com ``delete_article_which_sps_pkg_is_missing=True``.

    Parameters
    ----------
    issue_proc_id : int
        ID do IssueProc cujo fascículo será processado.
    username : str, optional
        Nome do usuário que executa a tarefa (alternativa a user_id).
    user_id : int, optional
        ID do usuário que executa a tarefa (alternativa a username).
    timeout : int, optional
        Tempo limite passado para Article.exclude_invalid_records.
    public_api_data : dict, optional
        Não utilizado atualmente nesta implementação.
    delete_article_which_sps_pkg_is_missing : bool, optional
        Se True, executa a exclusão de registros inválidos mesmo quando a
        reconciliação (``ArticleProc.complete_sps_pkg_ppx``) reportou falhas.
        Se False (padrão), nesse caso a exclusão é pulada e os ArticleProc
        afetados são apenas marcados (``migration_status=BLOCKED``) para que
        o usuário decida, mais tarde, solicitar a exclusão.

    Returns
    -------
    list or dict
        Lista de eventos ``{"operation": str, "response": dict}`` executados,
        ou dict com detalhes de exceção em caso de falha.
    """
    try:
        detail = None
        user = _get_user(user_id=user_id, username=username)
        issue_proc = IssueProc.objects.select_related("issue").get(
            id=issue_proc_id
        )
        detail = []
        detail.append({
            "params": {
                "delete_article_which_is_duplicated": delete_article_which_is_duplicated,
                "delete_article_which_sps_pkg_is_missing": delete_article_which_sps_pkg_is_missing,
                "delete_sps_pkg_which_ppx_is_missing": delete_sps_pkg_which_ppx_is_missing,
            }
        })
        issue = issue_proc.issue
        # Filtra Article por issue e 
        # completa Article.sps_pkg.ppx com Article.pp_xml
        response = Article.complete_sps_pkg_ppx(user, issue)
        detail.append({
            "operation": "Article.complete_sps_pkg_ppx",
            "response": response,
        })
        # Filtra ArticleProc por issue_proc_id e 
        # completa ArticleProc.sps_pkg.ppx requisitando novamente pid v3 usando sps_pkg.file
        response = ArticleProc.complete_sps_pkg_ppx(
            user, issue_proc_id_list=[issue_proc_id])
        detail.append({
            "operation": "ArticleProc.complete_sps_pkg_ppx",
            "response": response,
        })
        if delete_sps_pkg_which_ppx_is_missing or delete_sps_pkg_which_is_duplicated:
            # exclue os SPSPkg cujos ppx is None ou que tem ppx duplicados (mantém 1)
            response = SPSPkg.exclude_invalid_records(
                user, 
                issue_proc.pid,
                delete_sps_pkg_which_ppx_is_missing,
                delete_sps_pkg_which_is_duplicated,
            )
            detail.append({
                "operation": "SPSPkg.exclude_invalid_records",
                "response": response,
            })
        if delete_article_which_sps_pkg_is_missing or delete_article_which_is_duplicated:
            # exclue os Article cujos sps_pkg is None ou que tem sps_pkg duplicados (mantém 1)
            response = Article.exclude_invalid_records(
                user,
                issue,
                delete_article_which_sps_pkg_is_missing,
                delete_article_which_is_duplicated,
                timeout=timeout,
            )
            detail.append({
                "operation": "Article.exclude_invalid_records",
                "response": response,
            })
        if delete_article_procs_which_sps_pkg_is_missing or delete_article_procs_which_is_duplicated:
            # exclue os ArticleProc cujos sps_pkg is None ou que tem sps_pkg duplicados (mantém 1)
            response = ArticleProc.exclude_invalid_records(
                user,
                issue_proc_id,
                delete_article_procs_which_sps_pkg_is_missing,
                delete_article_procs_which_is_duplicated,
            )
            detail.append({
                "operation": "ArticleProc.exclude_invalid_records",
                "response": response,
            })
        return detail
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        return {
            "exc_type": str(exc_type),
            "exc_value": str(exc_value),
            "traceback": traceback.format_exc()
        }


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
            if not article_proc.article:
                continue
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
    Verifica a disponibilidade das páginas web de um artigo e atualiza o pid_status.

    1. Recupera o ``ArticleProc`` pelo id e, a partir dele, o ``Article``.
    2. Garante existência das ``ArticleCollection`` via
       ``article.create_or_update_article_collections``.
    3. Executa a verificação via ``article.check_availability``, filtrada
       por ``collection_id`` e ``website_kind`` (``purpose``).
    4. Consulta o resultado consolidado em
       ``article.available_on_classic_website`` e
       ``article.available_on_public_website``; para cada resposta
       válida (``valid=True``), atualiza ``article_proc.pid_status``
       via ``ArticleProc.set_pid_status``.

    Agendada (assíncrono) por ``task_publish_article`` após publicação
    bem-sucedida, e também por
    ``task_track_classic_website_article_pids_for_collection`` e
    ``task_check_articles_availability`` (verificação avulsa/em lote).

    Parameters
    ----------
    article_id : int, optional
        Não utilizado diretamente no corpo desta task (o artigo é obtido
        via ``article_proc.article``); mantido para compatibilidade e
        para os logs de erro.
    collection_id : int, optional
        Coleção usada para filtrar a verificação em
        ``article.check_availability``.
    website_kind : str, optional
        ``QA``/``PUBLIC``/``CLASSIC``; repassado como ``purpose`` para
        ``article.check_availability``.
    collection_acron : str, optional
        Recebido mas não utilizado no corpo atual desta task.
    timeout : int, optional
        Recebido mas não repassado explicitamente nesta implementação.
    force_update : bool, optional
        Se True, força nova verificação mesmo de páginas já válidas.
    article_proc_id : int
        ID do ``ArticleProc`` cujo artigo será verificado (obrigatório;
        usado para localizar o registro e propagar o resultado).
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
    Verifica disponibilidade de uma única ``ArticleWebPage``.

    Chama ``page.check_page`` (que faz a requisição HTTP e atualiza o
    status da página) e propaga o resultado automaticamente:
    ``ArticleWebPage`` → ``ArticleCollection``.

    Parameters
    ----------
    webpage_id : int
        ID da ``ArticleWebPage`` a verificar (obrigatório).
    article_metadata : dict, optional
        Metadados do artigo usados para validar o conteúdo da página.
    timeout : int, optional
        Timeout HTTP em segundos para a requisição.
    force_update : bool, optional
        Se True, re-verifica mesmo se a página já estiver com status
        válido.

    Note
    ----
    Nenhuma outra task deste módulo agenda ou chama
    ``task_check_article_page_availability`` diretamente; se estiver em
    uso, é provavelmente disparada por código de ``ArticleWebPage``/
    ``article.check_availability`` fora deste arquivo.
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
    estiverem válidas (``is_available=True``), define ``pid_status`` como
    ``PID_STATUS_PUBLIC_VALID`` via ``ArticleProc.set_pid_status``.

    Note
    ----
    Nenhuma outra task deste módulo agenda ou chama
    ``task_update_article_proc_availability`` diretamente —
    ``task_check_article_webpages`` já atualiza o ``pid_status``
    inline, sem despachar esta task. Confirmar se ela é usada como
    callback de uma chain/chord definida fora deste arquivo antes de
    considerá-la parte do pipeline ativo.
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
    Verificação em lote: busca ``ArticleProc`` por filtros e agenda verificação.

    Monta um filtro combinando (AND) ``article_pid_v3``,
    ``publication_year``, ``issue_folder`` e ``collection_acron`` com um
    filtro (OR) por ``issn_print``/``issn_electronic``, e agenda
    (assíncrono) ``task_check_article_webpages`` para cada ``ArticleProc``
    resultante (a criação/atualização da ``ArticleCollection`` é feita
    dentro de ``task_check_article_webpages``, não aqui).

    Parameters
    ----------
    username / user_id : str / int
        Identificação do usuário executor.
    issn_print / issn_electronic : str, optional
        Filtra por ISSN do periódico (OR lógico entre os dois).
    issue_folder / publication_year : str / int, optional
        Filtra por fascículo ou ano de publicação.
    article_pid_v3 : str, optional
        Filtra por artigo específico (via ``sps_pkg__pid_v3``).
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
    Confronta metadados do artigo com as páginas do site clássico e do site público.

    1. Garante as ``ArticleCollection`` do artigo
       (``create_or_update_article_collections``).
    2. Executa a verificação de disponibilidade
       (``article.check_availability``).
    3. Confronta o resultado com o site clássico
       (``article.available_on_classic_website``) e, se válido, atualiza
       ``pid_status`` via ``ArticleProc.set_pid_status``.
    4. Repete a checagem para o site público
       (``article.available_on_public_website``).

    O ``pid_status`` resultante reflete o resultado mais recente da
    verificação (ex.: CLASSIC_MATCHED, CLASSIC_MISMATCHED, CLASSIC_FOUND,
    CLASSIC_NOT_FOUND, ou os equivalentes de disponibilidade pública),
    conforme definido em ``migration_choices``.

    Parameters
    ----------
    article_proc_id : int
        ID do ``ArticleProc`` a verificar (obrigatório).
    timeout : int, optional
        Recebido mas não utilizado no corpo atual desta task.
    force_update : bool, optional
        Recebido mas não utilizado no corpo atual desta task.
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
