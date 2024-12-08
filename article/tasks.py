import re
import sys
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from article.choices import VERIFY_HTTP_ERROR_CODE
from config import celery_app
from core.utils.get_user import _get_user
from core.utils.requester import fetch_data, NonRetryableError, RetryableError
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

    try:
        for article in articles.iterator():
            for article_per_lang in article.doi_with_lang.lang:
                process_article_availability.apply_async(
                    kwargs=dict(
                        user_id=user_id,
                        username=username,
                        pid_v3=article.pid_v3,
                        pid_v2=article.sps_pkg.articleproc_set.first().pid,
                        journal_acron=article.journal.journal_acron,
                        lang=article_per_lang,
                        domain=article.journal.journalproc_set.first().collection.websiteconfiguration_set.get(enabled=True).url,
                    )
                )
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "function": "article.tasks.initiate_article_availability_check",
            },
        )

@celery_app.task(bind=True)
def process_article_availability(self, user_id, username, pid_v3, pid_v2, journal_acron, lang, domain,):
    urls = [
        f"{domain}/scielo.php?script=sci_arttext&pid={pid_v2}&lang={lang}&nrm=iso", 
        f"{domain}/j/{journal_acron}/a/{pid_v3}/?lang={lang}",
        f"{domain}/scielo.php?script=sci_arttext&pid={pid_v2}&format=pdf&lng={lang}&nrm=iso", 
        f"{domain}/j/{journal_acron}/a/{pid_v3}/?format=pdf&lang={lang}",
    ]
    pattern = r"format=pdf"
    try:
        user = _get_user(self.request, user_id=user_id, username=username)
        article = Article.objects.get(pid_v3=pid_v3)

        for url in urls:
            try:
                response = fetch_data(url, timeout=2, verify=True)
            except Exception as e :
                CheckArticleAvailability.create_or_update(
                    article=article,
                    status=dict(VERIFY_HTTP_ERROR_CODE).get(type(e),  _("An unknown error occurred")),
                    available=False,
                    url=url,
                    type=re.search(pattern, url),
                    user=user,
                )
                continue
            CheckArticleAvailability.create_or_update(
                article=article,
                status="Site Available",
                available=True,
                url=url,
                type=re.search(pattern, url),
                user=user,
            )
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "function": "article.tasks.process_article_availability",
                "urls": urls,
                "url": url,
            },
        )