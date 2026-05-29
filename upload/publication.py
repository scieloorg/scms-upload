import logging
import sys

from django.contrib.auth import get_user_model

from collection.models import WebSiteConfiguration
from collection.choices import PUBLIC, QA
from core.utils.requester import fetch_data
from proc.models import ArticleProc, IssueProc, JournalProc
from proc.source_core_api import create_or_update_journal, create_or_update_issue
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
            journal_url = (
                f"{website.url}/scielo.php?pid={journal_proc.pid}&script=sci_serial"
            )
            return {"journal": str(journal_proc), "published": bool(fetch_data(journal_url))}
        response = journal_proc.publish(
            user,
            publish_journal,
            website_kind=website.purpose,
            api_data=api_data,
            force_update=True,
            content_type="journal",
        )
        if not response:
            raise Exception(f"Unable to publish journal {journal_proc}")
        response["published"] = response.get("completed")
        return response
    except Exception as e:
        return {"error": f"journal {journal_proc} is not published. {e}"}


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
            issue_url = (
                f"{website.url}/scielo.php?pid={issue_proc.pid}&script=sci_issuetoc"
            )
            return {"issue": str(issue_proc), "published": bool(fetch_data(issue_url))}
        response = issue_proc.publish(
            user,
            publish_issue,
            website_kind=website.purpose,
            api_data=api_data,
            force_update=True,
            content_type="issue",
        )
        if not response:
            raise Exception(f"Unable to publish issue {issue_proc}")
        response["published"] = response.get("completed")
        return response
    except Exception as e:
        return {"error": f"issue {issue_proc} is not published. {e}"}



def publish_article_on_collection_websites(
    user, manager, website_kinds, force_journal_publication, force_issue_publication
):
    responses = []
    journal = manager.journal
    for issue_proc in IssueProc.objects.filter(
        issue=manager.article.issue,
    ):
        if journal.missing_fields:
            event = issue_proc.journal_proc.start(user, "Missing journal data")
            event.finish(
                user, detail={"journal_missing_fields": journal.missing_fields}
            )

        collection = issue_proc.collection
        qa_published = None

        if QA in website_kinds:
            response = publish_article_on_website(
                user,
                manager,
                issue_proc,
                QA,
                force_journal_publication,
                force_issue_publication,
            )
            qa_published = response and response.get("completed")
            resp = {
                "collection": collection.acron,
                "website": QA,
                "published": qa_published,
            }
            resp.update(response)
            responses.append(resp)
            break
        
        if PUBLIC in website_kinds:
            if not qa_published:
                try:
                    qa_website = WebSiteConfiguration.get(collection=collection, purpose=QA)
                    qa_published = check_article_is_published(manager.article, qa_website)
                    if not qa_published:
                        resp = {
                            "collection": collection.acron,
                            "website": QA,
                            "published": qa_published,
                        }
                        responses.append(resp)
                        break
                except WebSiteConfiguration.DoesNotExist as exc:
                    # não existe um site para previsualizar, então permite publicar no site público
                    pass

            # artigo está publicado em qa ou não existe site qa
            response = publish_article_on_website(
                user,
                manager,
                issue_proc,
                PUBLIC,
                force_journal_publication,
                force_issue_publication,
            )
            resp = {
                "collection": collection.acron,
                "website": PUBLIC,
                "published": response and response.get("completed"),
            }
            responses.append(resp)
    return responses


def publish_article_on_website(
    user,
    manager,
    issue_proc,
    website_kind,
    force_journal_publication=None,
    force_issue_publication=None,
):
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
    collection = issue_proc.collection

    logging.info(f"Publishing article on {collection} {website_kind}")
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
            enabled=website.enabled,
        )
        api.get_token()
        api_data = api.data
    except WebSiteConfiguration.DoesNotExist as exc:
        return {"error": f"Website {collection} {website_kind} does not exists"}
    except Exception as exc:
        return {"error": f"Website {collection} {website_kind}: {exc}"}

    try:
        responses = []
        journal_proc = issue_proc.journal_proc

        api_data["post_data_url"] = website.api_url_journal
        response = ensure_published_journal(
            journal_proc, website, user, api_data, force_journal_publication
        )
        responses.append(response)
        if response.get("error"):
            raise ValueError(response.get("error"))
        if not response.get("published"):
            raise ValueError(f"Unable to publish article because journal {journal_proc} is not published")

        api_data["post_data_url"] = website.api_url_issue
        response = ensure_published_issue(
            issue_proc, website, user, api_data, force_issue_publication
        )
        responses.append(response)
        if response.get("error"):
            raise ValueError(response.get("error"))
        if not response.get("published"):
            raise ValueError(f"Unable to publish article because issue {issue_proc} is not published")

        api_data["post_data_url"] = website.api_url_article
        return manager.publish(
            user,
            publish_article,
            website_kind=website.purpose,
            api_data=api_data,
            force_update=True,
            content_type="article",
            bundle_id=issue_proc.bundle_id,
        )
    except Exception as e:
        event = manager.start(user, f"Publish article on {collection} {website_kind}")
        event.finish(user, completed=False, detail=responses)
        return {"error": str(e)}
