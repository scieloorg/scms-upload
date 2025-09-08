import logging
import sys
from datetime import datetime


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
        logging.info((str(article_proc), str(article_proc.issue_proc)))
        try:
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
