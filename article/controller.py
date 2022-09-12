from datetime import datetime

from .models import Article


def create_article_from_opac(opac_article, user_id):
    article = Article()
    article.aop_pid = opac_article.aop_pid
    article.pid_v3 = opac_article.aid
    article.pid_v2 = opac_article.pid

    article.article_type = opac_article.type

    article.elocation_id = opac_article.elocation
    article.fpage = opac_article.fpage
    article.lpage = opac_article.lpage

    # FIXME: it is necessary to populate fields issue, doi_with_lang, etc...
    # article.issue = Issue.objects.get(opac_article.issue.pid)

    article.created = datetime.utcnow()
    article.creator_id = user_id

    article.save()

    return article
