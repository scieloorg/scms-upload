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
          │   duplicados ou com sps_pkg.collection_pid_v2 ausente)
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
import time
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
    Wrapper para TaskTracker que registra, em ordem cronológica, as etapas
    executadas por uma task e persiste tudo em ``TaskTracker.detail`` ao
    finalizar.

    Postgres (jsonb) não preserva a ordem das chaves e o widget do admin
    as exibe em ordem alfabética; por isso a ordem é dada por listas e por
    prefixos numéricos nas chaves do nível de topo.

    Estrutura de ``detail``::

        {
          "1_summary": {
            "result": "completed" | "interrupted (ValueError: ...)",
            "duration": "1m05.2s",
            "total_to_process": 10, "total_processed": 9, "total_errors": 1,
            "status": {  # status dos *Proc antes e depois da execução
              "1_before": {"article": {"migration=TODO | qa_ws=TODO": 10}},
              "2_after": {"article": {"migration=TODO | qa_ws=TODO": 1,
                                      "migration=DONE | qa_ws=TODO": 9}},
              "3_changes": {"article": {"migration=TODO | qa_ws=TODO": "10 -> 1",
                                        "migration=DONE | qa_ws=TODO": "0 -> 9"}},
            },
            ...  # números registrados com add_number
          },
          "2_params": {...},
          "3_steps": [
            {"#1 Start": {"elapsed": "0.0s",
                          "status": {"article": {"migration=TODO": 10}}}},
            {"#2 migrate_document_records": {"elapsed": "3.1s", "response": {...}}},
            {"#3 Created or updated ...": {"elapsed": "3.2s",
                "status_changes": {"article": {"migration=TODO": "10 -> 1",
                                               "migration=DONE": "0 -> 9"}}}},
            {"#4 ERROR ValueError: ...": {"elapsed": "3.4s", "item": "S0034-..."}},
          ],
          "4_errors": [{"step": "#4", "item": ..., "type": ..., "message": ..., "traceback": [...]}],
          "5_data": ...,
        }
    """

    def __init__(self, name, item, params):
        self.params = params
        self.task_tracker = TaskTracker.create(
            name=name,
            item=item,
        )
        self.steps = []
        self.stats = {}
        self.errors = []
        self.journal_proc_id = None
        # distribuição de status por entidade (journal/issue/article):
        # a da primeira chamada de update_total_status e a mais recente
        self.first_status = {}
        self.last_status = {}
        self._started = time.monotonic()

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

    @staticmethod
    def _format_seconds(seconds):
        minutes, seconds = divmod(seconds, 60)
        if minutes:
            return f"{int(minutes)}m{seconds:04.1f}s"
        return f"{seconds:.1f}s"

    def _add_step(self, title, content=None):
        """
        Acrescenta uma etapa ``{"#N título": {"elapsed": ..., **content}}``,
        em que ``elapsed`` é o tempo decorrido desde o início da task;
        retorna o rótulo "#N".
        """
        number = f"#{len(self.steps) + 1}"
        values = {
            "elapsed": self._format_seconds(time.monotonic() - self._started)
        }
        values.update(content or {})
        self.steps.append({f"{number} {title}": values})
        return number

    @staticmethod
    def _parse_exception(exception):
        """
        Normaliza ``exception`` em dict com type / message / traceback.

        Aceita uma Exception, o texto de ``traceback.format_exc()``, uma
        mensagem simples ou um dict (mantido, com o traceback em linhas).
        """
        if isinstance(exception, BaseException):
            return {
                "type": type(exception).__name__,
                "message": str(exception),
            }
        if isinstance(exception, dict):
            error = dict(exception)
            if isinstance(error.get("traceback"), str):
                error.update(TaskExecution._parse_exception(error["traceback"]))
            return error
        text = str(exception).strip()
        if not text.startswith("Traceback"):
            return {"message": text}
        lines = text.splitlines()
        # última linha: "ModuleName.ErrorType: mensagem"
        error_type, _, message = lines[-1].partition(": ")
        return {
            "type": error_type.split(".")[-1],
            "message": message,
            "traceback": lines,
        }

    def add_exception(self, exception, item=None):
        """
        Registra uma falha que não interrompe a task (ex.: um artigo).

        Fica em ``4_errors`` (com traceback) e também como etapa ``ERROR``
        em ``3_steps``, para ser vista na sequência; ``step`` liga os dois.
        """
        error = self._parse_exception(exception)
        if item is not None:
            error["item"] = str(item)
        headline = ": ".join(
            str(x) for x in (error.get("type"), error.get("message")) if x
        )
        error["step"] = self._add_step(
            f"ERROR {headline}"[:200],
            {"item": error["item"]} if item is not None else None,
        )
        self.errors.append(error)

    def add_event(self, event):
        """
        Registra uma etapa. Se ``event`` é dict com "operation" ou "action",
        esse valor é o título da etapa e as demais chaves, o conteúdo.
        """
        if event is None:
            return
        if isinstance(event, list):
            for item in event:
                self.add_event(item)
            return
        if not isinstance(event, dict):
            self._add_step(str(event))
            return
        content = dict(event)
        title = content.pop("operation", None) or content.pop("action", None)
        if not title and len(content) == 1:
            # ex.: {"websites": [...]}
            title = next(iter(content))
        self._add_step(str(title or "event"), content)

    def add_number(self, name, number):
        self.stats[name] = number

    @staticmethod
    def _format_total_status(items):
        """
        Converte a lista de ``get_total_status`` em
        ``{"migration=DONE | qa_ws=TODO | public_ws=TODO": 23, ...}``.

        Aceita os formatos ``{"total": n, "status": {...}}`` e
        ``{..., "total": n}``.
        """
        formatted = {}
        for item in items or []:
            if not isinstance(item, dict):
                formatted[str(item)] = None
                continue
            if isinstance(item.get("status"), dict):
                status = item["status"]
            else:
                status = {k: v for k, v in item.items() if k != "total"}
            key = " | ".join(
                f"{name[:-len('_status')] if name.endswith('_status') else name}={value}"
                for name, value in status.items()
            )
            formatted[key] = formatted.get(key, 0) + (item.get("total") or 0)
        return formatted

    def update_total_status(self, label, issue_proc_id=None):
        """
        Registra a etapa ``label`` com a distribuição de status de
        journal/issue/article (via ``get_total_status_data``).

        Na primeira chamada registra a distribuição completa (``status``);
        nas seguintes, apenas o que mudou (``status_changes``), no formato
        ``{"migration=TODO": "10 -> 1", "migration=DONE": "0 -> 9"}``.
        """
        result = get_total_status_data(self.journal_proc_id, issue_proc_id)
        current = {
            key: self._format_total_status(items) for key, items in result.items()
        }
        if not self.first_status:
            self.first_status = current
            self.last_status = current
            self._add_step(label, {"status": current})
            return

        changes = self._status_changes(self.last_status, current)
        self.last_status = current
        self._add_step(label, {"status_changes": changes or "no changes"})

    @staticmethod
    def _status_changes(previous_status, current_status):
        """
        Compara duas distribuições de status e retorna somente as
        combinações cujo total mudou: ``{"article": {"migration=TODO": "10 -> 1"}}``.
        """
        changes = {}
        for key in list(previous_status) + [
            k for k in current_status if k not in previous_status
        ]:
            previous = previous_status.get(key) or {}
            current = current_status.get(key) or {}
            entity_changes = {}
            for combination in list(previous) + [
                c for c in current if c not in previous
            ]:
                before = previous.get(combination, 0)
                after = current.get(combination, 0)
                if before != after:
                    entity_changes[combination] = f"{before} -> {after}"
            if entity_changes:
                changes[key] = entity_changes
        return changes

    @classmethod
    def _to_json(cls, value):
        """
        Converte ``value`` em estrutura serializável em JSON e legível:
        conjuntos viram listas ordenadas, tuplas viram listas, chaves de
        dict que são tuplas viram ``"a | b"`` e demais objetos, ``str``.
        """
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, dict):
            return {
                (
                    " | ".join(str(k) for k in key)
                    if isinstance(key, tuple)
                    else key if isinstance(key, str) else str(key)
                ): cls._to_json(item)
                for key, item in value.items()
            }
        if isinstance(value, (set, frozenset)):
            try:
                value = sorted(value)
            except TypeError:
                value = sorted(value, key=str)
            return [cls._to_json(item) for item in value]
        if isinstance(value, (list, tuple)):
            return [cls._to_json(item) for item in value]
        return str(value)

    def finish(self, exception=None, exc_traceback=None, data=None):
        try:
            if exception or exc_traceback or self.errors:
                completed = False
            else:
                completed = True

            if exception:
                result = f"interrupted ({type(exception).__name__}: {exception})"
            elif exc_traceback:
                result = "interrupted"
            elif self.errors:
                result = "completed with errors"
            else:
                result = "completed"

            summary = dict(self.stats)
            summary.update({
                "result": result,
                "duration": self._format_seconds(time.monotonic() - self._started),
                "total_to_process": self.total_to_process,
                "total_processed": self.total_processed,
                "total_errors": len(self.errors),
            })
            if self.first_status:
                # status dos *Proc antes e depois da execução
                summary["status"] = {
                    "1_before": self.first_status,
                    "2_after": self.last_status,
                    "3_changes": (
                        self._status_changes(self.first_status, self.last_status)
                        or "no changes"
                    ),
                }

            detail = {
                "1_summary": summary,
                "2_params": self.params,
                "3_steps": self.steps,
                "4_errors": self.errors,
            }
            if data:
                detail["5_data"] = data
            detail = self._to_json(detail)
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
    # sem efeito: lembrete, no agendamento, dos valores aceitos em status
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

        if classic_website:
            # cria ou atualiza MigratedJournal / JournalProc;
            # só muda JournalProc.migration_status se os dados mudaram
            create_or_update_migrated_journal(
                user,
                collection,
                classic_website,
                force_update or force_import_acron_id_file,
            )
        # na rotina (sem status explícito), inclui também os periódicos com
        # demanda de sincronização com o core; com status explícito, somente
        # os que têm os status solicitados
        include_core_sync_demand = not status
        status = tracker_choices.get_valid_status(status, force_update)
        JournalProc.fix_publication_status(collection)

        journal_filter = {}
        if journal_acron:
            journal_filter["acron"] = journal_acron

        if force_core_sync:
            journal_proc_ids = set(
                JournalProc.objects.filter(
                    collection=collection, **journal_filter
                ).values_list("id", flat=True)
            )
        else:
            journal_proc_ids = JournalProc.select_items_to_process(
                collection,
                status,
                params=journal_filter,
                include_core_sync_demand=include_core_sync_demand,
            )
        journal_proc_ids = sorted(journal_proc_ids)
        task_exec.total_to_process = len(journal_proc_ids)
        if not task_exec.total_to_process:
            task_exec.finish()
            return

        qa_api_data = get_api_data(collection, "journal", QA)
        public_api_data = get_api_data(collection, "journal", PUBLIC)

        total_scheduled = 0
        for journal_proc_id in journal_proc_ids:
            task_migrate_and_publish_journal.apply_async(
                kwargs=dict(
                    user_id=user_id,
                    username=username,
                    journal_proc_id=journal_proc_id,
                    force_update=force_update,
                    force_core_sync=force_core_sync,
                    collection_acron=collection.acron,
                    qa_api_data=qa_api_data,
                    public_api_data=public_api_data,
                    status=status,
                )
            )
            total_scheduled += 1

        task_exec.total_processed = total_scheduled
        task_exec.finish(data={"scheduled": journal_proc_ids})
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
def task_migrate_and_publish_journal(
    self,
    user_id=None,
    username=None,
    journal_proc_id=None,
    force_update=False,
    force_core_sync=False,
    collection_acron=None,
    qa_api_data=None,
    public_api_data=None,
    status=None,
):
    """
    Migra (se ``migration_status`` em ``status``, se há demanda de
    sincronização com o core ou se ``force_core_sync``) e publica um único
    periódico (JournalProc). A decisão usa os status no momento da execução.

    Fonte dos dados na migração:
    - core, se ``force_core_sync`` ou se o JournalProc não tem dados do
      site clássico (``migrated_data``), como os de coleções sem site
      clássico; se o periódico continuar sem sincronização, torna-se BLOCKED
    - site clássico, nos demais casos, pois por ora seus dados são os mais
      atuais (a migração atende a demanda: core_synchronized=True)

    Após a migração, se ``migration_status=DONE``, publica em sequência no
    QA e no PUBLIC, conforme ``qa_ws_status``/``public_ws_status`` estejam
    em ``status`` (ver ``BaseProc.publish_on_websites``).

    Retorna True se o periódico está migrado e as publicações solicitadas
    foram concluídas.
    """
    detail = {}
    event = None
    journal_proc = None
    try:
        user = _get_user(user_id, username)
        journal_proc = JournalProc.objects.get(id=journal_proc_id)
        status = tracker_choices.get_valid_status(status, force_update)

        event = journal_proc.start(user, "migrate and publish journal")
        migrate = (
            force_core_sync
            or journal_proc.migration_status in status
            or journal_proc.needs_core_sync
        )

        issn_electronic = journal_proc.issn_electronic
        issn_print = journal_proc.issn_print
        # sem ISSN, a consulta ao core retornaria todos os periódicos da coleção
        use_core = (issn_electronic or issn_print) and (
            force_core_sync or (migrate and not journal_proc.migrated_data)
        )
        if use_core:
            fetch_and_create_journal(
                user,
                collection_acron=collection_acron,
                issn_electronic=issn_electronic,
                issn_print=issn_print,
                force_update=True,
            )
            journal_proc.refresh_from_db()
            detail["journal_data_source"] = "core data"
            if journal_proc.needs_core_sync or not journal_proc.journal:
                # o core não tem o periódico ou a coleta não foi concluída;
                # BLOCKED evita nova tentativa a cada execução da rotina
                # (reprocessar com status=["BLOCKED"] ou force_core_sync)
                journal_proc.migration_status = tracker_choices.PROGRESS_STATUS_BLOCKED
                journal_proc.save()
                detail["error"] = "journal not synchronized with core data"
        elif migrate and journal_proc.migrated_data:
            journal_proc.create_or_update_item(
                user, force_update, migration_controller.create_or_update_journal
            )
            detail["journal_data_source"] = "classic website data"
        elif migrate:
            # sem dados do site clássico e sem ISSN para consultar o core:
            # aguarda os dados do title (ao chegarem, torna-se REPROC)
            journal_proc.migration_status = tracker_choices.PROGRESS_STATUS_PENDING
            journal_proc.save()
            detail["journal_data_source"] = None
            detail["error"] = "no classic website data and no ISSN to fetch core data"

        detail["migration_status"] = journal_proc.migration_status
        migrated = (
            journal_proc.migration_status == tracker_choices.PROGRESS_STATUS_DONE
        )
        published = True
        if migrated:
            publication_status = JournalProc.get_status_to_publish(
                status, migrated=migrate
            )
            publication = journal_proc.publish_on_websites(
                user,
                publish_journal,
                "journal",
                qa_api_data,
                public_api_data,
                publication_status,
                force_update,
            )
            detail["publication"] = publication
            published = all(
                item.get("completed", True) for item in publication.values()
            )

        completed = migrated and published
        event.finish(user, completed=completed, detail=detail)
        return completed
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
                action="proc.tasks.task_migrate_and_publish_journal",
                item=f"{journal_proc or journal_proc_id}",
                e=e,
                exc_traceback=exc_traceback,
                detail=detail,
            )
        return False


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
            JournalProc.fix_publication_status(collection)
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
    # sem efeito: lembrete, no agendamento, dos valores aceitos em status
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
    # sem efeito: lembrete, no agendamento, dos valores aceitos em status
    valid_status=None,
    force_update=False,
    force_migrate_document_records=False,
):
    """
    Migra e publica fascículos de uma coleção.

    Importa dados do site clássico via ``create_or_update_migrated_issue``
    e seleciona (``IssueProc.select_items_to_process``) somente os
    ``IssueProc`` cujos status estão em ``status``: executa
    ``migrate_issue`` nos que têm ``migration_status`` em ``status`` e
    agenda ``task_publish_issue`` no QA/PUBLIC somente se
    ``qa_ws_status``/``public_ws_status`` estiver em ``status`` (ou se o
    fascículo acabou de ser migrado; ver ``BaseProc.get_status_to_publish``).
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
        IssueProc.fix_publication_status(collection)
        params = {}
        if journal_acron:
            params["journal_proc__acron"] = journal_acron
        if issue_folder:
            params["issue_folder"] = issue_folder
        if publication_year:
            params["issue__publication_year"] = publication_year
        status = tracker_choices.get_valid_status(status, force_update)
        issue_proc_ids = IssueProc.select_items_to_process(
            collection, status, params=params
        )
        task_exec.total_to_process = len(issue_proc_ids)

        if not task_exec.total_to_process:
            task_exec.finish()
            return

        qa_api_data = get_api_data(collection, "issue", QA)
        public_api_data = get_api_data(collection, "issue", PUBLIC)
        websites = (
            (QA, qa_api_data, "qa_ws_status"),
            (PUBLIC, public_api_data, "public_ws_status"),
        )

        for issue_proc in IssueProc.objects.filter(id__in=issue_proc_ids):
            try:
                # decide com o status atual; a migração altera os de publicação
                migrate = issue_proc.migration_status in status
                if migrate:
                    migrate_issue(user, issue_proc, force_update)
                if not issue_proc.journal_proc or (
                    issue_proc.migration_status != tracker_choices.PROGRESS_STATUS_DONE
                ):
                    # migração falhou (ex.: JournalProc não encontrado);
                    # não há como publicar o fascículo
                    task_exec.add_exception(
                        f"Skip publish {issue_proc}: migration_status={issue_proc.migration_status}, "
                        f"journal_proc={issue_proc.journal_proc}"
                    )
                    continue
                publication_status = IssueProc.get_status_to_publish(
                    status, migrated=migrate
                )
                for website_kind, api_data, status_field in websites:
                    if not api_data or api_data.get("error"):
                        continue
                    if getattr(issue_proc, status_field) not in publication_status:
                        continue
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
                task_exec.total_processed += 1
            except Exception as e:
                exc_type, exc_value, exc_traceback = sys.exc_info()
                task_exec.add_exception(traceback.format_exc(), item=issue_proc)
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
            IssueProc.fix_publication_status(collection)
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
                        task_exec.add_exception(traceback.format_exc(), item=issue_proc)
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
    # sem efeito: lembrete, no agendamento, dos valores aceitos em status
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
    valid_status : list, optional
        Sem efeito. Presente no agendamento apenas como lembrete dos
        valores aceitos em ``status``.
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
        reconciliação de ``sps_pkg.collection_pid_v2`` reportar falhas (ver docstring
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

        user = _get_user(user_id, username)
        response = ArticleProc.mark_to_reproc_item_which_sps_pkg_pid_v2_is_incorrect(
            user,
            journal_acron_list=journal_acron_list,
            collection_acron_list=collection_acron_list,
        )
        task_exec.add_event({
            "operation": "Marked to reproc articles whose sps_pkg.pid_v2 is incorrect",
            "total_marked_to_reproc": len(response.get("marked_to_reproc") or []),
            "total_failures": len(response.get("failures") or {}),
            **response,
        })

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
        # por acrônimo do periódico: id do JournalProc e fascículos selecionados
        selected = {
            journal_acron: {
                "journal_proc_id": journal_proc_id,
                "issue_folder": journal_items.get("issue_folder"),
                "issue_proc_id_list": sorted(
                    journal_items.get("issue_proc_id_list") or []
                ),
            }
            for (journal_proc_id, journal_acron), journal_items in sorted(
                items_to_process.items(), key=lambda item: str(item[0][1])
            )
        }
        total_journals_to_process = len(selected)
        total_issues_to_process = sum(
            len(item["issue_proc_id_list"]) for item in selected.values()
        )
        task_exec.add_event({
            "operation": "Selected journals and issues to process",
            "total_journals": total_journals_to_process,
            "total_issues": total_issues_to_process,
        })
        task_exec.add_number("total_issues_to_process", total_issues_to_process)

        task_exec.total_to_process = total_journals_to_process
        total_processed = 0
        for journal_acron, journal_items in selected.items():
            journal_proc_id = journal_items["journal_proc_id"]
            issue_proc_id_list = journal_items["issue_proc_id_list"]
            task_migrate_and_publish_articles_by_journal.delay(
                user_id=user_id,
                username=username,
                collection_acron=collection_acron,
                journal_acron=journal_acron,
                journal_proc_id=journal_proc_id,
                issue_folder=journal_items.get("issue_folder"),
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
            "operation": "Scheduled task_migrate_and_publish_articles_by_journal",
            "total_scheduled": total_processed,
        })
        task_exec.total_processed = total_processed
        task_exec.finish(data={"scheduled": selected})

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

    1. ``ArticleProc.fix_publication_status``: normaliza ``qa_ws_status``/``public_ws_status``
       dos artigos conforme os websites habilitados na coleção.
    2. ``controller.import_journal_acron_id_records``: importa/atualiza o
       arquivo acron.id do periódico (respeitando ``force_import_acron_id_file``).
    3. Fascículos a processar: os de ``issue_proc_id_list`` (selecionados
       por ``task_migrate_and_publish_articles`` via
       ``ArticleProc.get_journal_and_issue_proc_ids``) e os com registros
       novos ou alterados no acron.id (``issue_proc_id_list`` da resposta
       de ``import_journal_acron_id_records``).
    4. Para cada fascículo, executa **de forma síncrona**
       ``task_fix_issue_articles`` (corrige/exclui ``SPSPkg``/``Article``/``ArticleProc``
       inconsistentes antes da migração) e então agenda, de forma
       assíncrona, ``task_migrate_and_publish_articles_by_issue`` repassando
       a resposta de ``task_fix_issue_articles`` em
       ``exclude_invalid_articles_response``. A decisão de migrar e de
       publicar cada artigo é tomada nessa tarefa.
    """
    task_params = {
        "user_id": user_id,
        "username": username,
        "collection_acron": collection_acron,
        "journal_acron": journal_acron,
        "publication_year": publication_year,
        "issue_folder": issue_folder,
        "issue_proc_id_list": issue_proc_id_list,
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

        ArticleProc.fix_publication_status(journal_proc.collection)
        task_exec.update_total_status(("Updated publication status"))

        # a partir de acron.id, cria ou atualiza JournalAcronIdFile e IdFileRecord,
        # fonte para criar/atualizar ArticleProc
        response = migration_controller.import_journal_acron_id_records(
            user,
            journal_proc,
            force_update=force_import_acron_id_file,
        )

        # resumo da importação: sem repetir params/stats e sem a lista
        # completa de fascículos do acron.id (só os pendentes)
        id_file_data = response.get("journal_id_file_data") or {}
        id_file_exceptions = response.get("exceptions") or []
        imported = {
            "operation": "Imported journal acron.id",
            "source_path": response.get("source_path"),
            "acron_id_last_updated": id_file_data.get("journal_id_file_last_updated"),
            "records_last_updated": id_file_data.get("id_file_record_last_updated"),
            **(response.get("stats") or {}),
            "pending_issue_pids": id_file_data.get("pending_issue_pids") or [],
            "pending_issue_proc_id_list": response.get("issue_proc_id_list") or [],
            "total_exceptions": len(id_file_exceptions),
        }
        if response.get("message"):
            imported["message"] = response["message"]
        if id_file_exceptions:
            imported["exceptions"] = id_file_exceptions
        task_exec.add_event(imported)
        if response.get("traceback"):
            task_exec.add_exception(response["traceback"], item=journal_acron)

        task_exec.update_total_status(label="Status after importing acron.id")

        qa_api_data = get_api_data(
            journal_proc.collection, "issue", "QA"
        )
        public_api_data = get_api_data(
            journal_proc.collection, "issue", "PUBLIC"
        )
        total_processed = 0
        requested_issue_proc_ids = set(issue_proc_id_list or [])
        pending_issue_proc_ids = set(response.get("issue_proc_id_list") or [])
        issue_proc_id_list = sorted(requested_issue_proc_ids | pending_issue_proc_ids)
        total_to_process = len(issue_proc_id_list)
        task_exec.add_event({
            "operation": "Selected issues to process",
            "total_issues": total_to_process,
            "total_requested": len(requested_issue_proc_ids),
            "total_pending_in_acron_id": len(pending_issue_proc_ids),
        })

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
            if isinstance(response, dict) and response.get("traceback"):
                task_exec.add_exception(
                    response["traceback"],
                    item=f"task_fix_issue_articles issue_proc_id={issue_proc_id}",
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
        task_exec.add_event({
            "operation": "Scheduled task_migrate_and_publish_articles_by_issue",
            "total_scheduled": total_processed,
        })
        task_exec.total_processed = total_processed
        task_exec.total_to_process = total_to_process
        task_exec.finish(data={"scheduled_issue_proc_id_list": issue_proc_id_list})
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

    1. ``issue_proc.migrate_document_records``: cria/atualiza os
       ``ArticleProc`` do fascículo a partir do site clássico (registros
       com novidades, sem ArticleProc ou cujo ArticleProc tem
       ``migration_status`` em ``status``, exceto TODO/REPROC). Os com dados novos
       têm o processo resetado (todas as fases TODO).
    2. ``issue_proc.migrate_document_files``: cria/atualiza os
       ``MigratedFile`` (pacotes SPS) do fascículo via
       ``controller.migrate_issue_files``.
    3. ``ArticleProc.select_items``: seleciona os ``ArticleProc`` com algum
       status em ``status`` (todos, se ``force_update``) e os resetados
       no passo 1.

    Para cada ``ArticleProc`` selecionado, decide com os status atuais:

    - migra (``article_proc.migrate_article``: retoma da primeira fase não
      concluída — XML, pacote SPS/pid provider, Article) se
      ``force_update``, se resetado no passo 1 ou se
      ``article_proc.needs_migration(status)``
    - senão, se já migrado (DONE), apenas o publica

    Falhas individuais são registradas em ``task_exec`` mas não
    interrompem o loop.

    Ao final, agenda (assíncrono) ``task_publish_issue_articles`` com os
    artigos migrados nesta execução e os a apenas publicar, para
    publicá-los e sincronizar o TOC.

    Parameters
    ----------
    issue_proc_id : int
        ID do ``IssueProc`` cujo fascículo será migrado.
    status : list, optional
        Lista de status usada na seleção e na decisão de migrar/publicar.
    force_update : bool, default False
        Se True, ignora o filtro de status ao selecionar artigos e força
        remigração em ``migrate_article``.
    force_migrate_document_records / force_migrate_document_files : bool, default False
        Forçam a remigração de registros/arquivos do fascículo mesmo que
        já tenham sido migrados anteriormente.
    qa_api_data / public_api_data : dict, optional
        Sem efeito: ``task_publish_issue_articles`` obtém os dados de API
        de cada website habilitado.
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
            user, force_migrate_document_records, status=status
        )
        # resetados nesta execução (dados novos ou retomada do registro):
        # migrados mesmo que status não inclua TODO/REPROC
        reset_article_proc_ids = set(response.get("reset_article_proc_ids") or [])
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
            include_id_list=list(reset_article_proc_ids),
        )

        total_processed = 0
        exceptions = {}
        migrated_ids = []
        to_publish_ids = []
        for article_proc in article_procs:
            try:
                # decide com o status atual: migra somente os que precisam;
                # os já migrados (DONE) são apenas publicados
                was_reset = article_proc.id in reset_article_proc_ids
                if (
                    force_update
                    or was_reset
                    or article_proc.needs_migration(status)
                ):
                    # executa get_xml, generate_sps_pkg, cria / atualiza Article
                    article = article_proc.migrate_article(user, force_update)
                    if article:
                        migrated_ids.append(article_proc.id)
                        total_processed += 1
                elif (
                    article_proc.migration_status
                    == tracker_choices.PROGRESS_STATUS_DONE
                ):
                    to_publish_ids.append(article_proc.id)
            except Exception as e:
                exc_type, exc_value, exc_traceback = sys.exc_info()
                exceptions[article_proc.pid] = traceback.format_exc()
                task_exec.add_exception(
                    exceptions[article_proc.pid], item=article_proc.pid
                )
        task_exec.update_total_status(("Created or updated SPS Package and Article records"), issue_proc_id)

        task_exec.total_processed = total_processed
        task_exec.add_number("total_processed", total_processed)
        task_exec.add_number("total_to_publish_only", len(to_publish_ids))
        task_exec.add_number("total_articleprocs", issue_proc.articleproc_set.count())

        task_publish_issue_articles.delay(
            user_id=user_id,
            username=username,
            issue_proc_id=issue_proc_id,
            status=status,
            articleprocs_id_list=migrated_ids + to_publish_ids,
            force_update=force_update,
            migrated_articleprocs_id_list=migrated_ids,
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
    articleprocs_id_list=None,
    force_update=False,
    migrated_articleprocs_id_list=None,
):
    """
    Publica artigos de um fascículo e sincroniza o fascículo no site.

    Considera os ``ArticleProc`` de ``articleprocs_id_list`` ou, se não
    informado (publicação avulsa, ``task_publish_articles``), todos os do
    fascículo. Para cada ``WebSiteConfiguration`` habilitada da coleção,
    primeiro QA e depois PUBLIC:

    1. Seleciona os artigos a publicar naquele website
       (``ArticleProc.select_items_to_publish``): migrados (DONE), com pid
       v3 e com ``qa_ws_status``/``public_ws_status`` em ``status`` (os de
       ``migrated_articleprocs_id_list``, também os pendentes); no PUBLIC,
       somente os já publicados no QA ou cujo QA não é usado.
    2. Publica cada artigo via ``task_publish_article``
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
    articleprocs_id_list : list[int], optional
        ``ArticleProc`` a considerar; se None, todos os do fascículo.
    force_update : bool, default False
        Se True, ignora o filtro de status (publica mesmo artigos já
        publicados).
    migrated_articleprocs_id_list : list[int], optional
        ``ArticleProc`` migrados nesta execução: são publicados também se
        pendentes (TODO/REPROC), mesmo que não estejam em ``status``
        (ver ``BaseProc.get_status_to_publish``).
    """
    task_params = {
        "user_id": user_id,
        "username": username,
        "issue_proc_id": issue_proc_id,
        "articleprocs_id_list": articleprocs_id_list,
        "migrated_articleprocs_id_list": migrated_articleprocs_id_list,
        "status": status,
        "force_update": force_update,
    }
    task_exec = TaskExecution(
        name="proc.tasks.task_publish_issue_articles",
        item=f"{issue_proc_id}",
        params=task_params,
    )
    websites_summary = []
    total_to_process = 0
    total_processed = 0
    total_failed = 0
    try:
        user = _get_user(user_id, username)
        status = tracker_choices.get_valid_status(status, force_update)

        issue_proc = IssueProc.objects.select_related("collection").get(
            pk=issue_proc_id
        )
        if articleprocs_id_list is None:
            # publicação avulsa (task_publish_articles): artigos do fascículo
            articles = ArticleProc.objects.filter(issue_proc=issue_proc)
        else:
            articles = ArticleProc.objects.filter(id__in=articleprocs_id_list)

        task_exec.item = f"{issue_proc}"
        task_exec.journal_proc_id = issue_proc.journal_proc_id
        task_exec.update_total_status("Start", issue_proc_id)

        collection = issue_proc.collection
        ArticleProc.fix_publication_status(collection)
        task_exec.update_total_status("Updated publication status", issue_proc_id)

        # QA antes do PUBLIC: no PUBLIC, somente os já publicados no QA
        websites = sorted(
            WebSiteConfiguration.objects.filter(
                collection=collection, enabled=True, purpose__in=(QA, PUBLIC)
            ),
            key=lambda website: website.purpose != QA,
        )
        for website in websites:
            api_data = website.get_data(content_type="article")
            website_kind = website.purpose

            article_ids_to_publish = ArticleProc.select_items_to_publish(
                articles,
                website_kind,
                status,
                migrated_ids=migrated_articleprocs_id_list,
            )
            total_to_publish = len(article_ids_to_publish)
            total_to_process += total_to_publish

            total_published = 0
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
                except Exception:
                    total_failed += 1
                    task_exec.add_exception(
                        traceback.format_exc(),
                        item=f"{website_kind} article_proc_id={article_proc_id}",
                    )

            total_processed += total_published
            websites_summary.append({
                "website": str(website),
                "website_id": website.id,
                "purpose": website_kind,
                "total_to_publish": total_to_publish,
                "total_published": total_published,
                "total_failed": total_to_publish - total_published,
            })
            task_exec.update_total_status(
                f"Total article published on {website_kind}: "
                f"{total_published}/{total_to_publish}",
                issue_proc_id,
            )

            task_sync_issue.delay(
                user_id=user_id,
                username=username,
                website_kind=website_kind,
                issue_proc_id=issue_proc_id,
                api_data=api_data,
            )
            task_exec.add_event({"operation": "Scheduled issue synchronization"})

        task_exec.add_event({"websites": websites_summary})
        task_exec.total_to_process = total_to_process
        task_exec.total_processed = total_processed
        task_exec.finish()
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        task_exec.add_event({"websites": websites_summary})
        task_exec.total_to_process = total_to_process
        task_exec.total_processed = total_processed
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
    (``ArticleProc.fix_publication_status``), seleciona ``IssueProc`` via
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
            ArticleProc.fix_publication_status(collection)
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
       ``sps_pkg.collection_pid_v2`` dos ArticleProc do fascículo ainda sem PidProviderXML
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
        # Filtra ArticleProc por issue_proc_id e vincula ArticleProc.sps_pkg
        # ao documento na coleção (collection_pid_v2), consultando o pid
        # provider com sps_pkg.file
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
        article.create_or_update_article_collections(user, force_update=force_update)
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
        Repassado para ``article.check_availability``.
    force_update : bool, optional
        Se True, força a reconstrução das URLs a partir da
        ``WebSiteConfiguration`` vigente e uma nova verificação mesmo de
        páginas já válidas.
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
        
        article.create_or_update_article_collections(user, force_update=force_update)
        article.check_availability(user, force_update=force_update, timeout=timeout)

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
