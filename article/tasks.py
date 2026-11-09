import logging
import sys

from config import celery_app
from tracker.models import UnexpectedEvent

from article.models import Article

DATA_AVAILABILITY_BATCH_SIZE = 500


def _filter_articles(
    collection_acron=None,
    journal_acron=None,
    publication_year=None,
    force_update=False,
):
    qs = Article.objects.filter(sps_pkg__isnull=False)
    if collection_acron:
        qs = qs.filter(
            pk__in=Article.objects.filter(
                article_collections__collection__acron=collection_acron
            ).values("pk")
        )
    if journal_acron:
        qs = Article.filter_by_journal_acron(qs, journal_acron)
    if publication_year:
        qs = qs.filter(issue__publication_year=publication_year)
    if not force_update:
        qs = qs.filter(data_availability_status__isnull=True)
    return qs


@celery_app.task(bind=True)
def task_update_data_availability_status(
    self,
    collection_acron=None,
    journal_acron=None,
    publication_year=None,
    force_update=False,
    batch_size=None,
):
    """
    Extrai data_availability_status do XML de artigos já carregados.

    Seleciona os artigos (por padrão, apenas os ainda não processados)
    e dispara uma subtarefa por lote de artigos.
    """
    try:
        batch_size = int(batch_size or DATA_AVAILABILITY_BATCH_SIZE)
        article_ids = list(
            _filter_articles(
                collection_acron=collection_acron,
                journal_acron=journal_acron,
                publication_year=publication_year,
                force_update=force_update,
            )
            .order_by("pk")
            .values_list("pk", flat=True)
        )
        for i in range(0, len(article_ids), batch_size):
            task_update_data_availability_status_for_articles.apply_async(
                kwargs=dict(
                    article_ids=article_ids[i : i + batch_size],
                    force_update=force_update,
                )
            )
        logging.info(
            f"task_update_data_availability_status: {len(article_ids)} articles"
        )
        return len(article_ids)
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "article.tasks.task_update_data_availability_status",
                "collection_acron": collection_acron,
                "journal_acron": journal_acron,
                "publication_year": publication_year,
                "force_update": force_update,
            },
        )


@celery_app.task(bind=True)
def task_update_data_availability_status_for_articles(
    self,
    article_ids,
    force_update=False,
):
    try:
        return Article.update_data_availability_status(
            queryset=Article.objects.filter(pk__in=article_ids),
            force_update=force_update,
        )
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "article.tasks.task_update_data_availability_status_for_articles",
                "article_ids": article_ids,
                "force_update": force_update,
            },
        )


# SPSPkg antes de Article (ver package.collection_pid_v2_completion)
COMPLETE_COLLECTION_PID_V2_MODELS = ("SPSPkg", "Article")


def _get_user(request, username=None, user_id=None):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    try:
        return User.objects.get(pk=request.user.id)
    except AttributeError:
        if user_id:
            return User.objects.get(pk=user_id)
        if username:
            return User.objects.get(username=username)


@celery_app.task(bind=True)
def task_complete_collection_pid_v2(
    self,
    username=None,
    user_id=None,
    model_name="SPSPkg",
    last_id=0,
    batch_size=100,
    countdown=30,
    max_batches=None,
    auto_continue=True,
):
    """
    Vincula aos documentos na coleção (collection_pid_v2), aos poucos, os
    SPSPkg e Article anteriores à separação por coleção.

    Cada execução processa um único lote (batch_size registros sem vínculo,
    com id > last_id, em ordem de id) e, se auto_continue, agenda a
    próxima execução após countdown segundos, a partir do último id
    processado. Assim a carga fica distribuída no tempo e a tarefa pode ser
    interrompida e retomada (informando last_id).

    Os SPSPkg são processados antes dos Article, pois o Article é vinculado
    ao documento na coleção do seu pacote.

    Registros cuja coleção é ambígua continuam sem vínculo e são vinculados
    quando reprocessados; o cursor avança sobre eles.

    max_batches: limite de lotes desta sequência de execuções (None: até
    terminar)

    Usa a mesma função da migração article 0014_complete_collection_pid_v2
    (package.collection_pid_v2_completion), que informa model_name e
    last_id para continuar o que ficou pendente nela.

    Ao terminar, informa em "unlinked" a quantidade de registros que
    continuam sem vínculo (ambíguos, para tratamento manual)
    """
    from package.models import SPSPkg

    models = {"SPSPkg": SPSPkg, "Article": Article}
    detail = {
        "task": "article.tasks.task_complete_collection_pid_v2",
        "model_name": model_name,
        "last_id": last_id,
        "batch_size": batch_size,
    }
    try:
        user = _get_user(self.request, username=username, user_id=user_id)
        model = models[model_name]
        stats, next_last_id, done = model.complete_collection_pid_v2_batch(
            user, last_id=last_id, batch_size=int(batch_size)
        )
        detail.update({"stats": stats, "next_last_id": next_last_id, "done": done})
        logging.info(f"task_complete_collection_pid_v2: {detail}")

        if not auto_continue:
            return detail

        remaining_batches = None
        if max_batches is not None:
            remaining_batches = int(max_batches) - 1
            if remaining_batches <= 0:
                return detail

        if done:
            index = COMPLETE_COLLECTION_PID_V2_MODELS.index(model_name)
            if index + 1 >= len(COMPLETE_COLLECTION_PID_V2_MODELS):
                from django.apps import apps as django_apps
                from package import collection_pid_v2_completion

                detail["unlinked"] = collection_pid_v2_completion.count_unlinked(
                    django_apps
                )
                logging.info(f"task_complete_collection_pid_v2: {detail}")
                return detail
            # próximo modelo, desde o início
            model_name = COMPLETE_COLLECTION_PID_V2_MODELS[index + 1]
            next_last_id = 0

        task_complete_collection_pid_v2.apply_async(
            kwargs=dict(
                user_id=user.id,
                model_name=model_name,
                last_id=next_last_id,
                batch_size=batch_size,
                countdown=countdown,
                max_batches=remaining_batches,
                auto_continue=auto_continue,
            ),
            countdown=countdown,
        )
        return detail
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail=detail,
        )
