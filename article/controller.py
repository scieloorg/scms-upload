import logging
from datetime import datetime

from django.utils.translation import gettext_lazy as _
from packtools.sps.models.article_ids import ArticleIds

from . import exceptions
from .models import Article, choices


def create_article(sps_pkg, user):
    article = Article.create_or_update(user, sps_pkg)
    article.add_journal(user)
    article.add_issue(user)
    article.save()
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
