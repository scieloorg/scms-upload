import logging
import sys

from django.db.models import Q, Count
from django.utils.translation import gettext_lazy as _

from migration import choices as migration_choices
from proc.models import ArticleProc


def log_event(execution_log, level, event_type, message, extra_data=None):
    """
    Adiciona um evento ao log de execução

    Args:
        execution_log: Lista onde o evento será adicionado
        level: Nível do log (info, warning, error)
        event_type: Tipo do evento (initialization, migration_failed, etc)
        message: Mensagem descritiva
        **extra_data: Dados adicionais do evento
    """
    event = {
        "message": message,
    }
    if extra_data:
        event["data"] = extra_data
    execution_log.append(event)


def schedule_article_publication(
    task_publish_article,
    article_proc_id,
    user_id,
    username,
    qa_api_data,
    public_api_data,
    force_update,
):
    """
    Agenda a publicação de um artigo nos websites QA e PUBLIC

    Args:
        task_publish_article: A task celery para publicação
        article_proc_id: ID do ArticleProc
        user_id: ID do usuário
        username: Nome do usuário
        qa_api_data: Dados da API QA
        public_api_data: Dados da API PUBLIC
        force_update: Flag para forçar atualização

    Returns:
        dict: Status de agendamento {"qa": bool, "public": bool}
    """
    scheduled = {"qa": False, "public": False}

    if not qa_api_data.get("error"):
        task_publish_article.apply_async(
            kwargs=dict(
                user_id=user_id,
                username=username,
                website_kind="QA",
                article_proc_id=article_proc_id,
                api_data=qa_api_data,
                force_update=force_update,
            )
        )
        scheduled["qa"] = True

    if not public_api_data.get("error"):
        task_publish_article.apply_async(
            kwargs=dict(
                user_id=user_id,
                username=username,
                website_kind="PUBLIC",
                article_proc_id=article_proc_id,
                api_data=public_api_data,
                force_update=force_update,
            )
        )
        scheduled["public"] = True

    return scheduled


def migrate_collection_articles(user, collection_acron, items, force_update):
    statistics = {
        "total_articles_to_process": 0,
        "total_articles_migrated": 0,
    }
    execution_log = []
    articles_count = items.count()
    statistics["total_articles_to_process"] = articles_count

    log_event(
        execution_log,
        "info",
        "articles_migration",
        f"Found {articles_count} articles to migrate",
        dict(
            collection=collection_acron,
            count=articles_count,
        ),
    )
    articles_migrated = 0
    for article_proc in items.iterator():
        try:
            logging.info(f"Migrating article_proc {article_proc}")
            article = article_proc.migrate_article(user, force_update)
            if article:
                articles_migrated += 1
        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            event = article_proc.start(user, "Migrate article error")
            event.finish(
                user,
                completed=False,
                exception=e,
                exc_traceback=exc_traceback,
            )

    statistics["total_articles_migrated"] = articles_migrated
    return statistics, execution_log


def publish_collection_articles(
    user,
    collection_acron,
    items,
    task_publish_article,
    qa_api_data,
    public_api_data,
    force_update,
):
    execution_log = []
    qa_scheduled = 0
    public_scheduled = 0
    processed = 0
    articles_count = items.count()

    log_event(
        execution_log,
        "info",
        "articles_publication",
        f"Found {articles_count} articles to publish",
        dict(
            collection=collection_acron,
            count=articles_count,
            qa_api_data_error=qa_api_data.get("error"),
            public_api_data_error=public_api_data.get("error"),
        ),
    )

    if not qa_api_data.get("error") or not public_api_data.get("error"):
        for article_proc in items.iterator():
            try:
                processed += 1
                response = schedule_article_publication(
                    task_publish_article,
                    article_proc.id,
                    user.id,
                    user.username,
                    qa_api_data,
                    public_api_data,
                    force_update,
                )
                if response["qa"]:
                    qa_scheduled += 1

                if response["public"]:
                    public_scheduled += 1

            except Exception as e:
                exc_type, exc_value, exc_traceback = sys.exc_info()
                event = article_proc.start(user, "Schedule article publication error")
                event.finish(
                    user,
                    completed=False,
                    exception=e,
                    exc_traceback=exc_traceback,
                )

    statistics = {}
    statistics["total_articles_to_publish"] = articles_count
    statistics["processed"] = processed
    statistics["total_qa_scheduled"] = qa_scheduled
    statistics["total_publich_scheduled"] = public_scheduled
    statistics["qa_api_data_error"] = bool(qa_api_data.get("error"))
    statistics["public_api_data_error"] = bool(public_api_data.get("error"))
    return statistics, execution_log


class ClassicWebsiteArticlePidTracker:
    TASK_NAME = "proc.source_classic_website.track_classic_website_article_pids"

    def __init__(self, user, collection):
        self.user = user
        self.collection = collection

    def create_article_proc_for_pids(self, pids):
        if not pids:
            return []
        registered_pids = set(
            ArticleProc.objects.filter(
                collection=self.collection, pid__in=pids
            ).values_list("pid", flat=True)
        )
        todo = set(pids) - registered_pids
        for pid in todo:
            yield ArticleProc(
                pid=pid,
                collection=self.collection,
                creator=self.user,
                pid_status=migration_choices.PID_STATUS_MISSING,
            )

    def update_pid_status(self, classic_website_pids):
        """
        Atualiza o `pid_status` dos `ArticleProc` da coleção comparando os
        PIDs registrados no banco com a lista de PIDs do site clássico
        (`classic_website_pids`).

        Regras de classificação:
            - `matched`: PID está em `classic_website_pids` **e** o
              `ArticleProc` já possui `migrated_data` (artigo migrado com
              sucesso).
            - `missing`: PID está em `classic_website_pids` **mas** o
              `ArticleProc` ainda não possui `migrated_data` (artigo
              presente no site clássico, mas pendente de migração).
            - `exceeding`: PID **não** está em `classic_website_pids`
              (existe no `ArticleProc` mas não no site clássico — ou seja,
              está "sobrando" em relação à fonte de verdade).

        Observações importantes:
            - O queryset base não exclui registros previamente marcados
              como `EXCEEDING`, permitindo que sejam reclassificados caso
              passem a constar na lista de entrada.
            - O retorno é o conjunto de PIDs da entrada que **não**
              correspondem a nenhum `ArticleProc` existente — usado pelo
              chamador para criar os registros faltantes.

        Parâmetros:
            classic_website_pids (iterable[str]): PIDs vindos do site
                clássico (fonte de verdade) para a coleção corrente.

        Retorno:
            set[str]: PIDs que estão em `classic_website_pids` mas ainda
            não possuem um `ArticleProc` correspondente.
        """
        # A lista de PIDs do site clássico pode ser muito grande (centenas
        # de milhares de itens). Para preservar memória e evitar passar
        # cláusulas `IN (...)` enormes para o banco — que podem estourar o
        # limite de parâmetros e tornar as queries lentas — esta
        # implementação:
        #
        # 1. Reaproveita a entrada se já for `set`/`frozenset`, evitando
        #    uma cópia integral. Caso contrário materializa uma única vez
        #    (suportando generators e demais iteráveis de uso único).
        # 2. Itera os `ArticleProc` da coleção em streaming
        #    (`.iterator(chunk_size=...)`) — só o filtro indexado por
        #    `collection` vai ao banco, sem `pid__in` gigante.
        # 3. Decide o status alvo de cada `ArticleProc` em Python
        #    consultando `pid in all_pids` (O(1) em set) e o
        #    `migrated_data_id`. Coleta apenas os PKs que precisam mudar.
        # 4. Aplica os UPDATEs em lotes pequenos por PK, mantendo a
        #    quantidade de parâmetros por query previsível.
        # 5. Computa o retorno (PIDs da entrada sem `ArticleProc`
        #    correspondente) durante a mesma varredura, sem uma query
        #    extra com `pid__in=all_pids`.
        if isinstance(classic_website_pids, (set, frozenset)):
            all_pids = classic_website_pids
        else:
            all_pids = set(classic_website_pids)

        MATCHED = migration_choices.PID_STATUS_MATCHED
        MISSING = migration_choices.PID_STATUS_MISSING
        EXCEEDING = migration_choices.PID_STATUS_EXCEEDING

        to_matched = []
        to_missing = []
        to_exceeding = []
        existing_pids = set()

        # Streaming dos ArticleProc da coleção; só carrega os campos
        # necessários para a decisão.
        rows = (
            ArticleProc.objects
            .filter(collection=self.collection)
            .values_list("pk", "pid", "pid_status", "migrated_data_id")
            .iterator(chunk_size=2000)
        )

        for pk, pid, current_status, migrated_data_id in rows:
            if pid in all_pids:
                # Marca como existente para excluir do retorno (o que
                # sobrar em `all_pids - existing_pids` são PIDs sem
                # ArticleProc, que o chamador irá criar).
                existing_pids.add(pid)
                # MATCHED: PID consta na lista do site clássico E o
                # artigo já foi migrado.
                # MISSING: PID consta na lista, mas `migrated_data`
                # ainda é NULL (inclui o caso em que era MATCHED e o
                # `MigratedData` foi removido via `on_delete=SET_NULL`).
                target = MATCHED if migrated_data_id is not None else MISSING
            else:
                # EXCEEDING: ArticleProc cujo PID NÃO está na lista do
                # site clássico. Avaliado independentemente do
                # `pid_status` anterior, permitindo reclassificar
                # registros previamente EXCEEDING.
                target = EXCEEDING

            if current_status == target:
                continue

            if target == MATCHED:
                to_matched.append(pk)
            elif target == MISSING:
                to_missing.append(pk)
            else:
                to_exceeding.append(pk)

        # Aplica os updates em lotes pequenos por PK para manter cada
        # cláusula `IN (...)` com tamanho previsível.
        base = ArticleProc.objects.filter(collection=self.collection)
        batch_size = 1000
        for pks, status in (
            (to_matched, MATCHED),
            (to_missing, MISSING),
            (to_exceeding, EXCEEDING),
        ):
            for start in range(0, len(pks), batch_size):
                base.filter(pk__in=pks[start:start + batch_size]).update(
                    pid_status=status
                )

        return all_pids - existing_pids
    
    def bulk_create(self, new_pids):
        if new_pids:
            ArticleProc.objects.bulk_create(self.create_article_proc_for_pids(new_pids), batch_size=500)


def track_classic_website_article_pids(
    user, collection, classic_website_config,
):
    tracker = ClassicWebsiteArticlePidTracker(user, collection)
    classic_website_pids = set(classic_website_config.get_pid_list())

    new_pids = set(tracker.update_pid_status(classic_website_pids))
    tracker.bulk_create(new_pids)
    
    data = {"collection": collection.acron}
    for item in ArticleProc.objects.filter(collection=collection).values("pid_status").annotate(
        total=Count("pid")
    ):
        data[item["pid_status"]] = item["total"]
    return data