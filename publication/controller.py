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
        article_url = f"{website.url}/j/{article.journal.acron}/a/{article.pid_v3}"
        return bool(fetch_data(article_url))
    except Exception as e:
        return False


def ensure_published_journal(journal_proc, website, user, api_data):
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
        journal_url = f"{website.url}/scielo.php?pid={journal_proc.pid}&script=sci_serial"
        return bool(fetch_data(journal_url))
    except Exception as e:
        response = journal_proc.publish(
            user,
            publish_journal,
            website_kind=website.purpose,
            api_data=api_data,
            force_update=True,
            content_type="journal"
        )
        return response.get("completed")


def ensure_published_issue(issue_proc, website, user, api_data):
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
        issue_url = f"{website.url}/scielo.php?pid={issue_proc.pid}&script=sci_issuetoc"
        return bool(fetch_data(issue_url))
    except Exception as e:
        response = issue_proc.publish(
            user,
            publish_issue,
            website_kind=website.purpose,
            api_data=api_data,
            force_update=True,
            content_type="issue"
        )
        return response.get("completed")


def publish_article_collection_websites(user, article, website_kinds):
    for issue_proc in IssueProc.objects.filter(journal_proc__journal=article.journal):
        yield from publish_article_on_websites(
            user, issue_proc, website_kinds, article
        )


def publish_article_on_websites(user, issue_proc, website_kinds, article):
    journal_proc = issue_proc.journal_proc
    collection = journal_proc.collection
    published_article = None
    allowed_to_be_public = None
    result = []
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
        
        if website_kind == PUBLIC:
            if QA not in website_kinds:
                try:
                    qa_website = WebSiteConfiguration.get(collection=collection, purpose=QA)
                    allowed_to_be_public = check_article_is_published(qa_website, article)
                except WebSiteConfiguration.DoesNotExist:
                    allowed_to_be_public = True
                
            if not allowed_to_be_public:
                yield {"collection": collection.acron, "website": website_kind, "published": False}
                break

        published_article = publish_article_on_website(
            user, manager, issue_proc, website, api_data)
        if website_kind == QA:
            allowed_to_be_public = published_article
        yield {"collection": collection.acron, "website": website_kind, "published": published_article}


def publish_article_on_website(user, manager, issue_proc, website, api_data):
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
    journal_proc = issue_proc.journal_proc
    api_data["post_data_url"] = website.api_url_journal
    if not ensure_published_journal(issue_proc.journal_proc, website, user, api_data):
        raise PublicationError(
            f"Unable to publish article {article}: {journal_proc} is not published on {website.purpose}"
        )

    api_data["post_data_url"] = website.api_url_issue
    if not ensure_published_issue(issue_proc, website, user, api_data):
        raise PublicationError(
            f"Unable to publish article {article}: {issue_proc} is not published on {website.purpose}"
        )

    api_data["post_data_url"] = website.api_url_article
    response = manager.publish(
        user,
        publish_article,
        website_kind=website.purpose,
        api_data=api_data,
        force_update=True,
        content_type="article"
    )
    return response.get("completed")


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
    
    return manager, journal, issue, article