import logging
import sys
from datetime import datetime

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from collection.choices import QA
from collection.models import Collection, WebSiteConfiguration
from config import celery_app
from migration import controller
from migration.models import JournalAcronIdFile
from proc.controller import migrate_and_publish_issues, migrate_and_publish_journals
from proc.models import ArticleProc, IssueProc, JournalProc
from publication.api.document import publish_article
from publication.api.issue import publish_issue
from publication.api.journal import publish_journal
from publication.api.publication import PublicationAPI
from tracker import choices as tracker_choices
from tracker.models import UnexpectedEvent

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
def task_migrate_and_publish(
    self,
    user_id=None,
    username=None,
    collection_acron=None,
    publication_year=None,
    force_update=False,
):
    try:
        from_datetime = datetime.utcnow()
        user = _get_user(user_id, username)

        for collection in _get_collections(collection_acron):
            # obtém os dados do site clássico
            classic_website = controller.get_classic_website(collection.acron)

            # migra title
            migrate_and_publish_journals(
                user,
                collection,
                classic_website,
                force_update,
                import_acron_id_file=True,
            )

            # migra issues
            migrate_and_publish_issues(
                user,
                collection,
                classic_website,
                force_update,
                get_files_from_classic_website=False,
            )

            # migra os documentos
            for journal_proc in JournalProc.journals_with_modified_articles(collection):
                task_migrate_journal_articles.apply_async(
                    kwargs=dict(
                        user_id=user_id,
                        username=username,
                        journal_proc_id=journal_proc.id,
                    )
                )

    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "proc.tasks.task_migrate_and_publish",
                "user_id": user_id,
                "username": username,
                "collection_acron": collection_acron,
                "force_update": force_update,
            },
        )


@celery_app.task(bind=True)
def task_migrate_journal_articles(
    self,
    user_id=None,
    username=None,
    journal_proc_id=None,
    publication_year=None,
    issue_folder=None,
    force_update=None,
):
    """
    Migra todos ou uma seleção de artigos de um dado journal
    Tarefa é chamada em dois casos:
    a) por task_migrate_and_publish
    b) por task_migrate_and_publish_articles

    Parameters
    ----------
    user_id : int
        identificacao do usuário
    username : str
        identificacao do usuário
    journal_proc_id : str
        journal_proc_id
    force_update : bool
        atualiza mesmo se já existe
    """
    try:
        params = {}
        user = _get_user(user_id, username)
        journal_proc = JournalProc.objects.get(pk=journal_proc_id)
        logging.info(f"task_migrate_journal_articles: {journal_proc}")

        # obtém os issues que tiveram atualizações ou
        # obtém todos os issues se force_update=True
        issue_procs = journal_proc.issues_with_modified_articles()

        if issue_folder or publication_year:
            if issue_folder:
                params["issue_folder"] = issue_folder
            if publication_year:
                params["publication_year"] = publication_year
            if issue_procs.filter(**params).exist():
                params = None

        logging.info(f"task_migrate_journal_articles - issues 1 : {journal_proc}")
        for issue_proc in issue_procs:

            logging.info(f"task_migrate_journal_articles - issues 1 : {issue_proc}")

            issue_proc.migrate_document_records(
                user,
                force_update=force_update,
            )

            issue_proc.get_files_from_classic_website(
                user,
                force_update,
                f_get_files_from_classic_website=controller.import_one_issue_files,
            )

            task_migrate_issue_articles.apply_async(
                kwargs=dict(
                    user_id=user_id,
                    username=username,
                    issue_proc_id=issue_proc.id,
                    force_update=force_update,
                )
            )

        if params:
            logging.info(f"task_migrate_journal_articles - issues 2 : {journal_proc}")
            for issue_proc in IssueProc.filter(**params):
                logging.info(f"task_migrate_journal_articles - issues 2 : {issue_proc}")

                issue_proc.get_files_from_classic_website(
                    user,
                    force_update,
                    f_get_files_from_classic_website=controller.import_one_issue_files,
                )

                task_migrate_issue_articles.apply_async(
                    kwargs=dict(
                        user_id=user_id,
                        username=username,
                        issue_proc_id=issue_proc.id,
                        force_update=force_update,
                    )
                )

    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "proc.tasks.task_migrate_journal_articles",
                "user_id": user_id,
                "username": username,
                "journal_proc_id": journal_proc_id,
                "force_update": force_update,
            },
        )


@celery_app.task(bind=True)
def task_migrate_issue_articles(
    self,
    user_id=None,
    username=None,
    issue_proc_id=None,
    force_update=None,
):
    try:
        user = _get_user(user_id, username)
        issue_proc = IssueProc.objects.get(pk=issue_proc_id)
        logging.info(f"issue_proc_id: {issue_proc.id}")

        for article_proc in ArticleProc.objects.filter(
            issue_proc=issue_proc
        ).iterator():
            logging.info(f"task_migrate_issue_articles: {article_proc}")
            task_migrate_and_publish_article.apply_async(
                kwargs=dict(
                    user_id=user_id,
                    username=username,
                    article_proc_id=article_proc.id,
                    force_update=force_update,
                )
            )
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "proc.tasks.task_migrate_issue_articles",
                "user_id": user_id,
                "username": username,
                "issue_proc_id": issue_proc_id,
                "force_update": force_update,
            },
        )


@celery_app.task(bind=True)
def task_migrate_and_publish_article(
    self,
    user_id=None,
    username=None,
    article_proc_id=None,
    force_update=None,
):
    try:
        user = _get_user(user_id, username)
        logging.info(f"article_proc_id: {article_proc_id}")
        article_proc = ArticleProc.objects.get(pk=article_proc_id)
        article = article_proc.migrate_article(user, force_update)
        if article:
            article_proc.publish(user, publish_article, force_update=force_update)
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "proc.tasks.task_migrate_and_publish_article",
                "item_id": article_proc_id,
                "user_id": user_id,
                "username": username,
                "force_update": force_update,
            },
        )


############################################
@celery_app.task(bind=True)
def task_migrate_and_publish_journals(
    self,
    user_id=None,
    username=None,
    collection_acron=None,
    force_update=False,
    force_import=None,
):
    try:
        user = _get_user(user_id, username)

        for collection in _get_collections(collection_acron):
            # obtém os dados do site clássico
            classic_website = controller.get_classic_website(collection.acron)

            # migra title
            migrate_and_publish_journals(
                user, collection, classic_website, force_update, force_import
            )

    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "proc.tasks.task_migrate_and_publish_journals",
                "user_id": user_id,
                "username": username,
                "collection_acron": collection_acron,
                "force_update": force_update,
            },
        )


############################################
@celery_app.task(bind=True)
def task_migrate_and_publish_issues(
    self,
    user_id=None,
    username=None,
    collection_acron=None,
    force_update=False,
    force_import=None,
):
    try:
        user = _get_user(user_id, username)

        for collection in _get_collections(collection_acron):
            # obtém os dados do site clássico
            classic_website = controller.get_classic_website(collection.acron)

            # migra title
            migrate_and_publish_issues(
                user, collection, classic_website, force_update, force_import
            )

    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "proc.tasks.task_migrate_and_publish_issues",
                "user_id": user_id,
                "username": username,
                "collection_acron": collection_acron,
                "force_update": force_update,
            },
        )


############################################
@celery_app.task(bind=True)
def task_migrate_and_publish_articles(
    self,
    user_id=None,
    username=None,
    collection_acron=None,
    journal_acron=None,
    publication_year=None,
    issue_folder=None,
    force_update=False,
    force_import=None,
):
    try:
        user = _get_user(user_id, username)
        params = {}
        if collection_acron:
            params["collection__acron"] = collection_acron
        if journal_acron:
            params["journal__acron"] = journal_acron

        for journal_proc in JournalProc.objects.filter(**params):
            # como é custoso obter os registros de acron,
            # somente se force_import é True, reexecuta a leitura de acron.id
            controller.register_acron_id_file_content(
                user,
                journal_proc,
                force_update=force_import,
            )
            task_migrate_journal_articles.apply_async(
                kwargs=dict(
                    user_id=user_id,
                    username=username,
                    journal_proc_id=journal_proc.id,
                    publication_year=publication_year,
                    issue_folder=issue_folder,
                    force_update=force_update or force_import,
                    # from_datetime=from_datetime,
                )
            )

    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "proc.tasks.task_migrate_and_publish_articles",
                "user_id": user_id,
                "username": username,
                "collection_acron": collection_acron,
                "force_update": force_update,
            },
        )
