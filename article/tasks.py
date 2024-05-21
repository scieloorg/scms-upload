import sys
from django.db.models import Q

from config import celery_app
from core.utils.get_user import _get_user
from core.utils.requester import fetch_data
from article.models import CheckArticleAvailability, Article
from collection.models import Collection
from tracker.models import UnexpectedEvent

@celery_app.task(bind=True)
def initiate_article_availability_check(
    self,
    username,
    user_id,
    issn_print=None,
    issn_electronic=None,
    publication_year=None,
    updated=None,
    article_pid_v3=None,
    collection_acron=None,
):
    if collection_acron:
        collection = Collection.objects.filter(acron=collection_acron)
    else:
        collection = Collection.objects.all()

    query = Q(journal__journalproc__collection__in=collection)
    if not updated:
        if article_pid_v3:
            query |= Q(pid_v3=article_pid_v3)
        if issn_print:
            query |= Q(journal__official_journal__issn_print=issn_print)
        if issn_electronic:
            query |= Q(journal__official_journal__issn_electronic=issn_electronic)
        if publication_year:
            query |= Q(issue__publication_year=publication_year)

    articles = Article.objects.filter(query)

    for article in articles.iterator():
        for article_per_lang in article.doi_with_lang.lang:
            process_article_availability.apply_async(
                kwargs=dict(
                    user_id=user_id,
                    username=username,
                    pid_v3=article.pid_v3,
                    journal_acron=article.journal.journal_acron,
                    lang=article_per_lang,
                )
            )


@celery_app.task(bind=True)
def process_article_availability(self, user_id, username, pid_v3, journal_acron, lang):
    urls = [
        f"https://www.scielo.br/scielo.php?script=sci_arttext&pid={pid_v3}&lng={lang}&nrm=iso", 
        f"https://www.scielo.br/j/{journal_acron}/a/{pid_v3}/?lang={lang}"
    ]
    try:
        user = _get_user(self.request, user_id=user_id, username=username)
        article = Article.objects.get(pid_v3=pid_v3)

        for url in urls:
            try:
                response = fetch_data(url, timeout=2, verify=True)
                CheckArticleAvailability.create_or_update(
                    article=article,
                    status=True,
                    url=url,
                    user=user,
                )
            except Exception as e:
                CheckArticleAvailability.create_or_update(
                    article=article,
                    status=False,
                    url=url,
                    user=user,
                )
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "function": "article.tasks.process_article_availability",
                "urls": urls
            },
        )