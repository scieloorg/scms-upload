import logging
import sys
import requests
from http import HTTPStatus

from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from collection.choices import PUBLIC, QA
from collection.models import Collection, WebSiteConfiguration
from config import celery_app
from core.models import PressRelease
from proc.models import ArticleProc, IssueProc, JournalProc
from proc.controller import create_or_update_journal, create_or_update_issue
from upload.models import Package
from publication.api.document import publish_article
from publication.api.issue import publish_issue
from publication.api.journal import publish_journal
from publication.api.pressrelease import publish_pressrelease
from publication.api.publication import PublicationAPI
from tracker.models import UnexpectedEvent


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
        incompleted = []
        if upload_package_id:
            manager = Package.objects.get(pk=upload_package_id)
            issue = manager.article.issue
        elif article_proc_id:
            manager = ArticleProc.objects.get(pk=article_proc_id)
            issue = manager.issue_proc.issue
        op_main = manager.start(user, f"publish on {website_kind}")

        article = manager.article
        journal = article.journal
        issue = article.issue

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
                    op_published_journal = manager.start(user, f"Publish journal")
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

                op_published_issue = manager.start(user, f"Publish issue")
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
            op_collection.finish(
                user,
                completed=completed,
                detail=response,
            )
            if not completed:
                incompleted.append(webiste_id)
        if not JournalProc.objects.filter(journal=journal).exists():
            raise JournalProc.DoesNotExist(f"No journal_proc for {article} {journal}")
        if not IssueProc.objects.filter(issue=issue).exists():
            raise IssueProc.DoesNotExist(f"No issue_proc for {article} {issue}")

        op_main.finish(
            user,
            completed=not bool(incompleted),
            exception=None,
            message_type=None,
            message=None,
            exc_traceback=None,
            detail=incompleted and {"incompletd": incompleted},
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
