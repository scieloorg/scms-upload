from datetime import datetime

from packtools.sps.models.article_ids import ArticleIds

from .models import Article as dbArticle


def create_article_from_etree(xml_tree, user_id):
    article = dbArticle()

    _ids = ArticleIds(xml_tree)

    article.aop_pid = _ids.aop_pid
    article.pid_v3 = _ids.v3
    article.pid_v2 = _ids.v2

    article.created = datetime.utcnow()
    article.creator_id = user_id

    article.save()

    return article
