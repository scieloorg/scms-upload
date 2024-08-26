import logging
import sys
from datetime import datetime

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from collection.choices import QA, PUBLIC
from collection.models import Collection, WebSiteConfiguration
from config import celery_app
from migration import controller
from proc.controller import migrate_and_publish_issues, migrate_and_publish_journals
from proc.models import ArticleProc, IssueProc, JournalProc
from publication.api.document import publish_article
from publication.api.journal import publish_journal
from publication.api.issue import publish_issue
from publication.api.publication import get_api_data, get_api
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
        user = _get_user(user_id, username)
        from_datetime = datetime.utcnow()
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
            qa_article_api_data = get_api_data(collection, "article", QA)
            public_article_api_data = get_api_data(collection, "article", PUBLIC)

            for journal_proc in JournalProc.journals_with_modified_articles(collection):
                task_migrate_journal_articles.apply_async(
                    kwargs=dict(
                        user_id=user_id,
                        username=username,
                        journal_proc_id=journal_proc.id,
                        qa_article_api_data=qa_article_api_data,
                        public_article_api_data=public_article_api_data
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
    qa_article_api_data=None,
    public_article_api_data=None
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
                    qa_article_api_data=qa_article_api_data,
                    public_article_api_data=public_article_api_data
                )
            )

        if params:
            logging.info(f"task_migrate_journal_articles - issues 2 : {journal_proc}")
            for issue_proc in IssueProc.objects.filter(**params):
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
                        qa_article_api_data=qa_article_api_data,
                        public_article_api_data=public_article_api_data
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
    qa_article_api_data=None,
    public_article_api_data=None
):
    try:
        user = _get_user(user_id, username)
        issue_proc = IssueProc.objects.get(pk=issue_proc_id)
        logging.info(f"issue_proc_id: {issue_proc.id}")

        for article_proc in ArticleProc.objects.filter(
            issue_proc=issue_proc
        ).iterator():
            task_migrate_and_publish_article.apply_async(
                kwargs=dict(
                    user_id=user_id,
                    username=username,
                    article_proc_id=article_proc.id,
                    force_update=force_update,
                    qa_article_api_data=qa_article_api_data,
                    public_article_api_data=public_article_api_data,
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
    qa_article_api_data=None,
    public_article_api_data=None,
):
    try:
        user = _get_user(user_id, username)
        article_proc = ArticleProc.objects.get(pk=article_proc_id)
        logging.info(f"task_migrate_issue_article: {article_proc}")
        article = article_proc.migrate_article(user, force_update)
        if article:
            article_proc.publish(
                user,
                publish_article,
                website_kind=QA,
                api_data=qa_article_api_data,
                force_update=force_update,
            )
            article_proc.publish(
                user,
                publish_article,
                website_kind=PUBLIC,
                api_data=public_article_api_data,
                force_update=force_update,
            )
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


@celery_app.task(bind=True)
def task_publish_journals(
    self,
    user_id=None,
    username=None,
    collection_acron=None,
    journal_acron=None,
    force_update=False,
):
    try:
        user = _get_user(user_id, username)
        for collection in _get_collections(collection_acron):
            for website_kind in (QA, PUBLIC):
                try:
                    api = get_api(collection, "journal", website_kind)
                except WebSiteConfiguration.DoesNotExist:
                    continue
                api.get_token()
                api_data = api.data

                # FIXME
                params = {}
                params["collection"] = collection
                if journal_acron:
                    params["acron"] = journal_acron

                if not force_update:
                    if website_kind == QA:
                        params["qa_ws_status__in"] = [
                            tracker_choices.PROGRESS_STATUS_TODO,
                            tracker_choices.PROGRESS_STATUS_REPROC,
                        ]
                    elif website_kind == PUBLIC:
                        params["public_ws_status__in"] = [
                            tracker_choices.PROGRESS_STATUS_TODO,
                            tracker_choices.PROGRESS_STATUS_REPROC,
                        ]

                items = JournalProc.objects.filter(**params)

                for journal_proc in items:
                    task_publish_journal.apply_async(
                        kwargs=dict(
                            user_id=user_id,
                            username=username,
                            website_kind=website_kind,
                            journal_proc_id=journal_proc.id,
                            api_data=api_data,
                            force_update=force_update,
                        )
                    )

    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "proc.tasks.task_publish_journals",
                "user_id": user_id,
                "username": username,
                "collection_acron": collection_acron,
                "force_update": force_update,
            },
        )


@celery_app.task(bind=True)
def task_publish_journal(
    self,
    user_id=None,
    username=None,
    website_kind=None,
    journal_proc_id=None,
    api_data=None,
    force_update=None,
):
    try:
        user = _get_user(user_id, username)
        journal_proc = JournalProc.objects.get(pk=journal_proc_id)
        journal_proc.publish(
            user,
            publish_journal,
            website_kind=website_kind,
            api_data=api_data,
            force_update=force_update,
        )

    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "proc.controller.publish_journal",
                "user_id": user.id,
                "username": user.username,
                "website_kind": website_kind,
                "pid": journal_proc.pid,
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


@celery_app.task(bind=True)
def task_publish_issues(
    self,
    user_id=None,
    username=None,
    collection_acron=None,
    journal_acron=None,
    publication_year=None,
    force_update=False,
):
    try:
        for collection in _get_collections(collection_acron):
            for website_kind in (QA, PUBLIC):
                try:
                    api = get_api(collection, "issue", website_kind)
                except WebSiteConfiguration.DoesNotExist:
                    continue
                api.get_token()
                api_data = api.data

                # FIXME
                params = {}
                params["collection"] = collection
                if journal_acron:
                    params["journal_proc__acron"] = journal_acron
                if publication_year:
                    params["issue__publication_year"] = str(publication_year)

                if not force_update:
                    if website_kind == QA:
                        params["qa_ws_status__in"] = [
                            tracker_choices.PROGRESS_STATUS_TODO,
                            tracker_choices.PROGRESS_STATUS_REPROC,
                        ]
                    elif website_kind == PUBLIC:
                        params["public_ws_status__in"] = [
                            tracker_choices.PROGRESS_STATUS_TODO,
                            tracker_choices.PROGRESS_STATUS_REPROC,
                        ]

                items = IssueProc.objects.filter(**params)

                for issue_proc in items:
                    task_publish_issue.apply_async(
                        kwargs=dict(
                            user_id=user_id,
                            username=username,
                            website_kind=website_kind,
                            issue_proc_id=issue_proc.id,
                            api_data=api_data,
                            force_update=force_update,
                        )
                    )

    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "proc.tasks.task_publish_issues",
                "user_id": user_id,
                "username": username,
                "collection_acron": collection_acron,
                "journal_acron": journal_acron,
                "publication_year": publication_year,
                "force_update": force_update,
            },
        )


@celery_app.task(bind=True)
def task_publish_issue(
    self,
    user_id=None,
    username=None,
    website_kind=None,
    issue_proc_id=None,
    api_data=None,
    force_update=None
):
    try:
        user = _get_user(user_id, username)
        issue_proc = IssueProc.objects.get(pk=issue_proc_id)
        issue_proc.publish(
            user,
            publish_issue,
            website_kind=website_kind,
            api_data=api_data,
            force_update=force_update,
        )

    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "proc.controller.publish_issue",
                "user_id": user.id,
                "username": user.username,
                "website_kind": website_kind,
                "pid": issue_proc.pid,
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

        logging.info(params)
        article_api_data = None
        for journal_proc in JournalProc.objects.filter(**params):

            qa_article_api_data = article_api_data or get_api_data(
                journal_proc.collection, "article", QA
            )
            public_article_api_data = article_api_data or get_api_data(
                journal_proc.collection, "article", PUBLIC
            )
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
                    qa_article_api_data=qa_article_api_data,
                    public_article_api_data=public_article_api_data,                    
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


@celery_app.task(bind=True)
def task_publish_articles(
    self,
    user_id=None,
    username=None,
    collection_acron=None,
    journal_acron=None,
    publication_year=None,
    force_update=False,
):
    try:
        for collection in _get_collections(collection_acron):
            for website_kind in (QA, PUBLIC):
                try:
                    api = get_api(collection, "article", website_kind)
                except WebSiteConfiguration.DoesNotExist:
                    continue
                api.get_token()
                api_data = api.data

                # FIXME
                params = {}
                params["collection"] = collection
                if journal_acron:
                    params["issue_proc__journal_proc__acron"] = journal_acron
                if publication_year:
                    params["issue_proc__issue__publication_year"] = str(publication_year)

                if not force_update:
                    if website_kind == QA:
                        params["qa_ws_status__in"] = [
                            tracker_choices.PROGRESS_STATUS_TODO,
                            tracker_choices.PROGRESS_STATUS_REPROC,
                        ]
                    elif website_kind == PUBLIC:
                        params["public_ws_status__in"] = [
                            tracker_choices.PROGRESS_STATUS_TODO,
                            tracker_choices.PROGRESS_STATUS_REPROC,
                        ]

                items = ArticleProc.objects.filter(**params)

                for article_proc in items:
                    task_publish_article.apply_async(
                        kwargs=dict(
                            user_id=user_id,
                            username=username,
                            website_kind=website_kind,
                            article_proc_id=article_proc.id,
                            api_data=api_data,
                            force_update=force_update,
                        )
                    )

    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "proc.tasks.task_publish_articles",
                "user_id": user_id,
                "username": username,
                "collection_acron": collection_acron,
                "journal_acron": journal_acron,
                "publication_year": publication_year,
                "force_update": force_update,
            },
        )


@celery_app.task(bind=True)
def task_publish_article(
    self,
    user_id=None,
    username=None,
    website_kind=None,
    article_proc_id=None,
    api_data=None,
    force_update=None,
):
    try:
        user = _get_user(user_id, username)
        article_proc = ArticleProc.objects.get(pk=article_proc_id)
        article_proc.publish(
            user,
            publish_article,
            website_kind=website_kind,
            api_data=api_data,
            force_update=force_update,
        )

    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "proc.controller.publish_article",
                "user_id": user_id,
                "username": username,
                "website_kind": website_kind,
                "pid": article_proc.pid,
            },
        )
