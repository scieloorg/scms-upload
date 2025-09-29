from datetime import datetime


def log_event(execution_log, level, event_type, message, **extra_data):
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
        "timestamp": datetime.now().isoformat(),
        "level": level,
        "type": event_type,
        "message": message,
    }
    if extra_data:
        event.update(extra_data)
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
