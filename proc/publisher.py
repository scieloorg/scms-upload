"""
Módulo responsável pela publicação de conteúdo nos websites.
"""

import logging

from proc.models import IssueProc, JournalProc, ArticleProc
from publication.api.issue import publish_issue
from publication.api.journal import publish_journal
from publication.api.publication import get_api_data


def publish_journals(
    user,
    website_kind,
    collection,
    journal_filter,
    issue_filter,
    force_update,
    run_publish_issues,
    run_publish_articles,
    task_publish_article,
):
    """
    Publica journals no website especificado.

    Args:
        user: Usuário executando a operação
        website_kind: Tipo de website (ex: 'public', 'preview')
        collection: Collection a ser publicada
        journal_filter: Filtros para seleção de journals
        issue_filter: Filtros para seleção de issues
        force_update: Forçar atualização mesmo se não houver mudanças
        run_publish_issues: Se deve executar publicação de issues também
        run_publish_articles: Se deve executar publicação de artigos também
        task_publish_article: Task para publicação assíncrona de artigos
    """
    params = dict(
        website_kind=website_kind,
        collection=collection,
        journal_filter=journal_filter,
        issue_filter=issue_filter,
        force_update=force_update,
        run_publish_issues=run_publish_issues,
        run_publish_articles=run_publish_articles,
        task_publish_article=(
            "call task_publish_article" if task_publish_article else None
        ),
    )
    logging.info(f"publish_journals {params}")

    api_data = get_api_data(collection, "journal", website_kind)

    if api_data.get("error"):
        logging.error(api_data)
    else:
        items = JournalProc.items_to_publish(
            website_kind=website_kind,
            content_type="journal",
            collection=collection,
            force_update=force_update,
            params=journal_filter,
        )
        logging.info(f"publish_journals: {items.count()}")

        for journal_proc in items:
            response = journal_proc.publish(
                user,
                publish_journal,
                website_kind=website_kind,
                api_data=api_data,
                force_update=force_update,
            )
            if run_publish_issues and response.get("completed"):
                publish_issues(
                    user,
                    website_kind,
                    journal_proc,
                    issue_filter,
                    force_update,
                    run_publish_articles,
                    task_publish_article,
                )


def publish_issues(
    user,
    website_kind,
    journal_proc,
    issue_filter,
    force_update,
    run_publish_articles,
    task_publish_article,
):
    """
    Publica issues de um journal específico no website.

    Args:
        user: Usuário executando a operação
        website_kind: Tipo de website
        journal_proc: JournalProc pai dos issues
        issue_filter: Filtros para seleção de issues
        force_update: Forçar atualização
        run_publish_articles: Se deve executar publicação de artigos
        task_publish_article: Task para publicação assíncrona de artigos
    """
    collection = journal_proc.collection
    params = dict(
        website_kind=website_kind,
        collection=collection,
        journal_proc=journal_proc,
        issue_filter=issue_filter,
        force_update=force_update,
        run_publish_articles=run_publish_articles,
        task_publish_article=(
            "call task_publish_article" if task_publish_article else None
        ),
    )
    logging.info(f"publish_issues {params}")

    api_data = get_api_data(collection, "issue", website_kind)

    if api_data.get("error"):
        logging.error(api_data)
    else:
        issue_filter["journal_proc"] = journal_proc
        items = IssueProc.items_to_publish(
            website_kind=website_kind,
            content_type="issue",
            collection=collection,
            force_update=force_update,
            params=issue_filter,
        )
        logging.info(f"publish_issues: {items.count()}")

        for issue_proc in items:
            response = issue_proc.publish(
                user,
                publish_issue,
                website_kind=website_kind,
                api_data=api_data,
                force_update=force_update,
            )
            if run_publish_articles and response.get("completed"):
                publish_articles(
                    user,
                    website_kind,
                    issue_proc,
                    force_update,
                    task_publish_article,
                )


def publish_articles(
    user, website_kind, issue_proc, force_update, task_publish_article
):
    """
    Publica artigos de um issue específico no website.

    Args:
        user: Usuário executando a operação
        website_kind: Tipo de website
        issue_proc: IssueProc pai dos artigos
        force_update: Forçar atualização
        task_publish_article: Task para publicação assíncrona de artigos
    """
    collection = issue_proc.collection
    params = dict(
        website_kind=website_kind,
        collection=collection,
        issue_proc=issue_proc,
        force_update=force_update,
        task_publish_article=(
            "call task_publish_article" if task_publish_article else None
        ),
    )
    logging.info(f"publish_articles {params}")

    api_data = get_api_data(collection, "article", website_kind)
    if api_data.get("error"):
        logging.error(api_data)
    else:
        items = ArticleProc.items_to_publish(
            website_kind=website_kind,
            content_type="article",
            collection=collection,
            force_update=force_update,
            params={"issue_proc": issue_proc},
        )
        logging.info(f"publish_articles: {items.count()}")

        for article_proc in items:
            task_publish_article.apply_async(
                kwargs=dict(
                    user_id=user.id,
                    username=user.username,
                    website_kind=website_kind,
                    article_proc_id=article_proc.id,
                    api_data=api_data,
                    force_update=force_update,
                )
            )
