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
        qs = qs.filter(journal__journal_acron=journal_acron)
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
