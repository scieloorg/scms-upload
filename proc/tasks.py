import logging
import sys

from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from collection.models import Collection
from config import celery_app
from proc.models import ArticleProc, IssueProc, JournalProc
from tracker.models import UnexpectedEvent

from . import controller

User = get_user_model()


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
                "task": "proc.tasks._get_user",
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
                "task": "proc.tasks._get_collections",
                "collection_acron": collection_acron,
            },
        )


############################################
@celery_app.task(bind=True)
def task_create_or_update_journals(
    self,
    user_id=None,
    username=None,
    collection_acron=None,
    force_update=False,
):
    """
    Percorre os registros MigratedData (source="journal"),
    e com seus dados, cria registros OfficialJournal, JournalProc e Journal

    Parameters
    ----------
    user_id : int
        identificacao do usuário
    username : str
        identificacao do usuário
    collection_acron : str
        acrônimo da coleção
    force_update : bool
        atualiza mesmo se já existe

    """
    try:
        content_type = "journal"
        for collection in _get_collections(collection_acron):
            items = JournalProc.items_to_register(
                collection, content_type, force_update
            )
            for item in items:
                # dispara tarefas para criar/atualizar os registros
                # OfficialJournal, JournalProc e Journal
                task_create_or_update_journal.apply_async(
                    kwargs=dict(
                        user_id=user_id,
                        username=username,
                        item_id=item.id,
                        force_update=force_update,
                    )
                )
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "proc.tasks.task_create_or_update_journals",
                "user_id": user_id,
                "username": username,
                "collection_acron": collection_acron,
                "force_update": force_update,
            },
        )


@celery_app.task(bind=True)
def task_create_or_update_journal(
    self,
    user_id=None,
    username=None,
    item_id=None,
    force_update=False,
):
    """
    Para um dado registro de MigratedData(journal),
    cria ou atualiza os registros de OfficialJournal, JournalProc e Journal

    Parameters
    ----------
    user_id : int
        identificacao do usuário
    username : str
        identificacao do usuário
    item_id : int
        id de MigratedData(journal)
    force_update : bool
        atualiza mesmo se já existe

    """
    try:
        user = _get_user(user_id, username)
        item = JournalProc.objects.get(pk=item_id)
        item.create_or_update_item(
            user, force_update, controller.create_or_update_journal
        )
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "proc.tasks.task_create_or_update_journal",
                "user_id": user_id,
                "username": username,
                "item_id": item_id,
                "force_update": force_update,
            },
        )
        raise e


@celery_app.task(bind=True)
def task_create_or_update_issues(
    self,
    user_id=None,
    username=None,
    collection_acron=None,
    force_update=False,
):
    """
    Percorre os registros MigratedData (source="issue"),
    e com seus dados, cria registros IssueProc e Issue

    Parameters
    ----------
    user_id : int
        identificacao do usuário
    username : str
        identificacao do usuário
    force_update : bool
        atualiza mesmo se já existe

    """
    try:
        for collection in _get_collections(collection_acron):
            items = IssueProc.items_to_register(collection, "issue", force_update)
            for item in items:
                # dispara tarefas para criar/atualizar os registros
                # IssueProc e Issue
                task_create_or_update_issue.apply_async(
                    kwargs=dict(
                        user_id=user_id,
                        username=username,
                        item_id=item.id,
                        force_update=force_update,
                    )
                )
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "proc.tasks.task_create_or_update_issues",
                "user_id": user_id,
                "username": username,
                "collection_acron": collection_acron,
                "force_update": force_update,
            },
        )


@celery_app.task(bind=True)
def task_create_or_update_issue(
    self,
    user_id=None,
    username=None,
    item_id=None,
    force_update=False,
):
    """
    Para um dado registro de MigratedData(issue),
    cria ou atualiza os registros de IssueProc e Issue

    Parameters
    ----------
    user_id : int
        identificacao do usuário
    username : str
        identificacao do usuário
    item_id : int
        id de MigratedData(issue)
    force_update : bool
        atualiza mesmo se já existe

    """
    try:
        user = _get_user(user_id, username)
        item = IssueProc.objects.get(pk=item_id)
        item.create_or_update_item(
            user, force_update, controller.create_or_update_issue
        )
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "proc.tasks.task_create_or_update_issue",
                "item_id": item_id,
                "user_id": user_id,
                "username": username,
            },
        )


@celery_app.task(bind=True)
def task_generate_sps_packages(
    self,
    user_id=None,
    username=None,
    collection_acron=None,
    journal_acron=None,
    publication_year=None,
    issue_folder=None,
    force_update=False,
    body_and_back_xml=False,
    html_to_xml=False,
    force_core_update=True,
):
    try:
        for collection in _get_collections(collection_acron):
            items = ArticleProc.items_to_build_sps_pkg(
                collection_acron,
                journal_acron,
                publication_year,
                issue_folder,
                force_update,
            )
            for item in items:
                task_generate_sps_package.apply_async(
                    kwargs={
                        "username": username,
                        "user_id": user_id,
                        "item_id": item.id,
                        "body_and_back_xml": body_and_back_xml,
                        "html_to_xml": html_to_xml,
                        "force_core_update": force_core_update,
                    }
                )
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "proc.tasks.task_generate_sps_packages",
                "user_id": user_id,
                "username": username,
                "collection_acron": collection_acron,
                "journal_acron": journal_acron,
                "publication_year": publication_year,
                "issue_folder": issue_folder,
                "force_update": force_update,
                "body_and_back_xml": body_and_back_xml,
                "html_to_xml": html_to_xml,
                "force_core_update": force_core_update,
            },
        )


@celery_app.task(bind=True)
def task_generate_sps_package(
    self,
    item_id=None,
    body_and_back_xml=False,
    html_to_xml=False,
    username=None,
    user_id=None,
    force_core_update=None,
):
    try:
        user = _get_user(user_id, username)
        item = ArticleProc.objects.get(pk=item_id)
        if force_core_update and item.sps_pkg:
            item.sps_pkg.set_registered_in_core(False)
        item.generate_sps_package(
            user,
            body_and_back_xml,
            html_to_xml,
        )
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "proc.tasks.task_generate_sps_package",
                "item_id": item_id,
                "user_id": user_id,
                "username": username,
                "body_and_back_xml": body_and_back_xml,
                "html_to_xml": html_to_xml,
            },
        )


@celery_app.task(bind=True)
def task_create_or_update_articles(
    self,
    user_id=None,
    username=None,
    collection_acron=None,
    force_update=False,
):
    """
    Percorre os registros MigratedData (source="article"),
    e com seus dados, cria registros ArticleProc e Article

    Parameters
    ----------
    user_id : int
        identificacao do usuário
    username : str
        identificacao do usuário
    force_update : bool
        atualiza mesmo se já existe

    """
    try:
        for collection in _get_collections(collection_acron):
            items = ArticleProc.items_to_register(collection, "article", force_update)
            for item in items:
                # dispara tarefas para criar/atualizar os registros
                # ArticleProc e Article
                task_create_or_update_article.apply_async(
                    kwargs=dict(
                        user_id=user_id,
                        username=username,
                        item_id=item.id,
                        force_update=force_update,
                    )
                )
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "proc.tasks.task_create_or_update_articles",
                "user_id": user_id,
                "username": username,
                "collection_acron": collection_acron,
                "force_update": force_update,
            },
        )


@celery_app.task(bind=True)
def task_create_or_update_article(
    self,
    user_id=None,
    username=None,
    item_id=None,
    force_update=False,
):
    """
    Para um dado registro de MigratedData(article),
    cria ou atualiza os registros de ArticleProc e Article

    Parameters
    ----------
    user_id : int
        identificacao do usuário
    username : str
        identificacao do usuário
    item_id : int
        id de MigratedData(article)
    force_update : bool
        atualiza mesmo se já existe

    """
    try:
        user = _get_user(user_id, username)
        item = ArticleProc.objects.get(pk=item_id)
        item.create_or_update_item(
            user, force_update, controller.create_or_update_article
        )
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "proc.tasks.task_create_or_update_article",
                "item_id": item_id,
                "user_id": user_id,
                "username": username,
            },
        )


@celery_app.task(bind=True)
def task_synchronize_to_pid_provider(
    self,
    username=None,
    user_id=None,
):

    for item in ArticleProc.objects.filter(
        sps_pkg__isnull=False,
        sps_pkg__registered_in_core=False,
    ).iterator():
        try:
            subtask_synchronize_to_pid_provider.apply_async(
                kwargs=dict(
                    user_id=user_id,
                    username=username,
                    item_id=item.id,
                )
            )
        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            UnexpectedEvent.create(
                e=e,
                exc_traceback=exc_traceback,
                detail={
                    "task": "proc.tasks.task_synchronize_to_pid_provider",
                    "user_id": user_id,
                    "username": username,
                },
            )


@celery_app.task(bind=True)
def subtask_synchronize_to_pid_provider(
    self,
    username=None,
    user_id=None,
    item_id=None
):
    user = _get_user(user_id, username)
    item = ArticleProc.objects.get(pk=item_id)
    item.synchronize(user)


@celery_app.task(bind=True)
def task_create_or_update_article_proc_from_uploaded_packages(
    self,
    user_id=None,
    username=None,
):
    """
    Percorre os registros Package e cria ArticleProc

    Parameters
    ----------
    user_id : int
        identificacao do usuário
    username : str
        identificacao do usuário
    """
    try:
        for package in ArticleProc.items_to_ingress():
            # dispara tarefas para criar/atualizar os registros
            # OfficialJournal, JournalProc e Journal
            task_create_or_update_article_proc_from_uploaded_package.apply_async(
                kwargs=dict(
                    user_id=user_id,
                    username=username,
                    package_id=package.id,
                )
            )
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "proc.tasks.task_create_or_update_article_proc_from_uploaded_packages",
                "user_id": user_id,
                "username": username,
            },
        )


@celery_app.task(bind=True)
def task_create_or_update_article_proc_from_uploaded_package(
    self,
    user_id=None,
    username=None,
    package_id=None,
):
    """
    Para um dado registro de upload.models.Package,
    cria ou atualiza os registros de ArticleProc

    Parameters
    ----------
    user_id : int
        identificacao do usuário
    username : str
        identificacao do usuário
    package_id : int
        id de upload.models.Package

    """
    try:
        user = _get_user(user_id, username)
        ArticleProc.ingress(user, package_id)
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "proc.tasks.task_create_or_update_article_proc_from_uploaded_package",
                "user_id": user_id,
                "username": username,
                "package_id": package_id,
            },
        )
