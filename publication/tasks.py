import logging
from datetime import datetime

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from article.models import SciELOArticle
from article.tasks import task_create_or_update_articles
from collection.choices import QA
from collection.models import Collection, WebSiteConfiguration
from config import celery_app
from issue.models import SciELOIssue
from journal.models import SciELOJournal
from publication.api.document import publish_article as api_publish_article
from publication.api.issue import publish_issue as api_publish_issue
from publication.api.journal import publish_journal as api_publish_journal
from publication.db.document import publish_article
from publication.db.issue import publish_issue
from publication.db.journal import publish_journal
from publication.db.db import mk_connection


User = get_user_model()

# try:
#     website = WebSiteConfiguration.objects.get(
#         purpose=QA,
#         enabled=True,
#         db_uri__isnull=False,
#     )
#     mk_connection(website.db_uri)
# except Exception as e:
#     pass


def db_connect(collection, website_kind):
    return
    if website_kind == QA:
        logging.info(dict(
            collection=collection,
            purpose=website_kind,
            db_uri__isnull=False,
            enabled=True,
        ))
        try:
            website = WebSiteConfiguration.objects.get(
                collection=collection,
                purpose=website_kind,
                db_uri__isnull=False,
                enabled=True,
            )
        except WebSiteConfiguration.DoesNotExist:
            for item in WebSiteConfiguration.objects.iterator():
                logging.info(
                    (item.collection, item.purpose, item.db_uri, item.enabled)
                )
        else:
            mk_connection(website.db_uri)


def _get_user(user_id, username):
    if user_id:
        return User.objects.get(pk=user_id)
    if username:
        return User.objects.get(username=username)


@celery_app.task(bind=True)
def task_publish(
    self,
    user_id=None,
    username=None,
    collection_acron=None,
    force_update=False,
):
    user = _get_user(user_id, username)
    # registra articles
    task_create_or_update_articles.apply_async(
        kwargs={
            "user_id": user.id,
            "collection_acron": collection_acron,
            "force_update": force_update,
        }
    )
    # publica journals
    task_publish_journals.apply_async(
        kwargs={
            "user_id": user.id,
            "collection_acron": collection_acron,
            "force_update": force_update,
        }
    )
    # publica issues
    task_publish_issues.apply_async(
        kwargs={
            "user_id": user.id,
            "collection_acron": collection_acron,
            "force_update": force_update,
        }
    )
    # publica
    task_publish_articles.apply_async(
        kwargs={
            "user_id": user.id,
            "collection_acron": collection_acron,
            "force_update": force_update,
        }
    )


@celery_app.task(bind=True)
def task_publish_journals(
    self,
    user_id=None,
    username=None,
    website_kind=None,
    collection_acron=None,
    force_update=None,
):

    website_kind = website_kind or QA

    if collection_acron:
        collections = Collection.objects.filter(acron=collection_acron).iterator()
    else:
        collections = Collection.objects.iterator()
    if force_update:
        for collection in collections:
            for item in SciELOJournal.objects.filter(
                publication_stage__isnull=False,
                collection=collection,
            ).iterator():
                item.publication_stage = None
                item.save()

    if collection_acron:
        collections = Collection.objects.filter(acron=collection_acron).iterator()
    else:
        collections = Collection.objects.iterator()
    for collection in collections:
        db_connect(collection, website_kind)

        items = SciELOJournal.items_to_publish(website_kind, collection)

        for journal in items:
            task_publish_journal.apply_async(
                kwargs={
                    "user_id": user_id,
                    "username": username,
                    "journal_id": journal.id,
                    "website_kind": website_kind,
                }
            )


@celery_app.task(bind=True)
def task_publish_journal(
    self,
    username,
    user_id,
    journal_id,
    website_kind,
):
    user = _get_user(user_id, username)
    scielo_journal = SciELOJournal.objects.get(id=journal_id)

    website = WebSiteConfiguration.get(
        collection=scielo_journal.collection,
        purpose=website_kind,
    )

    if website.api_url_journal:
        return api_publish_journal(user, website, scielo_journal)
    if website.db_uri:
        publish_journal(user, website, scielo_journal)


@celery_app.task(bind=True)
def task_publish_issues(
    self,
    user_id=None,
    username=None,
    website_kind=None,
    collection_acron=None,
    force_update=None,
):
    website_kind = website_kind or QA

    if collection_acron:
        collections = Collection.objects.filter(acron=collection_acron).iterator()
    else:
        collections = Collection.objects.iterator()
    if force_update:
        for collection in collections:
            for item in SciELOIssue.objects.filter(
                publication_stage__isnull=False,
                scielo_journal__collection=collection,
            ).iterator():
                item.publication_stage = None
                item.save()

    if collection_acron:
        collections = Collection.objects.filter(acron=collection_acron).iterator()
    else:
        collections = Collection.objects.iterator()
    for collection in collections:
        db_connect(collection, website_kind)
        items = SciELOIssue.items_to_publish(
            website_kind,
            scielo_journal__collection=collection,
        )
        for issue in items:
            task_publish_issue.apply_async(
                kwargs={
                    "user_id": user_id,
                    "username": username,
                    "issue_id": issue.id,
                    "website_kind": website_kind,
                }
            )


@celery_app.task(bind=True)
def task_publish_issue(
    self,
    user_id,
    username,
    issue_id,
    website_kind,
):
    user = _get_user(user_id, username)
    scielo_issue = SciELOIssue.objects.get(id=issue_id)
    website = WebSiteConfiguration.get(
        collection=scielo_issue.scielo_journal.collection,
        purpose=website_kind,
    )
    if website.api_url_issue:
        return api_publish_issue(user, website, scielo_issue)
    if website.db_uri:
        publish_issue(user, website, scielo_issue)


@celery_app.task(bind=True)
def task_publish_articles(
    self,
    user_id=None,
    username=None,
    website_kind=None,
    collection_acron=None,
    force_update=None,
):
    website_kind = website_kind or QA

    if collection_acron:
        collections = Collection.objects.filter(acron=collection_acron).iterator()
    else:
        collections = Collection.objects.iterator()
    if force_update:
        for collection in collections:
            logging.info(collection)
            SciELOArticle.objects.filter(
                publication_stage__isnull=False,
                collection=collection,
            ).update(publication_stage=None)

    if collection_acron:
        collections = Collection.objects.filter(acron=collection_acron).iterator()
    else:
        collections = Collection.objects.iterator()
    for collection in collections:
        items = SciELOArticle.items_to_publish(website_kind)
        for item in items:
            logging.info("artigo")
            task_publish_article.apply_async(
                kwargs={
                    "user_id": user_id,
                    "username": username,
                    "article_id": item.id,
                    "website_kind": website_kind,
                }
            )


@celery_app.task(bind=True)
def task_publish_article(
    self,
    user_id,
    username,
    article_id,
    website_kind,
):
    logging.info(article_id)
    user = _get_user(user_id, username)
    scielo_article = SciELOArticle.objects.get(id=article_id)
    website = WebSiteConfiguration.get(
        collection=scielo_article.collection,
        purpose=website_kind,
    )
    if website.api_url_article:
        return api_publish_article(user, website, scielo_article)
    if website.db_uri:
        db_connect(scielo_article.collection, website_kind)
        publish_article(user, website, scielo_article)
