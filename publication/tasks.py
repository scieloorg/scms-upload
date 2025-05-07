import logging
import sys
import requests
from datetime import datetime
from http import HTTPStatus

from collection.choices import PUBLIC, QA
from collection.models import Collection, WebSiteConfiguration
from config import celery_app
from core.models import PressRelease
from core.utils.requester import fetch_data, NonRetryableError
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from proc.models import ArticleProc, IssueProc, JournalProc
from publication import controller
from publication.models import ArticleAvailability
from publication.api.document import publish_article
from publication.api.issue import publish_issue
from publication.api.journal import publish_journal
from publication.api.pressrelease import publish_pressrelease
from publication.api.publication import PublicationAPI
from tracker.models import UnexpectedEvent

from .models import Article, ScieloURLStatus

# FIXME
# from upload.models import Package

User = get_user_model()

SCIELO_MODELS = {
    "journal": JournalProc,
    "issue": IssueProc,
    "article": ArticleProc,
    "pressrelease": PressRelease,
}

PUBLISH_FUNCTIONS = {
    "journal": publish_journal,
    "issue": publish_issue,
    "article": publish_article,
    "pressrelease": publish_pressrelease,
}


def _get_user(user_id, username):
    try:
        if user_id:
            return User.objects.get(pk=user_id)
        if username:
            return User.objects.get(username=username)
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "migration.tasks._get_user",
                "user_id": user_id,
                "username": username,
            },
        )


def _get_collections(collection_acron):
    try:
        if collection_acron:
            return Collection.objects.filter(acron=collection_acron).iterator()
        else:
            return Collection.objects.iterator()
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "migration.tasks._get_collections",
                "collection_acron": collection_acron,
            },
        )


# @celery_app.task(bind=True)
# def task_publish(
#     self,
#     user_id=None,
#     username=None,
#     website_kind=None,
#     collection_acron=None,
#     force_update=None,
# ):

#     website_kind = website_kind or QA
#     for collection in _get_collections(collection_acron):
#         if not collection.acron:
#             continue
#         task_publish_collection.apply_async(
#             kwargs=dict(
#                 user_id=user_id,
#                 username=username,
#                 website_kind=website_kind,
#                 collection_acron=collection.acron,
#                 force_update=force_update,
#             )
#         )


# @celery_app.task(bind=True)
# def task_publish_journals(
#     self,
#     user_id=None,
#     username=None,
#     website_kind=None,
#     collection_acron=None,
#     force_update=None,
# ):

#     for collection in _get_collections(collection_acron):
#         task_publish_model.apply_async(
#             kwargs=dict(
#                 user_id=user_id,
#                 username=username,
#                 website_kind=website_kind,
#                 collection_acron=collection.acron,
#                 force_update=force_update,
#                 model_name="journal",
#             )
#         )


# @celery_app.task(bind=True)
# def task_publish_issues(
#     self,
#     user_id=None,
#     username=None,
#     website_kind=None,
#     collection_acron=None,
#     force_update=None,
# ):
#     for collection in _get_collections(collection_acron):
#         task_publish_model.apply_async(
#             kwargs=dict(
#                 user_id=user_id,
#                 username=username,
#                 website_kind=website_kind,
#                 collection_acron=collection.acron,
#                 force_update=force_update,
#                 model_name="issue",
#             )
#         )


# @celery_app.task(bind=True)
# def task_publish_articles(
#     self,
#     user_id=None,
#     username=None,
#     website_kind=None,
#     collection_acron=None,
#     force_update=None,
# ):
#     for collection in _get_collections(collection_acron):
#         task_publish_model.apply_async(
#             kwargs=dict(
#                 user_id=user_id,
#                 username=username,
#                 website_kind=website_kind,
#                 collection_acron=collection.acron,
#                 force_update=force_update,
#                 model_name="article",
#             )
#         )


# @celery_app.task(bind=True)
# def task_publish_collection(
#     self,
#     user_id=None,
#     username=None,
#     website_kind=None,
#     collection_acron=None,
#     force_update=None,
# ):

#     for collection in _get_collections(collection_acron):
#         for model_name in ("journal", "issue", "article"):
#             task_publish_model.apply_async(
#                 kwargs=dict(
#                     user_id=user_id,
#                     username=username,
#                     website_kind=website_kind,
#                     collection_acron=collection.acron,
#                     force_update=force_update,
#                     model_name=model_name,
#                 )
#             )


# @celery_app.task(bind=True)
# def task_publish_model(
#     self,
#     user_id=None,
#     username=None,
#     website_kind=None,
#     collection_acron=None,
#     force_update=None,
#     model_name=None,
# ):

#     website_kind = website_kind or QA
#     model_name = model_name or "article"
#     collection = Collection.get(acron=collection_acron)
#     user = _get_user(user_id, username)

#     SciELOModel = SCIELO_MODELS.get(model_name)

#     api_data = _get_api_data(collection, website_kind, model_name)

#     for item in SciELOModel.items_to_publish(
#         user, website_kind, model_name, collection
#     ):
#         task_publish_item.apply_async(
#             kwargs=dict(
#                 user_id=user_id,
#                 username=username,
#                 item_id=item.id,
#                 api_data=api_data,
#                 model_name=model_name,
#                 website_kind=website_kind,
#             )
#         )


# @celery_app.task(bind=True)
# def task_publish_item(
#     self,
#     user_id,
#     username,
#     item_id,
#     api_data,
#     model_name,
#     website_kind,
# ):
#     try:
#         item = None
#         user = _get_user(user_id, username)
#         SciELOModel = SCIELO_MODELS.get(model_name)
#         item = SciELOModel.objects.get(pk=item_id)
#         item.publish(user, PUBLISH_FUNCTIONS.get(model_name), website_kind, api_data)
#     except Exception as e:
#         exc_type, exc_value, exc_traceback = sys.exc_info()
#         UnexpectedEvent.create(
#             e=e,
#             exc_traceback=exc_traceback,
#             detail=dict(
#                 item_id=item_id,
#                 model_name=model_name,
#             ),
#         )


@celery_app.task(bind=True)
def task_publish_collection_inline(
    self,
    user_id=None,
    username=None,
    website_kind=None,
    collection_acron=None,
):
    for collection in _get_collections(collection_acron):
        task_publish_model_inline.apply_async(
            kwargs=dict(
                user_id=user_id,
                username=username,
                website_kind=website_kind,
                collection_acron=collection.acron,
            )
        )


@celery_app.task(bind=True)
def task_publish_model_inline(
    self,
    user_id=None,
    username=None,
    website_kind=None,
    collection_acron=None,
):
    website_kind = website_kind or QA
    collection = Collection.get(acron=collection_acron)
    user = _get_user(user_id, username)

    website = WebSiteConfiguration.get(
        collection=collection,
        purpose=website_kind,
        enabled=True,
    )
    for ws in website.endpoint.all().filter(name="pressrelease"):
        SciELOModel = SCIELO_MODELS.get(ws.name)

        api = PublicationAPI(
            post_data_url=ws.url,
            get_token_url=website.api_get_token_url,
            username=website.api_username,
            password=website.api_password,
        )
        api.get_token()

        for item in SciELOModel.objects.all():
            task_publish_item_inline.apply_async(
                kwargs=dict(
                    item_id=item.id,
                    api_data=api.data,
                    model_name="pressrelease",
                )
            )


def task_publish_item_inline(
    item_id,
    api_data,
    model_name,
):
    try:
        SciELOModel = SCIELO_MODELS.get(model_name)
        PUBLISH_FUNCTIONS.get(model_name)(SciELOModel, api_data)
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail=dict(
                item_id=item_id,
                model_name=model_name,
            ),
        )


def is_registered(url):
    try:
        logging.info(url)
        x = requests.get(url, timeout=30)
        logging.info(x.status_code)
        return x.status_code == HTTPStatus.OK
    except Exception as e:
        return None


@celery_app.task(bind=True)
def task_publish_article(
    self,
    user_id,
    username,
    websites,
    article_proc_id=None,
    upload_package_id=None,
    publication_rule=None,
):
    """
    Tarefa que publica artigos ingressados pelo Upload
    """
    try:
        logging.info(dict(
            user_id=user_id,
            username=username,
            websites=websites,
            article_proc_id=article_proc_id,
            upload_package_id=upload_package_id,
            publication_rule=publication_rule,
        ))
        
        user = _get_user(user_id, username)
        op_main = None
        manager = None
        responses = []

        # Obter gerenciador e informações do artigo
        manager = controller.get_manager_info(article_proc_id, upload_package_id)
        
        article = manager.article
        journal = article.journal
        issue = article.issue

        if len(websites) > 1:
            published_by = "SYSTEM"
        elif manager.assignee:
            published_by = manager.assignee.username or manager.assignee.id
        elif manager.analyst:
            published_by = manager.analyst.user.username or manager.analyst.user.id 
        elif manager.updated_by:
            published_by = manager.updated_by.username or manager.updated_by.id 
        elif manager.creator:
            published_by = manager.creator.username or manager.creator.id 
        # Iniciar operação principal
        op_main = manager.start(user, f"Publishing article to {', '.join(websites)}")
        
        # Garantir que o JournalProc existe (pré-requisito comum)
        controller.ensure_journal_proc_exists(user, journal)

        # Garantir que o IssueProc existe (pré-requisito comum)
        controller.ensure_issue_proc_exists(user, issue)
    
        responses = list(
            controller.publish_article_collection_websites(
                user, manager, websites))
        op_main.finish(
            user,
            completed=bool(any([item["published"] for item in responses])),
            exception=None,
            message_type=None,
            message=None,
            exc_traceback=None,
            detail=responses,
        )

    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        if op_main:
            op_main.finish(
                user,
                completed=False,
                exception=e,
                exc_traceback=exc_traceback,
                detail=None,
            )
        else:
            UnexpectedEvent.create(
                e=e,
                exc_traceback=exc_traceback,
                detail=dict(
                    task="task_publish_article",
                    item=str(manager),
                    article_proc_id=article_proc_id,
                    upload_package_id=upload_package_id,
                    websites=websites,
                ),
            )

    try:
        # check availability
        op_main = manager.start(user, f"Check article availability on {', '.join(websites)}")
        logging.info("ArticleAvailabilityArticleAvailabilityArticleAvailability")
        logging.info(responses)
        logging.info(dict(publication_rule=publication_rule, published_by=published_by))           
        if responses:
            obj = ArticleAvailability.create_or_update(
                user,
                article,
                published_by=published_by,
                publication_rule=publication_rule,
            )
        for response in responses:
            for website in WebSiteConfiguration.objects.filter(
                collection__acron=response["collection"],
                purpose__in=websites,
                enabled=True,
            ):
                process_article_availability.apply_async(
                    kwargs=dict(
                        pid_v3=article.pid_v3,
                        user_id=user_id,
                        username=username,
                        domain=website.url,
                    )
                )
        op_main.finish(
            user,
            completed=True,
            detail=dict(
                pid_v3=article.pid_v3,
                websites=websites,
            ),
        )
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        if op_main:
            op_main.finish(
                user,
                completed=False,
                exception=e,
                exc_traceback=exc_traceback,
                websites=websites,
            )
        else:
            UnexpectedEvent.create(
                e=e,
                exc_traceback=exc_traceback,
                detail=dict(
                    task="task_publish_article",
                    item=str(manager),
                    article_proc_id=article_proc_id,
                    upload_package_id=upload_package_id,
                    websites=websites,
                ),
            )


@celery_app.task(bind=True)
def task_check_article_availability(
    self,
    username,
    user_id=None,
    issn_print=None,
    issn_electronic=None,
    publication_year=None,
    article_pid_v3=None,
    collection_acron=None,
    purpose=None,
):

    if collection_acron:
        collection = Collection.objects.filter(acron=collection_acron)
    else:
        collection = Collection.objects.all()

    journal_query = Q()
    if collection:
        journal_query |= Q(collection__in=collection)
    if issn_print:
        journal_query |= Q(journal__official_journal__issn_print=issn_print)
    if issn_electronic:
        journal_query |= Q(journal__official_journal__issn_electronic=issn_electronic)

    article_query = Q()
    if article_pid_v3:
        article_query |= Q(pid_v3=article_pid_v3)
    if publication_year:
        article_query |= Q(issue__publication_year=publication_year)

    try:
        for journal_proc in JournalProc.objects.filter(journal_query, journal__isnull=False):
            if not journal_proc.journal.journal_acron:
                journal_proc.journal.journal_acron = journal_proc.acron
                journal_proc.journal.save()
            for article in Article.objects.filter(
                article_query, journal=journal_proc.journal
            ):
                for item in WebSiteConfiguration.objects.filter(
                    enabled=True, collection=journal_proc.collection
                ):
                    process_article_availability.apply_async(
                        kwargs=dict(
                            pid_v3=article.pid_v3,
                            user_id=user_id,
                            username=username,
                            domain=item.url,
                        )
                    )
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "function": "publication.tasks.task_check_article_availability",
            },
        )


@celery_app.task(bind=True)
def process_article_availability(
    self, pid_v3, domain, user_id, username, timeout=None,
):
    try:
        user = _get_user(user_id=user_id, username=username)
        article = Article.objects.get(pid_v3=pid_v3)
        logging.info(f"{domain} {pid_v3}")
        obj = ArticleAvailability.create_or_update(user, article)
        obj.create_or_update_urls(user, website_url=domain, timeout=timeout)
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "function": "publication.tasks.process_article_availability",
                "domain": domain,
                "pid_v3": pid_v3,
            },
        )


@celery_app.task(bind=True)
def retry_failed_scielo_urls(self, username=None, user_id=None, pid_v3=None, timeout=None):
    try:
        user = _get_user(user_id=user_id, username=username)
        params = {}
        params["available"] = False
        if pid_v3:
            params["article_availability__article__pid_v3"] = pid_v3

        for scielo_url_status in ScieloURLStatus.objects.filter(**params):
            scielo_url_status.update(user, timeout)
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "function": "publication.tasks.retry_failed_scielo_urls",
                "pid_v3": pid_v3,
            },
        )


@celery_app.task(bind=True)
def fetch_data_and_register_result(self, pid_v3, url, username, user_id):
    try:
        user = _get_user(user_id=user_id, username=username)
        article = Article.objects.get(pid_v3=pid_v3)
        ScieloURLStatus.create_or_update(
            user=user,
            article=article,
            url=url,
        )
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "function": "publication.tasks.fetch_data_and_register_result",
                "url": url,
                "pid_v3": pid_v3,
            },
        )
