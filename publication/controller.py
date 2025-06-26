import logging
import sys

from django.contrib.auth import get_user_model

from collection.models import WebSiteConfiguration
from collection.choices import PUBLIC, QA
from core.utils.requester import fetch_data
from proc.models import ArticleProc, IssueProc, JournalProc
from proc.controller import ensure_journal_proc_exists, ensure_issue_proc_exists
from publication.api.document import publish_article
from publication.api.issue import publish_issue
from publication.api.journal import publish_journal
from publication.api.publication import PublicationAPI
from tracker.models import UnexpectedEvent


User = get_user_model()


class PublicationError(Exception):
    """Erro durante o processo de publicação"""
    pass


def check_article_is_published(article, website):
    """
    Verifica se um artigo já está publicado em um website

    Args:
        article: O artigo a ser verificado
        journal_proc: O processador do journal
        website: A configuração do website
        user: O usuário que executa a operação
        manager: O gerenciador da operação

    Returns:
        bool: True se o artigo já está publicado, False caso contrário
    """
    try:
        article_url = f"{website.url}/j/{article.journal.journal_acron}/a/{article.pid_v3}/?format=xml"
        return bool(fetch_data(article_url))
    except Exception as e:
        logging.exception(e)
        return False


def ensure_published_journal(journal_proc, website, user, api_data, force_update=None):
    """
    Publica um journal em um website

    Args:
        journal_proc: O processador do journal
        website: A configuração do website
        user: O usuário que executa a operação
        api_data: Os dados da API para publicação

    Returns:
        dict: Resultado da publicação com detalhes

    Raises:
        PublicationError: Se ocorrer erro na publicação
    """

    try:
        if not force_update:
            journal_url = f"{website.url}/scielo.php?pid={journal_proc.pid}&script=sci_serial"
            return bool(fetch_data(journal_url))
    except Exception as e:
        pass

    response = journal_proc.publish(
        user,
        publish_journal,
        website_kind=website.purpose,
        api_data=api_data,
        force_update=True,
        content_type="journal"
    )
    return response


def ensure_published_issue(issue_proc, website, user, api_data, force_update=None):
    """
    Publica um issue em um website

    Args:
        manager: O gerenciador da operação
        issue_proc: O processador do issue
        website: A configuração do website
        user: O usuário que executa a operação
        api_data: Os dados da API para publicação

    Returns:
        dict: Resultado da publicação com detalhes

    Raises:
        PublicationError: Se ocorrer erro na publicação
    """
    try:
        if not force_update:
            issue_url = f"{website.url}/scielo.php?pid={issue_proc.pid}&script=sci_issuetoc"
            return bool(fetch_data(issue_url))
    except Exception as e:
        pass

    response = issue_proc.publish(
        user,
        publish_issue,
        website_kind=website.purpose,
        api_data=api_data,
        force_update=True,
        content_type="issue"
    )
    return response


def publish_article_collection_websites(user, manager, website_kinds, force_journal_publication, force_issue_publication):
    for issue_proc in IssueProc.objects.filter(
        issue=manager.article.issue,
    ):
        if not manager.article.journal.journal_acron:
            manager.article.journal.journal_acron = issue_proc.journal_proc.acron
            manager.article.journal.save()
        yield from publish_article_on_websites(
            user, manager, issue_proc, website_kinds,
            force_journal_publication, force_issue_publication,
        )


def publish_article_on_websites(user, manager, issue_proc, website_kinds, force_journal_publication, force_issue_publication):
    collection = issue_proc.collection
    published_article = None
    qa_published = None
    article = manager.article
    for website_kind in website_kinds:
        try:
            website = WebSiteConfiguration.get(
                collection=collection,
                purpose=website_kind,
            )
            api = PublicationAPI(
                post_data_url=website.api_url_article,
                get_token_url=website.api_get_token_url,
                username=website.api_username,
                password=website.api_password,
                timeout=15,
            )
            api.get_token()
            api_data = api.data
        except WebSiteConfiguration.DoesNotExist as exc:
            continue

        published_article = publish_article_on_website(
            user, manager, issue_proc, website, api_data, qa_published,
            force_journal_publication, force_issue_publication,
        )
        if website_kind == QA:
            qa_published = published_article
        data = {"collection": collection.acron, "website": website_kind, "published": published_article}
        logging.info(data)            
        yield data


def publish_article_on_website(user, manager, issue_proc, website, api_data, qa_published=None, force_journal_publication=None, force_issue_publication=None):
    """
    Publica um artigo verificando e garantindo as dependências (journal e issue)
    
    Args:
        manager: O gerenciador da operação
        journal_proc: O processador do journal
        issue_proc: O processador do issue
        website: A configuração do website
        user: O usuário que executa a operação
        api_data: Os dados da API para publicação
        
    Returns:
        dict: Resultado da publicação com detalhes e histórico
        
    Raises:
        PublicationError: Se ocorrer erro na publicação
    """
    article = manager.article
    collection = issue_proc.collection
    logging.info(f"publish_article_on_website: qa_published {qa_published}")
    logging.info(f"publish_article_on_website: website.purpose {website.purpose}")
    if website.purpose == PUBLIC and not qa_published:
        try:
            qa_website = WebSiteConfiguration.get(collection=collection, purpose=QA)
            qa_published = check_article_is_published(article, qa_website)
        except WebSiteConfiguration.DoesNotExist as exc:
            # site QA inexistente, a ausencia do artigo em QA não impede publicação em PUBLIC
            logging.exception(exc)
            qa_published = True
        if not qa_published:
            return False

    article = manager.article
    journal_proc = issue_proc.journal_proc
    api_data["post_data_url"] = website.api_url_journal
    response = ensure_published_journal(journal_proc, website, user, api_data, force_journal_publication)
    if not response or not response.get("completed"):
        raise PublicationError(
            f"Unable to publish article {article}: {journal_proc} is not published on {website.purpose} {response}"
        )


    api_data["post_data_url"] = website.api_url_issue
    response = ensure_published_issue(issue_proc, website, user, api_data, force_issue_publication)
    if not response or not response.get("completed"):
        raise PublicationError(
            f"Unable to publish article {article}: {issue_proc} is not published on {website.purpose} {response}"
        )

    api_data["post_data_url"] = website.api_url_article
    response = manager.publish(
        user,
        publish_article,
        website_kind=website.purpose,
        api_data=api_data,
        force_update=True,
        content_type="article",
        bundle_id=issue_proc.bundle_id,
    )
    return response


def get_manager_info(article_proc_id=None, upload_package_id=None):
    """
    Obtém o gerenciador e informações do artigo
    
    Args:
        article_proc_id: ID do processo de artigo
        upload_package_id: ID do pacote de upload
        
    Returns:
        tuple: (manager, journal, issue, article)
        
    Raises:
        ValueError: Se nenhum ID for fornecido
    """
    if upload_package_id:
        from upload.models import Package
        manager = Package.objects.get(pk=upload_package_id)
        issue = manager.issue
        journal = manager.journal
        article = manager.article
    elif article_proc_id:
        manager = ArticleProc.objects.get(pk=article_proc_id)
        issue = manager.issue_proc.issue
        journal = manager.journal_proc.journal
        article = manager.article
    else:
        raise ValueError("Either article_proc_id or upload_package_id must be provided")
    
    return manager