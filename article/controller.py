import logging
from datetime import datetime

from django.utils.translation import gettext_lazy as _
from packtools.sps.models.article_ids import ArticleIds

from pid_requester.controller import PidRequester
from . import exceptions
from .models import Article, choices
from collection.models import Collection


def request_pid_v3_and_create_article(xml_with_pre, filename, user, collection=None):
    """
    Solicita PID versão 3, registra o artigo e o arquivo XML com o pid v3
    provido pelo PID Provider

    collection: identificar coleção se requisição vier da migração
    """
    logging.info(f"Request PID V3 para {filename}")
    pid_requester = PidRequester()
    response = pid_requester.request_pid_for_xml_with_pre(xml_with_pre, filename, user)

    # IGNORA ERRO DE SOLICITACAO PID PROVIDER DO CORE
    # TODO REMOVER O COMENTÁRIO FUTURAMENTE
    # if response.get("error_type"):
    #     return response

    try:
        issnl = xml_with_pre.journal_issnl
    except AttributeError:
        issnl = None
    article = Article.get_or_create(
        pid_v3=response["v3"],
        pid_v2=response["v2"],
        aop_pid=response.get("aop_pid"),
        creator=user,
        issn_electronic=xml_with_pre.journal_issn_electronic,
        issn_print=xml_with_pre.journal_issn_print,
        issnl=issnl,
        volume=xml_with_pre.volume,
        number=xml_with_pre.number,
        suppl=xml_with_pre.suppl,
        publication_year=xml_with_pre.pub_year,
        collection=collection,
    )
    return {"article": article}


def create_article_from_etree(xml_tree, user_id, status=choices.AS_PUBLISHED):
    article = Article()

    _ids = ArticleIds(xml_tree)

    article.aop_pid = _ids.aop_pid
    article.pid_v3 = _ids.v3
    article.pid_v2 = _ids.v2

    article.status = status

    article.created = datetime.utcnow()
    article.creator_id = user_id

    article.save()

    return article


def update_article(article_id, **kwargs):
    try:
        article = Article.objects.get(pk=article_id)
        for k, v in kwargs.items():
            setattr(article, k, v)
        article.save()
    except Article.DoesNotExist:
        raise
    except Exception as e:
        raise exceptions.UpdateDocumentError(
            _("Unable to update article {} {} {}").format(str(kwargs), type(e), e)
        )
    return article
