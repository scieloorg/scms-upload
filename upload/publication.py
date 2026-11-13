import logging
from urllib.parse import urlencode

from collection.choices import PUBLIC, QA
from collection.models import WebSiteConfiguration
from core.utils.requester import fetch_data
from proc.models import IssueProc
from publication.api.document import publish_article
from publication.api.issue import publish_issue
from publication.api.journal import publish_journal
from publication.api.publication import PublicationAPI
from upload.publication_results import destination_result, publication_error_metadata

DEPENDENCY_PUBLICATION = {
    "journal": ("sci_serial", publish_journal),
    "issue": ("sci_issuetoc", publish_issue),
}


def check_article_is_published(article, website):
    """Consulta o XML do artigo para verificar sua presença no site."""
    try:
        languages = sorted(article.article_langs)
        if not languages:
            logging.error(
                "Cannot check QA publication for article %s: no document language available",
                article.pid_v3,
            )
            return False
        query = urlencode({"format": "xml", "lang": languages[0]})
        article_url = (
            f"{website.url.rstrip('/')}/j/{article.journal.journal_acron}"
            f"/a/{article.pid_v3}/?{query}"
        )
        return bool(fetch_data(article_url))
    except Exception as e:
        logging.exception(e)
        return False


def ensure_published_dependency(
    manager, website, user, api_data, content_type, force_update=None
):
    """Consulta ou publica o periódico ou fascículo exigido pelo artigo."""
    script, publish = DEPENDENCY_PUBLICATION[content_type]
    if not force_update:
        try:
            url = f"{website.url}/scielo.php?pid={manager.pid}&script={script}"
            if fetch_data(url):
                return {content_type: str(manager), "published": True}
        except Exception:
            pass

    try:
        response = (
            manager.publish(
                user,
                publish,
                website_kind=website.purpose,
                api_data=api_data,
                force_update=True,
                content_type=content_type,
            )
            or {}
        )
    except Exception as error:
        return {
            "published": False,
            "error": str(error),
            **publication_error_metadata(error),
        }

    response["published"] = bool(response.get("completed"))
    if not response["published"]:
        response.setdefault(
            "error",
            response.get("error_message")
            or f"Unable to publish {content_type} {manager}",
        )

    return response


def publish_article_on_collection_websites(
    user, manager, collection, website_kinds, force_journal_publication, force_issue_publication
):
    responses = []
    journal = manager.journal
    issue_proc = IssueProc.objects.filter(issue=manager.issue, collection=collection).first()

    if journal.missing_fields:
        event = issue_proc.journal_proc.start(user, "Missing journal data")
        event.finish(
            user, detail={"journal_missing_fields": str(journal.missing_fields)}
        )

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
        qa_published = response.get("completed")
        resp = destination_result(QA, response, collection.acron)
        responses.append(resp)
        if not qa_published:
            return responses

    if PUBLIC in website_kinds:
        if not qa_published:
            try:
                qa_website = WebSiteConfiguration.get(collection=collection, purpose=QA)
                qa_published = check_article_is_published(manager.article, qa_website)
                if not qa_published:
                    resp = destination_result(
                        QA, {"completed": False}, collection.acron
                    )
                    responses.append(resp)
                    return responses
            except WebSiteConfiguration.DoesNotExist:
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
        resp = destination_result(PUBLIC, response, collection.acron)
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
    """Publica o artigo após confirmar as dependências no destino."""
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
        if not api.token:
            api.get_token()
        api_data = api.data
    except WebSiteConfiguration.DoesNotExist as exc:
        return {
            "error": f"Website {collection} {website_kind} does not exists",
            "stage": "connection",
            **publication_error_metadata(exc),
        }
    except Exception as exc:
        metadata = publication_error_metadata(exc)
        if metadata["error_category"] == "unknown":
            metadata["error_category"] = "authentication"
        return {
            "error": f"Website {collection} {website_kind}: {exc}",
            "stage": "authentication",
            **metadata,
        }

    stage = "journal"
    responses = []
    try:
        dependencies = (
            (
                "journal",
                issue_proc.journal_proc,
                website.api_url_journal,
                force_journal_publication,
            ),
            ("issue", issue_proc, website.api_url_issue, force_issue_publication),
        )
        for stage, dependency, url, force_update in dependencies:
            api_data["post_data_url"] = url
            response = ensure_published_dependency(
                dependency, website, user, api_data, stage, force_update
            )
            responses.append(response)
            if not response["published"]:
                break
        else:
            stage = "article"
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
            return {**response, "stage": stage}
    except Exception as error:
        response = {"error": str(error), **publication_error_metadata(error)}

    event = manager.start(user, f"Publish article on {collection} {website_kind}")
    event.finish(user, completed=False, detail=responses)

    return {**response, "stage": stage}
