import logging
import sys

from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from collection.choices import QA
from collection.models import Collection, WebSiteConfiguration
from config import celery_app
from proc.models import ArticleProc, IssueProc, JournalProc
from core.models import PressRelease
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
    "pressrelease": PressRelease
}

PUBLISH_FUNCTIONS = {
    "journal": publish_journal,
    "issue": publish_issue,
    "article": publish_article,
    "pressrelease": publish_pressrelease
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


def _get_api_data(collection, website_kind, item_name):
    website = WebSiteConfiguration.get(
        collection=collection,
        purpose=website_kind,
    )
    API_URLS = {
        "journal": website.api_url_journal,
        "issue": website.api_url_issue,
        "article": website.api_url_article,
    }
    api = PublicationAPI(
        post_data_url=API_URLS.get(item_name),
        get_token_url=website.api_get_token_url,
        username=website.api_username,
        password=website.api_password,
    )
    api.get_token()
    return api.data


@celery_app.task(bind=True)
def task_publish(
    self,
    user_id=None,
    username=None,
    website_kind=None,
    collection_acron=None,
    force_update=None,
):

    website_kind = website_kind or QA
    for collection in _get_collections(collection_acron):
        if not collection.acron:
            continue
        task_publish_collection.apply_async(
            kwargs=dict(
                user_id=user_id,
                username=username,
                website_kind=website_kind,
                collection_acron=collection.acron,
                force_update=force_update,
            )
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

    for collection in _get_collections(collection_acron):
        task_publish_model.apply_async(
            kwargs=dict(
                user_id=user_id,
                username=username,
                website_kind=website_kind,
                collection_acron=collection.acron,
                force_update=force_update,
                model_name="journal",
            )
        )


@celery_app.task(bind=True)
def task_publish_issues(
    self,
    user_id=None,
    username=None,
    website_kind=None,
    collection_acron=None,
    force_update=None,
):
    for collection in _get_collections(collection_acron):
        task_publish_model.apply_async(
            kwargs=dict(
                user_id=user_id,
                username=username,
                website_kind=website_kind,
                collection_acron=collection.acron,
                force_update=force_update,
                model_name="issue",
            )
        )


@celery_app.task(bind=True)
def task_publish_articles(
    self,
    user_id=None,
    username=None,
    website_kind=None,
    collection_acron=None,
    force_update=None,
):
    for collection in _get_collections(collection_acron):
        task_publish_model.apply_async(
            kwargs=dict(
                user_id=user_id,
                username=username,
                website_kind=website_kind,
                collection_acron=collection.acron,
                force_update=force_update,
                model_name="article",
            )
        )


@celery_app.task(bind=True)
def task_publish_collection(
    self,
    user_id=None,
    username=None,
    website_kind=None,
    collection_acron=None,
    force_update=None,
):

    for collection in _get_collections(collection_acron):
        for model_name in ("journal", "issue", "article"):
            task_publish_model.apply_async(
                kwargs=dict(
                    user_id=user_id,
                    username=username,
                    website_kind=website_kind,
                    collection_acron=collection.acron,
                    force_update=force_update,
                    model_name=model_name,
                )
            )


@celery_app.task(bind=True)
def task_publish_model(
    self,
    user_id=None,
    username=None,
    website_kind=None,
    collection_acron=None,
    force_update=None,
    model_name=None,
):

    website_kind = website_kind or QA
    model_name = model_name or "article"
    collection = Collection.get(acron=collection_acron)
    user = _get_user(user_id, username)

    SciELOModel = SCIELO_MODELS.get(model_name)

    api_data = _get_api_data(collection, website_kind, model_name)

    for item in SciELOModel.items_to_publish(
        user, website_kind, model_name, collection
    ):
        task_publish_item.apply_async(
            kwargs=dict(
                user_id=user_id,
                username=username,
                item_id=item.id,
                api_data=api_data,
                model_name=model_name,
                website_kind=website_kind,
            )
        )


@celery_app.task(bind=True)
def task_publish_item(
    self,
    user_id,
    username,
    item_id,
    api_data,
    model_name,
    website_kind,
):
    try:
        item = None
        user = _get_user(user_id, username)
        SciELOModel = SCIELO_MODELS.get(model_name)
        item = SciELOModel.objects.get(pk=item_id)
        item.publish(user, PUBLISH_FUNCTIONS.get(model_name), website_kind, api_data)
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