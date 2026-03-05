"""
Celery tasks for Crossref DOI deposit operations.
"""

import logging
import sys

from django.contrib.auth import get_user_model

from config import celery_app
from tracker.models import UnexpectedEvent

logger = logging.getLogger(__name__)

User = get_user_model()


def _get_user(user_id, username):
    try:
        if user_id:
            return User.objects.get(pk=user_id)
        if username:
            return User.objects.get(username=username)
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "doi.tasks._get_user",
                "user_id": user_id,
                "username": username,
            },
        )


@celery_app.task(bind=True, name="Deposit DOI to Crossref")
def task_deposit_doi_to_crossref(self, user_id, username, article_id, force=False):
    """
    Realiza o depósito do DOI de um único artigo no Crossref.

    Parameters
    ----------
    user_id : int
        ID do usuário que disparou a tarefa.
    username : str
        Nome do usuário que disparou a tarefa.
    article_id : int
        ID do artigo cujo DOI será depositado.
    force : bool
        Se True, realiza o depósito mesmo que já tenha sido feito com sucesso anteriormente.
    """
    from article.models import Article
    from doi.controller import (
        deposit_article_doi,
        CrossrefDepositError,
        CrossrefConfigurationNotFoundError,
    )

    try:
        user = _get_user(user_id, username)
        article = Article.objects.get(pk=article_id)

        logger.info(
            f"Starting Crossref DOI deposit for article {article} "
            f"(user: {username or user_id})"
        )

        deposit = deposit_article_doi(user=user, article=article, force=force)

        logger.info(
            f"Crossref DOI deposit completed for article {article}. "
            f"Status: {deposit.status}"
        )
        return {
            "article_id": article_id,
            "deposit_id": deposit.id,
            "status": deposit.status,
        }

    except CrossrefConfigurationNotFoundError as e:
        logger.error(
            f"Crossref configuration not found for article {article_id}: {e}"
        )
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "task_deposit_doi_to_crossref",
                "article_id": article_id,
                "user_id": user_id,
                "username": username,
            },
        )
        raise

    except CrossrefDepositError as e:
        logger.error(
            f"Crossref deposit error for article {article_id}: {e}"
        )
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "task_deposit_doi_to_crossref",
                "article_id": article_id,
                "user_id": user_id,
                "username": username,
            },
        )
        raise

    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "task_deposit_doi_to_crossref",
                "article_id": article_id,
                "user_id": user_id,
                "username": username,
            },
        )
        raise


@celery_app.task(bind=True, name="Batch Deposit DOIs to Crossref")
def task_batch_deposit_doi_to_crossref(
    self,
    user_id,
    username,
    journal_id=None,
    article_ids=None,
    force=False,
):
    """
    Realiza o depósito em lote de DOIs de artigos no Crossref.

    Parameters
    ----------
    user_id : int
        ID do usuário que disparou a tarefa.
    username : str
        Nome do usuário que disparou a tarefa.
    journal_id : int, optional
        ID do periódico. Se informado, deposita todos os artigos do periódico
        que ainda não foram depositados com sucesso (a menos que force=True).
    article_ids : list, optional
        Lista de IDs de artigos a depositar. Se informado, deposita apenas
        os artigos da lista.
    force : bool
        Se True, realiza o depósito mesmo que já tenha sido feito com sucesso.
    """
    from article.models import Article
    from doi.controller import (
        deposit_article_doi,
        CrossrefDepositError,
        CrossrefConfigurationNotFoundError,
    )
    from doi.models import CrossrefDepositStatus

    results = {
        "total": 0,
        "success": 0,
        "error": 0,
        "skipped": 0,
        "errors": [],
    }

    try:
        user = _get_user(user_id, username)

        if article_ids:
            articles = Article.objects.filter(pk__in=article_ids)
        elif journal_id:
            articles = Article.objects.filter(journal_id=journal_id)
        else:
            logger.warning(
                "task_batch_deposit_doi_to_crossref: neither journal_id nor "
                "article_ids were provided. Nothing to process."
            )
            return results

        results["total"] = articles.count()
        logger.info(
            f"Starting batch Crossref DOI deposit for {results['total']} articles "
            f"(journal_id={journal_id}, user={username or user_id})"
        )

        for article in articles.iterator():
            try:
                deposit = deposit_article_doi(
                    user=user, article=article, force=force
                )
                if deposit.status == CrossrefDepositStatus.SUCCESS:
                    results["success"] += 1
                elif deposit.status == CrossrefDepositStatus.PENDING:
                    results["skipped"] += 1
                else:
                    results["error"] += 1
                    results["errors"].append(
                        {
                            "article_id": article.id,
                            "status": deposit.status,
                            "response": deposit.response_body,
                        }
                    )
            except CrossrefConfigurationNotFoundError as e:
                results["error"] += 1
                results["errors"].append(
                    {"article_id": article.id, "error": str(e)}
                )
                logger.error(
                    f"Crossref config not found for article {article}: {e}"
                )
                break
            except CrossrefDepositError as e:
                results["error"] += 1
                results["errors"].append(
                    {"article_id": article.id, "error": str(e)}
                )
                logger.error(
                    f"Crossref deposit error for article {article}: {e}"
                )
            except Exception as e:
                results["error"] += 1
                results["errors"].append(
                    {"article_id": article.id, "error": str(e)}
                )
                logger.error(
                    f"Unexpected error during Crossref deposit for article {article}: {e}"
                )

        logger.info(
            f"Batch Crossref DOI deposit finished. Results: {results}"
        )
        return results

    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "task_batch_deposit_doi_to_crossref",
                "journal_id": journal_id,
                "article_ids": article_ids,
                "user_id": user_id,
                "username": username,
            },
        )
        raise
