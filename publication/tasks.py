import gzip
import logging
import sys
import requests
from http import HTTPStatus

from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _
from datetime import datetime

from collection.choices import PUBLIC, QA
from collection.models import Collection, WebSiteConfiguration
from config import celery_app
from core.models import PressRelease
from core.utils.requester import fetch_data
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from proc.models import ArticleProc, IssueProc, JournalProc
from proc.controller import create_or_update_journal, create_or_update_issue
from upload.models import Package
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
    api_data,
    website_kind,
    article_proc_id=None,
    upload_package_id=None,
):
    """
    Tarefa que publica artigos ingressados pelo Upload
    """
    try:
        user = _get_user(user_id, username)
        op_main = None
        manager = None
        tracking = []
        if upload_package_id:
            manager = Package.objects.get(pk=upload_package_id)
            issue = manager.issue
            journal = manager.journal
            logging.info(journal)
            logging.info(issue)

        elif article_proc_id:
            manager = ArticleProc.objects.get(pk=article_proc_id)
            issue = manager.issue_proc.issue
            journal = manager.journal_proc.journal

        op_main = manager.start(user, f"publish on {website_kind}")

        article = manager.article
 
        if not JournalProc.objects.filter(journal=journal).exists():
            op_journal_proc = manager.start(user, f"publish on {website_kind} - create_or_update_journal")
            created = create_or_update_journal(
                journal_title=journal.title,
                issn_electronic=journal.official_journal.issn_electronic,
                issn_print=journal.official_journal.issn_print,
                user=user,
                force_update=True,
            )
            op_journal_proc.finish(user, completed=bool(created))

        if not IssueProc.objects.filter(issue=issue).exists():
            op_issue_proc = manager.start(user, f"publish on {website_kind} - create_or_update_issue")
            created = create_or_update_issue(
                journal=journal,
                pub_year=issue.publication_year,
                volume=issue.volume,
                suppl=issue.supplement,
                number=issue.number,
                user=user,
                force_update=True,
            )
            op_issue_proc.finish(user, completed=bool(created))

        for journal_proc in JournalProc.objects.filter(journal=journal):

            webiste_id = f"{website_kind} {journal_proc.collection}"
            executing = {"website": webiste_id}
            op_collection = manager.start(
                user, f"> publish on {webiste_id}"
            )
            try:
                website = WebSiteConfiguration.get(
                    collection=journal_proc.collection,
                    purpose=website_kind,
                )
            except WebSiteConfiguration.DoesNotExist as exc:
                op_collection.finish(
                    user,
                    completed=False,
                    message=f"{webiste_id} does not exist",
                    exception=exc,
                    detail=None,
                )
                continue

            api = PublicationAPI(
                post_data_url=website.api_url_article,
                get_token_url=website.api_get_token_url,
                username=website.api_username,
                password=website.api_password,
                timeout=15,
            )
            api.get_token()
            api_data = api.data

            issue_proc = IssueProc.objects.get(
                journal_proc=journal_proc, issue=issue
            )
            # issue_url = f"{website.url}/j/{journal_proc.acron}/i/{issue.publication_year}.{issue.issue_folder}"
            issue_url = f"{website.url}/scielo.php?pid={issue_proc.pid}&script=sci_issuetoc"
            if not is_registered(issue_url):

                journal_url = f"{website.url}/scielo.php?pid={journal_proc.pid}&script=sci_serial"
                if not is_registered(journal_url):
                    op_published_journal = manager.start(user, f"publish journal on {website_kind}")
                    api_data["post_data_url"] = website.api_url_journal
                    response = journal_proc.publish(
                        user,
                        publish_journal,
                        website_kind=website_kind,
                        api_data=api_data,
                        force_update=True,
                        content_type="journal"
                    )
                    response["url"] = journal_url
                    op_published_journal.finish(user, completed=response.get("completed"), detail=response)

                op_published_issue = manager.start(user, f"publish issue on {website_kind}")
                api_data["post_data_url"] = website.api_url_issue
                response = issue_proc.publish(
                    user,
                    publish_issue,
                    website_kind=website_kind,
                    api_data=api_data,
                    force_update=True,
                    content_type="issue"
                )
                response["url"] = issue_url
                op_published_issue.finish(user, completed=response.get("completed"), detail=response)

            api_data["post_data_url"] = website.api_url_article
            response = publish_article(manager, api_data, journal_proc.pid)
            completed = response.get("result") == "OK"
            manager.update_publication_stage(website_kind, completed=completed)

            executing["completed"] = completed
            op_collection.finish(
                user,
                completed=completed,
                detail=response,
            )
            tracking.append(executing)
        if not JournalProc.objects.filter(journal=journal).exists():
            raise JournalProc.DoesNotExist(f"No journal_proc for {article} {journal}")
        if not IssueProc.objects.filter(issue=issue).exists():
            raise IssueProc.DoesNotExist(f"No issue_proc for {article} {issue}")

        op_main.finish(
            user,
            completed=len(tracking)==len([item for item in tracking if item["completed"]]),
            exception=None,
            message_type=None,
            message=None,
            exc_traceback=None,
            detail=tracking,
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
                    website_kind=website_kind,
                ),
            )
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail=dict(
                task="task_publish_article",
                item=str(manager),
                article_proc_id=article_proc_id,
                upload_package_id=article_proc_id,
                website_kind=website_kind,
            ),
        )


@celery_app.task(bind=True)
def initiate_article_availability_check(
    self,
    username,
    user_id=None,
    issn_print=None,
    issn_electronic=None,
    publication_year=None,
    updated=None,
    article_pid_v3=None,
    collection_acron=None,
    purpose="PUBLIC",
):
    if collection_acron:
        collection = Collection.objects.filter(acron=collection_acron)
    else:
        collection = Collection.objects.all()

    query = Q()
    if not updated:
        if article_pid_v3:
            query |= Q(pid_v3=article_pid_v3)
        if issn_print:
            query |= Q(journal__official_journal__issn_print=issn_print)
        if issn_electronic:
            query |= Q(journal__official_journal__issn_electronic=issn_electronic)
        if publication_year:
            query |= Q(issue__publication_year=publication_year)

    try:
        for col in collection:
            for journal_collection in col.journalcollection_set.all():
                for article in journal_collection.journal.article_set.filter(query):
                    for lang in article.article_langs:
                        process_article_availability.apply_async(
                            kwargs=dict(
                                user_id=user_id,
                                username=username,
                                pid_v3=article.pid_v3,
                                pid_v2=article.pid_v2,
                                journal_acron=article.journal.journal_acron,
                                lang=lang,
                                domain=journal_collection.collection.websiteconfiguration_set.get(
                                    enabled=True, purpose=purpose
                                ).url,
                            )
                        )
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "function": "publication.tasks.initiate_article_availability_check",
            },
        )


@celery_app.task(bind=True)
def process_article_availability(
    self, user_id, username, pid_v3, pid_v2, journal_acron, lang, domain
):
    urls = [
        f"{domain}/scielo.php?script=sci_arttext&pid={pid_v2}&lang={lang}&nrm=iso",
        f"{domain}/j/{journal_acron}/a/{pid_v3}/?lang={lang}",
        f"{domain}/scielo.php?script=sci_arttext&pid={pid_v2}&format=pdf&lng={lang}&nrm=iso",
        f"{domain}/j/{journal_acron}/a/{pid_v3}/?format=pdf&lang={lang}",
    ]

    for url in urls:
        fetch_data_and_register_result.apply_async(
            kwargs=dict(
                pid_v3=pid_v3,
                url=url,
                username=username,
                user_id=user_id,
            )
        )


@celery_app.task(bind=True)
def retry_failed_scielo_urls(self, username, user_id=None):
    for scielo_url_status in ScieloURLStatus.objects.filter(available=False):
        fetch_data_and_register_result.apply_async(
            kwargs=dict(
                pid_v3=scielo_url_status.article_availability.article.pid_v3,
                url=scielo_url_status.url,
                username=username,
                user_id=user_id,
            )
        )


@celery_app.task(bind=True)
def fetch_data_and_register_result(self, pid_v3, url, username, user_id):
    try:
        user = _get_user(user_id=user_id, username=username)
        article = Article.objects.get(pid_v3=pid_v3)

        try:
            response = fetch_data(url, timeout=2, verify=True)
        except Exception as e:
            ScieloURLStatus.create_or_update(
                article=article,
                url=url,
                check_date=datetime.now(),
                available=False,
                user=user,
            )
        else:
            try:
                obj = ScieloURLStatus.get(article=article, url=url)
                obj.available = True
                obj.save()
            except ScieloURLStatus.DoesNotExist:
                ScieloURLStatus.create_or_update(
                    article=article,
                    url=url,
                    check_date=datetime.now(),
                    available=True,
                    user=user,
                )
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "function": "publication.tasks.process_article_availability",
                "url": url,
            },
        )
