import logging
import sys

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from article.models import Article
from collection.choices import QA, PUBLIC
from collection.models import Collection, WebSiteConfiguration
from config import celery_app
from migration import controller
from proc.article_publication_controller import (
    log_event,
    schedule_article_publication
)
from proc.controller import (
    create_or_update_migrated_issue,
    create_or_update_migrated_journal,
    migrate_journal,
    migrate_issue,
    publish_journals,
    create_collection_procs_from_pid_list,
    create_or_update_journal_acron_id_file,
    get_files_from_classic_website,
    migrate_document_records,
    fetch_and_create_journal,
)
from proc.models import ArticleProc, IssueProc, JournalProc
from publication.api.document import publish_article
from publication.api.journal import publish_journal
from publication.api.issue import publish_issue
from publication.api.publication import get_api_data, get_api
from publication.models import ArticleAvailability
from tracker.models import UnexpectedEvent, TaskTracker
from tracker import choices as tracker_choices


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
    logging.info("task_migrate_and_publish is discontinued")
    logging.info("Use task_migrate_and_publish_journals")
    logging.info("Use task_migrate_and_publish_issues")
    logging.info("Use task_migrate_and_publish_articles")


############################################
@celery_app.task(bind=True)
def task_migrate_and_publish_journals(
    self,
    user_id=None,
    username=None,
    collection_acron=None,
    journal_acron=None,
    force_update=False,
    status=None,
    valid_status=None,
    force_import_acron_id_file=False,
):
    try:
        user = _get_user(user_id, username)
        
        task_params = {
            "task": "proc.tasks.task_migrate_and_publish_journals",
            "user_id": user_id,
            "username": username,
            "collection_acron": collection_acron,
            "journal_acron": journal_acron,
            "force_update": force_update,
            "status": status,
            "force_import_acron_id_file": force_import_acron_id_file,
        }
        task_tracker = TaskTracker.create(
            name="proc.tasks.task_migrate_and_publish_journals",
            detail=task_params,
        )
        journal_filter = {}
        if journal_acron:
            journal_filter["acron"] = journal_acron
        status = tracker_choices.get_valid_status(status, force_update)
        query_by_status = (
            Q(migration_status__in=status)
            | Q(qa_ws_status__in=status)
            | Q(public_ws_status__in=status)
        )
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
                query_by_status, collection=collection, **journal_filter
            ):
                # cria ou atualiza Journal e atualiza journal_proc
                migrate_journal(user, journal_proc, force_update)
                try:
                    # atualiza Journal e atualiza journal_proc com dados do Core
                    event = None
                    event = journal_proc.start(user, "fetch_and_create_journal")
                    fetch_and_create_journal(
                        user,
                        collection_acron=collection.acron,
                        issn_electronic=journal_proc.issn_electronic,
                        issn_print=journal_proc.issn_print,
                        force_update=force_update,
                    )
                    event.finish(user, completed=True, detail=journal_proc.completeness)
                except Exception as e:
                    exc_type, exc_value, exc_traceback = sys.exc_info()

                    if event:
                        event.finish(
                            user,
                            completed=False,
                            exception=e,
                            exc_traceback=exc_traceback,
                        )
                    else:
                        UnexpectedEvent.create(
                            e=e,
                            exc_traceback=exc_traceback,
                            detail=task_params,
                        )

                if not qa_api_data.get("error"):
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
                if not public_api_data.get("error"):
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
        task_tracker.finish(completed=True)
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        task_tracker.finish(completed=False, exception=e, exc_traceback=exc_traceback)


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

        task_params = {
            "task": "proc.tasks.task_publish_journals",
            "user_id": user_id,
            "username": username,
            "collection_acron": collection_acron,
            "journal_acron": journal_acron,
            "force_update": force_update,
        }

        task_tracker = TaskTracker.create(
            name="proc.tasks.task_publish_journals",
            detail=task_params,
        )
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
        task_tracker.finish(completed=True)
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        task_tracker.finish(
            completed=False,
            exception=e,
            exc_traceback=exc_traceback,
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
        event = journal_proc.start(user, "proc.tasks.publish_journal")
        journal_proc.publish(
            user,
            publish_journal,
            content_type="journal",
            website_kind=website_kind,
            api_data=api_data,
            force_update=force_update,
        )

    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        try:
            event.finish(
                user, completed=False, exception=e, exc_traceback=exc_traceback)
        except Exception as ignored_exception:
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
    status=None,
    valid_status=None,
    force_update=False,
    force_migrate_document_records=False,
):
    try:
        user = _get_user(user_id, username)
        task_params = {
            "task": "proc.tasks.task_migrate_and_publish_issues",
            "user_id": user_id,
            "username": username,
            "collection_acron": collection_acron,
            "journal_acron": journal_acron,
            "publication_year": publication_year,
            "status": status,
            "force_update": force_update,
            "issue_folder": issue_folder,
            "force_migrate_document_records": force_migrate_document_records,
        }
        task_tracker = TaskTracker.create(
            name="proc.tasks.task_migrate_and_publish_issues",
            detail=task_params,
        )
        params = {}
        if journal_acron:
            params["journal_proc__acron"] = journal_acron
        if issue_folder:
            params["issue_folder"] = issue_folder
        if publication_year:
            params["issue__publication_year"] = publication_year

        status = tracker_choices.get_valid_status(status, force_update)
        query_by_status = (
            Q(migration_status__in=status)
            | Q(docs_status__in=status)
            | Q(files_status__in=status)
            | Q(qa_ws_status__in=status)
            | Q(public_ws_status__in=status)
        )

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
            # items = IssueProc.items_to_process(collection, "issue", params, force_update)

            items = IssueProc.objects.filter(
                query_by_status,
                collection=collection,
                **params,
            )
            logging.info(items.count())
            for issue_proc in items:
                migrate_issue(user, issue_proc, force_update)

                if not qa_api_data.get("error"):
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
                if not public_api_data.get("error"):
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
        task_tracker.finish(completed=True)
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        task_tracker.finish(
            completed=False,
            exception=e,
            exc_traceback=exc_traceback,
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
        task_tracker.finish(
            completed=False,
            exception=e,
            exc_traceback=exc_traceback,
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
        event = issue_proc.start(user, "proc.tasks.publish_issue")
        issue_proc.publish(
            user,
            publish_issue,
            content_type="issue",
            website_kind=website_kind,
            api_data=api_data,
            force_update=force_update,
        )

    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        try:
            event.finish(
                user=user,
                completed=False,
                exception=e,
                exc_traceback=exc_traceback,
            )
        except Exception as ignored_exception:
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
    status=None,
    valid_status=None,
    force_update=False,
    force_import_acron_id_file=False,
    force_migrate_document_records=False,
    force_migrate_document_files=False,
    skip_migrate_pending_document_records=False,
):
    # Lista plana para armazenar todos os eventos
    execution_log = []
    
    # Estatísticas separadas
    statistics = {
        "total_collections": 0,
        "total_articles_processed": 0,
        "total_articles_migrated": 0,
        "total_articles_to_publish": 0,
        "articles_published_qa": 0,
        "articles_published_public": 0,
    }
    
    try:
        user = _get_user(user_id, username)
        task_params = {
            "task": "proc.tasks.task_migrate_and_publish_articles",
            "user_id": user_id,
            "username": username,
            "collection_acron": collection_acron,
            "journal_acron": journal_acron,
            "publication_year": publication_year,
            "issue_folder": issue_folder,
            "status": status,
            "force_update": force_update,
            "force_import_acron_id_file": force_import_acron_id_file,
            "force_migrate_document_records": force_migrate_document_records,
            "force_migrate_document_files": force_migrate_document_files,
            "skip_migrate_pending_document_records": skip_migrate_pending_document_records
        }
        task_tracker = TaskTracker.create(
            name="proc.tasks.task_migrate_and_publish_articles",
            detail=task_params,
        )
        
        log_event(execution_log, "info", "initialization", "Task initialized with parameters", params=task_params)
        
        status = tracker_choices.get_valid_status(status, force_update)
        query_by_status = (
            Q(migration_status__in=status)
            | Q(xml_status__in=status)
            | Q(sps_pkg_status__in=status)
        )

        journal_filter = {}
        if journal_acron:
            journal_filter["acron"] = journal_acron

        params = {}
        if journal_acron:
            params["issue_proc__journal_proc__acron"] = journal_acron
        if issue_folder:
            params["issue_proc__issue_folder"] = issue_folder
        if publication_year:
            params["issue_proc__issue__publication_year"] = publication_year

        collections = list(_get_collections(collection_acron))
        statistics["total_collections"] = len(collections)
        
        for collection in collections:
            collection_name = collection.acron if hasattr(collection, 'acron') else str(collection)
            
            # Step 1: Create or update journal acron id file
            log_event(
                execution_log,
                "info",
                "create_journal_acron_id_file",
                "Starting journal acron id file creation/update",
                collection=collection_name
            )
            
            create_or_update_journal_acron_id_file(
                user,
                collection,
                journal_filter,
                force_update=force_import_acron_id_file,
            )

            # Step 2: Migrate document records
            log_event(
                execution_log,
                "info",
                "migrate_document_records",
                "Starting document records migration",
                collection=collection_name
            )
            
            migrate_document_records(
                user,
                collection_acron=collection_acron,
                journal_acron=journal_acron,
                issue_folder=issue_folder,
                publication_year=publication_year,
                status=status,
                force_update=force_migrate_document_records,
                skip_migrate_pending_document_records=skip_migrate_pending_document_records,
            )

            # Step 3: Get files from classic website
            log_event(
                execution_log,
                "info",
                "get_files_from_classic_website",
                "Starting file retrieval from classic website",
                collection=collection_name
            )
            
            get_files_from_classic_website(
                user,
                collection_acron=collection_acron,
                journal_acron=journal_acron,
                issue_folder=issue_folder,
                publication_year=publication_year,
                status=status,
                force_update=force_migrate_document_files,
            )

            qa_api_data = get_api_data(collection, "article", QA)
            public_api_data = get_api_data(collection, "article", PUBLIC)
            
            # Log API data status
            if qa_api_data.get("error"):
                log_event(
                    execution_log,
                    "error",
                    "api_error",
                    f"QA API error for collection {collection_name}",
                    api="QA",
                    collection=collection_name,
                    error=qa_api_data.get("error")
                )
            
            if public_api_data.get("error"):
                log_event(
                    execution_log,
                    "error",
                    "api_error",
                    f"PUBLIC API error for collection {collection_name}",
                    api="PUBLIC",
                    collection=collection_name,
                    error=public_api_data.get("error")
                )

            # Process articles for migration
            items = ArticleProc.objects.filter(
                query_by_status, collection=collection, **params
            )
            
            articles_count = items.count()
            statistics["total_articles_processed"] += articles_count
            
            log_event(
                execution_log,
                "info",
                "articles_migration",
                f"Found {articles_count} articles to process for migration",
                collection=collection_name,
                count=articles_count
            )

            force_update = (
                force_update
                or force_migrate_document_records
                or force_migrate_document_files
                or force_import_acron_id_file
            )
            
            articles_migrated = 0
            qa_published = 0
            public_published = 0
            
            for article_proc in items:
                article = article_proc.migrate_article(user, force_update)
                if not article:
                    log_event(
                        execution_log,
                        "warning",
                        "migration_failed",
                        f"Failed to migrate article {article_proc.id}",
                        article_proc_id=article_proc.id,
                        collection=collection_name
                    )
                    continue
                
                articles_migrated += 1
                statistics["total_articles_migrated"] += 1

                # Schedule publishing tasks
                scheduled = schedule_article_publication(
                    task_publish_article,
                    article_proc.id,
                    user_id,
                    username,
                    qa_api_data,
                    public_api_data,
                    force_update
                )
                
                if scheduled["qa"]:
                    qa_published += 1
                    statistics["articles_published_qa"] += 1
                
                if scheduled["public"]:
                    public_published += 1
                    statistics["articles_published_public"] += 1

            # Publication phase
            query_by_status = Q(qa_ws_status__in=status) | Q(
                public_ws_status__in=status
            )
            params["sps_pkg__pid_v3__isnull"] = False
            items = ArticleProc.objects.filter(
                query_by_status, collection=collection, **params
            )

            articles_to_publish = items.count()
            statistics["total_articles_to_publish"] += articles_to_publish
            
            log_event(
                execution_log,
                "info",
                "articles_publication",
                f"Found {articles_to_publish} articles to publish",
                collection=collection_name,
                count=articles_to_publish,
                status_filter=status,
                article_filter=params
            )

            for article_proc in items:
                schedule_article_publication(
                    task_publish_article,
                    article_proc.id,
                    user_id,
                    username,
                    qa_api_data,
                    public_api_data,
                    force_update
                )
            
            # Add collection summary
            log_event(
                execution_log,
                "info",
                "collection_completed",
                f"Completed processing collection {collection_name}",
                collection=collection_name,
                articles_processed=articles_count,
                articles_migrated=articles_migrated,
                articles_to_publish=articles_to_publish,
                qa_published=qa_published,
                public_published=public_published
            )
        
        # Final summary
        log_event(
            execution_log,
            "info",
            "task_completed",
            "Task completed successfully",
            **statistics
        )
        
        task_tracker.finish(
            completed=True, 
            detail={
                "log": execution_log,
                "statistics": statistics
            }
        )
        
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        
        log_event(
            execution_log,
            "error",
            "fatal_error",
            f"Task failed with error: {str(e)}",
            error=str(e),
            exc_type=str(exc_type),
            exc_value=str(exc_value)
        )
        
        task_tracker.finish(
            completed=False,
            exception=e,
            exc_traceback=exc_traceback,
            detail={
                "log": execution_log,
                "statistics": statistics
            }
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
        detail = {"published": False, "available": False}
        article_proc = None
        article_proc = ArticleProc.objects.get(pk=article_proc_id)
        event = article_proc.start(user, "publish article / check availability")
        response = article_proc.publish(
            user,
            publish_article,
            content_type="article",
            website_kind=website_kind,
            api_data=api_data,
            force_update=force_update,
        )
        detail["published"] = response.get("completed")
        detail["available"] = False
        if response.get("completed"):
            obj = ArticleAvailability.create_or_update(
                user,
                article_proc.article,
                published_by="MIGRATION",
                publication_rule="MIGRATION",
            )
            for website in WebSiteConfiguration.objects.filter(
                collection=article_proc.collection,
                purpose=website_kind,
            ):
                obj.create_or_update_urls(user, website.url)

            detail["available"] = obj.completed
        event.finish(user, detail=detail, completed=True)
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        try:
            event.finish(user, exc_traceback=exc_traceback, exception=e, detail=detail)
        except Exception as ignored_exception:
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
def task_create_procs_from_pid_list(
    self, username, user_id=None, collection_acron=None, force_update=None
):
    user = _get_user(user_id=user_id, username=username)
    try:
        for collection in _get_collections(collection_acron):
            task_create_collection_procs_from_pid_list.apply_async(
                kwargs=dict(
                    username=user.username,
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
def task_create_collection_procs_from_pid_list(
    self, username, collection_acron, force_update
):
    user = _get_user(user_id=None, username=username)
    try:
        task_params = {
            "task": "proc.tasks.task_create_collection_procs_from_pid_list",
            "username": username,
            "force_update": force_update,
        }
        task_tracker = TaskTracker.create(
            name="proc.tasks.task_create_collection_procs_from_pid_list",
            detail=task_params,
        )
        classic_website_config = controller.get_classic_website_config(collection_acron)
        collection = classic_website_config.collection
        create_collection_procs_from_pid_list(
            user,
            classic_website_config.collection,
            classic_website_config.pid_list_path,
            force_update,
        )
        task_tracker.finish(completed=True)
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        task_tracker.finish(
            completed=False,
            exception=e,
            exc_traceback=exc_traceback,
        )


@celery_app.task(bind=True)
def task_fetch_and_create_journal(
    self,
    user_id,
    username,
    collection_acron=None,
    issn_electronic=None,
    issn_print=None,
    force_update=None,
):
    user = _get_user(user_id=user_id, username=username)
    try:
        task_params = {
            "task": "proc.tasks.task_fetch_and_create_journal",
            "user_id": user_id,
            "username": username,
            "collection_acron": collection_acron,
            "issn_electronic": issn_electronic,
            "issn_print": issn_print,
            "force_update": force_update,
        }
        task_tracker = TaskTracker.create(
            name="proc.tasks.task_fetch_and_create_journal",
            detail=task_params,
        )
        fetch_and_create_journal(
            user,
            collection_acron=collection_acron,
            issn_electronic=issn_electronic,
            issn_print=issn_print,
            force_update=force_update,
        )
        task_tracker.finish(completed=True)
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        task_tracker.finish(
            completed=False,
            exception=e,
            exc_traceback=exc_traceback,
        )
