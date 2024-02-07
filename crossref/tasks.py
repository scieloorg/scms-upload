import logging

from article.models import Article
from config import celery_app
from core.utils.get_user import _get_user
from crossref.models import XMLCrossref, CrossrefConfiguration
from crossref.utils.utils import generate_crossref_xml_from_article


@celery_app.task(bind=True)
def generate_and_submit_crossref_xml_for_all_articles(
    self,
    prefix,
    user_id=None,
    username=None,
):
    user = _get_user(user_id=user_id, username=username)
    articles = Article.objects.filter(sps_pkg__isnull=False)
    
    try:
        data = CrossrefConfiguration.get_data(prefix=prefix)
    except CrossrefConfiguration.DoesNotExist:
        return None

    for article in articles:
        create_or_update_crossref_record.apply_async(
            kwargs=dict(
                xml_crossref=generate_crossref_xml_from_article(
                    article=article, data=data
                ),
                article_id=article.id,
                data=data,
                user=user,
            )
        )


@celery_app.task(bind=True)
def create_or_update_crossref_record(
    xml_crossref,
    article_id,
    data,
    user,
):  
    try:
        article = Article.objects.get(pk=article_id)
    except Article.DoesNotExist:
        logging.info(f"Not found {article_id}")
        return None

    XMLCrossref.create_or_update(
        file=xml_crossref,
        filename="crossref",
        article=article,
        user=user,
    )