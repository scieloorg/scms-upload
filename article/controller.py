from datetime import datetime

from django.utils.translation import gettext_lazy as _
from packtools.sps.models.article_ids import ArticleIds

from . import exceptions
from .models import Article, choices
from pid_requester.controller import PidRequester


def request_pid(xml_with_pre, filename, user):
    """
    Solicita PID versão 3, registra o artigo e o arquivo XML com o pid v3
    provido pelo PID Provider
    """
    pid_requester = PidRequester()
    response = pid_requester.request_pid_for_xml_with_pre(xml_with_pre, filename, user)
    if response.get("error_type"):
        return response
    article = Article.get_or_create(
        pid_v3=response["v3"],
        pid_v2=response["v2"],
        aop_pid=response.get("aop_pid"),
        creator=user,
    )
    article.add_xml_sps(filename, xml_with_pre.tostring())
    return article


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


def get_or_create_official_article(official_issue, **kwargs):
    try:
        official_article, status = Article.objects.get_or_create(**kwargs)
    except Exception as e:
        raise exceptions.GetOrCreateDocumentError(
            _("Unable to get or create official article {} {} {}").format(
                str(kwargs), type(e), e
            )
        )
    return official_article
