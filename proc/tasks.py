import logging
import sys

from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from collection.choices import QA, PUBLIC
from collection.models import Collection, WebSiteConfiguration
from config import celery_app
from migration import controller
from proc.controller import (
    create_or_update_migrated_issue,
    create_or_update_migrated_journal,
    migrate_journal,
    migrate_issue,
    publish_journals,
    create_collection_procs_from_pid_list,
)
from proc.models import ArticleProc, IssueProc, JournalProc
from publication.api.document import publish_article
from publication.api.journal import publish_journal
from publication.api.issue import publish_issue
from publication.api.publication import get_api_data, get_api
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
    journal_acron=None,
    publication_year=None,
    issue_folder=None,
    force_update=False,
    force_import_acron_id_file=False,
    force_migrate_document_records=False,
):
    try:
        user = _get_user(user_id, username)
        journal_filter = {}
        if journal_acron:
            journal_filter["acron"] = journal_acron

        issue_filter = {}
        if journal_acron:
            issue_filter["journal_proc__acron"] = journal_acron
        if issue_folder:
            issue_filter["issue_folder"] = issue_folder
        if publication_year:
            issue_filter["issue__publication_year"] = publication_year

        logging.info(f"journal_filter: {journal_filter}")
        logging.info(f"issue_filter: {issue_filter}")

        for collection in _get_collections(collection_acron):
            # obtém os dados do site clássico
            classic_website = controller.get_classic_website(collection.acron)

            # import title.id, cria MigratedJournal
            create_or_update_migrated_journal(
                user,
                collection,
                classic_website,
                force_update,
            )
            # import issue.id, cria MigratedIssue
            create_or_update_migrated_issue(
                user,
                collection,
                classic_website,
                force_update,
            )

            items = JournalProc.items_to_process(collection, "journal", journal_filter, force_update)
            logging.info(f"journals to process: {items.count()}")
            for journal_proc in items:
                migrate_journal(
                    user,
                    journal_proc,
                    issue_filter,
                    force_update,
                    force_import_acron_id_file=force_import_acron_id_file,
                    force_migrate_document_records=force_migrate_document_records,
                    migrate_issues=False,
                    migrate_articles=False,
                )

            items = IssueProc.items_to_process(
                collection,
                "issue",
                issue_filter,
                force_update,
            )
            logging.info(f"issues to process: {items.count()}")
            for issue_proc in items:
                migrate_issue(
                    user,
                    issue_proc,
                    force_update,
                    force_migrate_document_records=force_migrate_document_records,
                    migrate_articles=False,
                )

            article_filter = {}
            if issue_filter:
                article_filter = {f"issue_proc__{k}": v for k, v in issue_filter.items()}

            logging.info(f"article_filter: {article_filter}")
            items = ArticleProc.items_to_process(collection, "article", article_filter, force_update)
            logging.info(f"articles to process: {items.count()}")
            for article_proc in items:
                article_proc.migrate_article(user, force_update)

            for website_kind in (QA, PUBLIC):
                publish_journals(
                    user,
                    website_kind,
                    collection,
                    journal_filter,
                    issue_filter,
                    force_update,
                    run_publish_issues=False,
                    run_publish_articles=False,
                    task_publish_article=task_publish_article,
                )

                items = IssueProc.items_to_publish(
                    website_kind=website_kind,
                    content_type="issue",
                    collection=collection,
                    force_update=force_update,
                    params=issue_filter,
                )
                logging.info(f"publish_issues: {issue_filter} {items.count()}")
                api_data = get_api_data(collection, "issue", website_kind)
                for issue_proc in items:
                    published = issue_proc.publish(
                        user,
                        publish_issue,
                        website_kind=website_kind,
                        api_data=api_data,
                        force_update=force_update,
                    )

                items = ArticleProc.items_to_publish(
                    website_kind=website_kind,
                    content_type="article",
                    collection=collection,
                    force_update=force_update,
                    params=article_filter,
                )
                api_data = get_api_data(collection, "article", website_kind)
                logging.info(f"publish_articles: {article_filter} {items.count()}")
                for article_proc in items:
                    task_publish_article.apply_async(
                        kwargs=dict(
                            user_id=user.id,
                            username=user.username,
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
                "task": "proc.tasks.task_migrate_and_publish",
                "user_id": user_id,
                "username": username,
                "collection_acron": collection_acron,
                "journal_acron": journal_acron,
                "publication_year": publication_year,
                "issue_folder": issue_folder,
                "force_update": force_update,
                "force_import_acron_id_file": force_import_acron_id_file,
                "force_migrate_document_records": force_migrate_document_records,
            },
        )


############################################
@celery_app.task(bind=True)
def task_migrate_and_publish_journals(
    self,
    user_id=None,
    username=None,
    collection_acron=None,
    journal_acron=None,
    force_update=False,
    force_import_acron_id_file=False,
    force_migrate_document_records=False,
):
    try:
        user = _get_user(user_id, username)
        journal_filter = {}
        if journal_acron:
            journal_filter["acron"] = journal_acron

        for collection in _get_collections(collection_acron):
            # obtém os dados do site clássico
            classic_website = controller.get_classic_website(collection.acron)

            create_or_update_migrated_journal(
                user,
                collection,
                classic_website,
                force_update,
            )

            qa_api_data = get_api_data(collection, "journal", "QA")
            public_api_data = get_api_data(collection, "journal", "PUBLIC")

            for journal_proc in JournalProc.objects.filter(
                collection=collection, **journal_filter
            ):
                try:
                    # cria ou atualiza Journal e atualiza journal_proc
                    migrate_journal(
                        user,
                        journal_proc,
                        issue_filter=None,
                        force_update=force_update,
                        force_import_acron_id_file=force_import_acron_id_file,
                        force_migrate_document_records=force_migrate_document_records,
                        migrate_issues=False,
                        migrate_articles=False,
                    )
                    task_publish_journal.apply_async(
                        kwargs=dict(
                            user_id=user_id,
                            username=username,
                            website_kind="QA",
                            journal_proc_id=journal_proc.id,
                            api_data=qa_api_data,
                            force_update=force_update,
                        )
                    )
                    task_publish_journal.apply_async(
                        kwargs=dict(
                            user_id=user_id,
                            username=username,
                            website_kind="PUBLIC",
                            journal_proc_id=journal_proc.id,
                            api_data=public_api_data,
                            force_update=force_update,
                        )
                    )

                except Exception as e:
                    exc_type, exc_value, exc_traceback = sys.exc_info()
                    UnexpectedEvent.create(
                        e=e,
                        exc_traceback=exc_traceback,
                        detail={
                            "task": "proc.tasks.migrate_and_publish_journals",
                            "user_id": user.id,
                            "username": user.username,
                            "collection": collection.acron,
                            "journal_acron": journal_acron,
                            "pid": journal_proc.pid,
                            "force_update": force_update,
                        },
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
                "journal_acron": journal_acron,
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
        params = {}
        if journal_acron:
            params["acron"] = journal_acron

        logging.info(f"task_publish_journals {params}")
        for collection in _get_collections(collection_acron):

            for website_kind in (QA, PUBLIC):

                try:
                    api = get_api(collection, "journal", website_kind)
                except WebSiteConfiguration.DoesNotExist:
                    continue
                api.get_token()
                api_data = api.data

                items = JournalProc.items_to_publish(
                    website_kind=website_kind,
                    content_type="journal",
                    collection=collection,
                    force_update=force_update,
                    params=params,
                )
                logging.info(f"publish_journals {items.count()}")
                for journal_proc in items:
                    logging.info(f"{website_kind} {journal_proc}")
                    try:
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
                                "task": "proc.task.publish_journals",
                                "user_id": user.id,
                                "username": user.username,
                                "collection": collection.acron,
                                "pid": journal_proc.pid,
                                "force_update": force_update,
                            },
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
                "journal_acron": journal_acron,
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
                "task": "proc.tasks.publish_journal",
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
    journal_acron=None,
    publication_year=None,
    issue_folder=None,
    force_update=False,
    force_migrate_document_records=False
):
    try:
        user = _get_user(user_id, username)
        params = {}
        if journal_acron:
            params["journal_proc__acron"] = journal_acron
        if issue_folder:
            params["issue_folder"] = issue_folder
        if publication_year:
            params["issue__publication_year"] = publication_year

        logging.info(params)
        for collection in _get_collections(collection_acron):
            # obtém os dados do site clássico
            classic_website = controller.get_classic_website(collection.acron)

            create_or_update_migrated_issue(
                user,
                collection,
                classic_website,
                force_update,
            )

            qa_api_data = get_api_data(collection, "issue", "QA")
            public_api_data = get_api_data(collection, "issue", "PUBLIC")
            items = IssueProc.items_to_process(collection, "issue", params, force_update)
            logging.info(items.count())
            for issue_proc in items:
                try:
                    migrate_issue(
                        user,
                        issue_proc,
                        force_update,
                        force_migrate_document_records=force_migrate_document_records,
                        migrate_articles=False,
                    )

                    task_publish_issue.apply_async(
                        kwargs=dict(
                            user_id=user_id,
                            username=username,
                            website_kind="QA",
                            issue_proc_id=issue_proc.id,
                            api_data=qa_api_data,
                            force_update=force_update,
                        )
                    )
                    task_publish_issue.apply_async(
                        kwargs=dict(
                            user_id=user_id,
                            username=username,
                            website_kind="PUBLIC",
                            issue_proc_id=issue_proc.id,
                            api_data=public_api_data,
                            force_update=force_update,
                        )
                    )

                except Exception as e:
                    exc_type, exc_value, exc_traceback = sys.exc_info()
                    UnexpectedEvent.create(
                        e=e,
                        exc_traceback=exc_traceback,
                        detail={
                            "task": "proc.task.migrate_and_publish_issues",
                            "user_id": user.id,
                            "username": user.username,
                            "collection": collection.acron,
                            "pid": issue_proc.pid,
                            "force_update": force_update,
                            "force_migrate_document_records": force_migrate_document_records,
                        },
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
                "journal_acron": journal_acron,
                "publication_year": publication_year,
                "issue_folder": issue_folder,
                "force_update": force_update,
                "force_migrate_document_records": force_migrate_document_records,
            },
        )


@celery_app.task(bind=True)
def task_publish_issues(
    self,
    user_id=None,
    username=None,
    collection_acron=None,
    journal_acron=None,
    issue_folder=None,
    publication_year=None,
    force_update=False,
):
    try:
        params = {}
        if journal_acron:
            params["journal_proc__acron"] = journal_acron
        if issue_folder:
            params["issue_folder"] = str(issue_folder)
        if publication_year:
            params["issue__publication_year"] = str(publication_year)
        for collection in _get_collections(collection_acron):
            for website_kind in (QA, PUBLIC):

                try:
                    api = get_api(collection, "issue", website_kind)
                except WebSiteConfiguration.DoesNotExist:
                    continue
                api.get_token()
                api_data = api.data

                for issue_proc in IssueProc.items_to_publish(
                    website_kind=website_kind,
                    content_type="issue",
                    collection=collection,
                    force_update=force_update,
                    params=params,
                ):
                    try:
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
                                "task": "proc.tasks.publish_issues",
                                "user_id": user_id,
                                "username": username,
                                "collection": collection.acron,
                                "pid": issue_proc.pid,
                                "force_update": force_update,
                            },
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
                "issue_folder": issue_folder,
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
    force_update=None,
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
                "task": "proc.tasks.publish_issue",
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
):
    try:
        user = _get_user(user_id, username)

        params = {}
        if journal_acron:
            params["issue_proc__journal_proc__acron"] = journal_acron
        if issue_folder:
            params["issue_proc__issue_folder"] = issue_folder
        if publication_year:
            params["issue_proc__issue__publication_year"] = publication_year

        logging.info(f"task_migrate_and_publish_articles: {params}")

        for collection in _get_collections(collection_acron):
            qa_api_data = get_api_data(collection, "article", QA)
            public_api_data = get_api_data(collection, "article", PUBLIC)

            items = ArticleProc.items_to_process(collection, "article", params, force_update)
            logging.info(f"articles to process: {items.count()}")
            logging.info(f"article_filter: {params}")
            logging.info(list(ArticleProc.items_to_process_info(items)))

            for article_proc in items:
                article = article_proc.migrate_article(user, force_update)
                if not article:
                    continue

                task_publish_article.apply_async(
                        kwargs=dict(
                            user_id=user_id,
                            username=username,
                            website_kind="QA",
                            article_proc_id=article_proc.id,
                            api_data=qa_api_data,
                            force_update=force_update,
                        )
                    )
                task_publish_article.apply_async(
                    kwargs=dict(
                        user_id=user_id,
                        username=username,
                        website_kind="PUBLIC",
                        article_proc_id=article_proc.id,
                        api_data=public_api_data,
                        force_update=force_update,
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
                "journal_acron": journal_acron,
                "publication_year": publication_year,
                "issue_folder": issue_folder,
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
    issue_folder=None,
    publication_year=None,
    force_update=False,
):
    try:
        params = {}

        if journal_acron:
            params["issue_proc__journal_proc__acron"] = journal_acron
        if issue_folder:
            params["issue_proc__issue_folder"] = issue_folder
        if publication_year:
            params["issue_proc__issue__publication_year"] = publication_year

        for collection in _get_collections(collection_acron):
            for website_kind in (QA, PUBLIC):
                try:
                    api = get_api(collection, "article", website_kind)
                except WebSiteConfiguration.DoesNotExist:
                    continue
                api.get_token()
                api_data = api.data

                # for article_proc in ArticleProc.objects.filter(collection=collection, **params):
                for article_proc in ArticleProc.items_to_publish(
                    website_kind=website_kind,
                    content_type="article",
                    collection=collection,
                    force_update=force_update,
                    params=params,
                ):
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
                "issue_folder": issue_folder,
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
                "task": "proc.task.publish_article",
                "user_id": user_id,
                "username": username,
                "website_kind": website_kind,
                "pid": article_proc.pid,
            },
        )


@celery_app.task(bind=True)
def task_create_procs_from_pid_list(self, username, user_id=None, collection_acron=None, force_update=None):
    user = _get_user(user_id=None, username=username)
    try:
        for collection in _get_collections(collection_acron):
            task_create_collection_procs_from_pid_list.apply_async(
                kwargs=dict(
                    username=username,
                    collection_acron=collection.acron,
                    force_update=force_update,
                )
            )
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "function": "proc.tasks.task_create_procs_from_pid_list",
                "collection_acron": collection_acron,
            },
        )


@celery_app.task(bind=True)
def task_create_collection_procs_from_pid_list(self, username, collection_acron, force_update):
    user = _get_user(user_id=None, username=username)
    try:
        classic_website_config = controller.get_classic_website_config(collection_acron)
        collection = classic_website_config.collection
        create_collection_procs_from_pid_list(
            user,
            classic_website_config.collection,
            classic_website_config.pid_list_path,
            force_update,
        )
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "function": "proc.tasks.task_create_collection_procs_from_pid_list",
                "collection_acron": collection_acron,
            },
        )
