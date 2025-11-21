import logging
import sys
import traceback

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from article.models import Article
from collection.choices import PUBLIC, QA
from collection.models import Collection, WebSiteConfiguration
from config import celery_app
from migration import controller

from proc.controller import (
    create_collection_procs_from_pid_list,
    create_or_update_migrated_issue,
    create_or_update_migrated_journal,
    fetch_and_create_journal,
    migrate_issue,
    migrate_journal,
)
from proc.models import ArticleProc, IssueProc, JournalProc
from publication.api.document import publish_article
from publication.api.issue import publish_issue
from publication.api.journal import publish_journal
from publication.api.publication import get_api, get_api_data
from publication.models import ArticleAvailability
from tracker import choices as tracker_choices
from tracker.models import TaskTracker, UnexpectedEvent

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
                    if force_update or not journal_proc.journal.core_synchronized:
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
                user, completed=False, exception=e, exc_traceback=exc_traceback
            )
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

        task_params = {
            "task": "proc.tasks.task_publish_issues",
            "collection_acron": collection_acron,
            "journal_acron": journal_acron,
            "issue_folder": issue_folder,
            "publication_year": publication_year,
            "force_update": force_update,
        }
        task_tracker = TaskTracker.create(
            name="proc.tasks.task_publish_issues",
            detail=task_params,
        )
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
    collection_acron_list=None,
    journal_acron_list=None,
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
    detail = {}
    task_params = {
        "user_id": user_id,
        "username": username,
        "collection_acron": collection_acron,
        "journal_acron": journal_acron,
        "collection_acron_list": collection_acron_list,
        "journal_acron_list": journal_acron_list,
        "publication_year": publication_year,
        "issue_folder": issue_folder,
        "status": status,
        "force_update": force_update,
        "force_import_acron_id_file": force_import_acron_id_file,
        "force_migrate_document_records": force_migrate_document_records,
        "force_migrate_document_files": force_migrate_document_files,
    }
    
    task_tracker = TaskTracker.create(
        name="proc.tasks.task_migrate_and_publish_articles",
        detail=task_params,
    )
    
    try:
        params = {}
        journal_acron_list = journal_acron_list or []
        if journal_acron:
            journal_acron_list += [journal_acron]
        if journal_acron_list:
            params["acron__in"] = journal_acron_list
        collection_acron_list = collection_acron_list or []
        if collection_acron:
            collection_acron_list += [collection_acron]
        if collection_acron_list:
            params["collection__acron3__in"] = collection_acron_list

        journal_collection_pairs = JournalProc.objects.filter(**params).values("journal__acron", "collection__acron3").distinct()
        detail["total_journals_to_process"] = journal_collection_pairs.count()
        for journal_acron, collection_acron in journal_collection_pairs:
            kwargs = {}
            kwargs.update(task_params)
            kwargs["journal_acron"] = journal_acron
            kwargs["collection_acron"] = collection_acron
            task_migrate_and_publish_articles_by_collection_journal.delay(**kwargs)

        task_tracker.finish(completed=True, detail=detail)

    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        detail["exception"] = traceback.format_exc()
        task_tracker.finish(
            completed=False,
            exception=e,
            exc_traceback=exc_traceback,
            detail=detail,
        )


@celery_app.task(bind=True)
def task_migrate_and_publish_articles_by_collection_journal(
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
):
    # Lista plana para armazenar todos os eventos
    events = []

    # Estatísticas separadas
    statistics = {}

    try:
        user = _get_user(user_id, username)
        detail = {}
        task_params = {
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
        }
        task_tracker = TaskTracker.create(
            name=f"proc.tasks.task_migrate_and_publish_articles_by_collection_journal {journal_acron} {collection_acron}",
            detail=task_params,
        )
        # obtém os dados do site clássico
        journal_proc = JournalProc.select_related("collection").objects.get(
            collection__acron3=collection_acron,
            acron=journal_acron,
        )

        events.append("Create/update journal acron id file")
        response = controller.register_acron_id_file_content(
            user,
            journal_proc,
            force_update=force_import_acron_id_file,
        )
        statistics.update(response)
        events.append("Identify filter: article pids to migrate")
        try:
            article_pids_to_migrate = response.pop("article_pids_to_migrate")
        except KeyError:
            article_pids_to_migrate = []
        
        # Agrupa os article_pids_to_migrate por issue_pid
        events.append("Group article pids to migrate by issue")
        article_pids_to_migrate_by_issue = {}
        if article_pids_to_migrate:
            for article_pid in article_pids_to_migrate:
                if len(article_pid) >= 23:  # Verificação de segurança para PID válido
                    issue_pid = article_pid[1:-5]
                    article_pids_to_migrate_by_issue.setdefault(issue_pid, set())
                    article_pids_to_migrate_by_issue[issue_pid].add(article_pid)

        # Lista de issue_pids a serem processados
        issue_pids = list(article_pids_to_migrate_by_issue.keys())

        events.append("Identify filter: status")
        status = tracker_choices.get_valid_status(status, force_update)
        issue_proc_list = IssueProc.get_id_and_pid_list_to_process(
            journal_proc,
            issue_folder,
            publication_year,
            issue_pids,
            status,
            events,
        )
        
        statistics["total_issues_to_process"] = issue_proc_list.count()

        events.append("Schedule journal issues to process")
        for issue_proc_id, issue_pid in issue_proc_list:
            task_migrate_and_publish_articles_by_journal_issue.delay(
                user_id=user_id,
                username=username,
                issue_proc_id=issue_proc_id,
                article_pids_to_migrate=article_pids_to_migrate_by_issue.get(issue_pid),
                status=status,
                force_update=force_update,
                force_migrate_document_records=force_migrate_document_records,
                force_migrate_document_files=force_migrate_document_files,
           )
        detail["events"] = events
        detail["statistics"] = statistics
        task_tracker.finish(completed=True, detail=detail)
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        detail["exception"] = traceback.format_exc()
        detail["events"] = events
        detail["statistics"] = statistics
        task_tracker.finish(
            completed=False,
            exception=e,
            exc_traceback=exc_traceback,
            detail=detail,
        )


@celery_app.task(bind=True)
def task_migrate_and_publish_articles_by_journal_issue(
    self,
    user_id=None,
    username=None,
    issue_proc_id=None,
    article_pids_to_migrate=None,
    status=None,
    force_update=False,
    force_migrate_document_records=False,
    force_migrate_document_files=False,
):
    events = []
    detail = {}

    try:
        user = _get_user(user_id, username)
        task_params = {
            "user_id": user_id,
            "username": username,
            "issue_proc_id": issue_proc_id,
            "article_pids_to_migrate": article_pids_to_migrate,
            "status": status,
            "force_update": force_update,
            "force_migrate_document_records": force_migrate_document_records,
            "force_migrate_document_files": force_migrate_document_files,
        }
        issue_proc = IssueProc.objects.select_related(
            "collection", "journal_proc",
        ).get(pk=issue_proc_id)

        task_tracker = TaskTracker.create(
            name=f"proc.tasks.task_migrate_and_publish_articles_by_journal_issue {issue_proc}",
            detail=task_params,
        )
        
        if issue_proc.docs_status in status or article_pids_to_migrate:
            events.append("Migrate document records")
            issue_proc.migrate_document_records(user, force_update)

        if issue_proc.files_status in status:
            events.append("Migrate issue files")
            issue_proc.get_files_from_classic_website(
                user, force_update, controller.migrate_issue_files
            )

        ArticleProc.mark_for_reprocessing(issue_proc, article_pids_to_migrate)

        events.append("Select articles to migrate")
        query_by_status = (
            Q(migration_status__in=status)
            | Q(xml_status__in=status)
            | Q(sps_pkg_status__in=status)
        )
        filters = {"issue_proc": issue_proc}
        if article_pids_to_migrate:
            filters["pid__in"] = article_pids_to_migrate
        
        article_ids_to_migrate = ArticleProc.objects.select_related(
            "issue_proc",
        ).filter(
            query_by_status, **filters
        ).values_list("id", flat=True)

        publish_filters = {"issue_proc": issue_proc, "sps_pkg__pid_v3__isnull": False}
        if article_pids_to_migrate:
            publish_filters["pid__in"] = article_pids_to_migrate
            
        article_ids_to_publish = ArticleProc.objects.select_related(
            "issue_proc", "sps_pkg",
        ).filter(
            Q(qa_ws_status__in=status) | Q(public_ws_status__in=status),
            **publish_filters
        ).values_list("id", flat=True)

        detail["total_articles_to_migrate"] = article_ids_to_migrate.count()
        detail["total_articles_to_publish"] = article_ids_to_publish.count()
        
        events.append("Migrate and publish issue articles")
        if detail["total_articles_to_migrate"] or detail["total_articles_to_publish"]:            
            task_migrate_and_publish_issue_articles.delay(
                user_id=user_id,
                username=username,
                issue_proc=str(issue_proc),
                issue_proc_id=issue_proc_id,
                article_ids_to_migrate=list(article_ids_to_migrate),
                journal_acron=issue_proc.journal_proc.acron,
                collection_acron=issue_proc.collection.acron3,
                issue_folder=issue_proc.issue_folder,
                publication_year=issue_proc.issue.publication_year if issue_proc.issue else None,
                status=status,
                force_update=force_update,
            )

        detail["events"] = events
        task_tracker.finish(
            completed=True,
            detail=detail,
        )
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        detail["exception"] = traceback.format_exc()
        detail["events"] = events
        
        task_tracker.finish(
            completed=False,
            exception=e,
            exc_traceback=exc_traceback,
            detail=detail,
        )


@celery_app.task(bind=True)
def task_migrate_and_publish_issue_articles(
    self, 
    user_id=None,
    username=None,
    issue_proc=None,
    issue_proc_id=None,
    status=None,
    article_ids_to_migrate=None,
    collection_acron=None,
    journal_acron=None,
    issue_folder=None,
    publication_year=None,
    force_update=False,
):
    events = []
    detail = {}
    try:
        user = _get_user(user_id, username)
        task_params = {
            "user_id": user_id,
            "username": username,
            "issue_proc_id": issue_proc_id,
            "article_ids_to_migrate": article_ids_to_migrate,
            "status": status,
            "force_update": force_update,
        }
        
        task_tracker = TaskTracker.create(
            name=f"proc.tasks.task_migrate_and_publish_issue_articles {issue_proc}",
            detail=task_params,
        )
        events.append("Select articles to migrate")
        if article_ids_to_migrate:
            items = ArticleProc.objects.select_related(
                "issue_proc",
            ).filter(
                id__in=article_ids_to_migrate
            )
            detail["total_articles_to_process"] = items.count()
            
            events.append("Migrate articles")
            exceptions = {}
            for article_proc in items:
                try:
                    article = article_proc.migrate_article(user, force_update)
                except Exception as e:
                    exc_type, exc_value, exc_traceback = sys.exc_info()
                    exceptions[article_proc.pid] = traceback.format_exc()
            detail["total failures"] = len(exceptions)
            detail["total_articles_migrated"] = detail["total_articles_to_process"] - detail["total failures"]
            detail["exceptions"] = exceptions
        else:
            detail["total_articles_to_process"] = 0
            detail["total failures"] = 0
            detail["total_articles_migrated"] = 0
            detail["exceptions"] = {}
            events.append("No articles to migrate")
            
        article_ids_to_publish = ArticleProc.objects.select_related(
            "issue_proc", "sps_pkg",
        ).filter(
            Q(qa_ws_status__in=status) | Q(public_ws_status__in=status),
            issue_proc_id=issue_proc_id,
            sps_pkg__pid_v3__isnull=False,
        ).values_list("id", flat=True)
        detail["total_articles_to_publish"] = article_ids_to_publish.count()

        events.append("Schedule Publish articles")
        if detail["total_articles_to_publish"]:
            task_publish_articles.delay(
                user_id=user_id,
                username=username,
                collection_acron=collection_acron,
                journal_acron=journal_acron,
                issue_folder=issue_folder,
                publication_year=publication_year,
                force_update=force_update,
            )

        detail["events"] = events
        task_tracker.finish(
            completed=True,
            detail=detail,
        )
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        detail["exception"] = traceback.format_exc()
        detail["events"] = events
        task_tracker.finish(
            completed=False,
            exception=e,
            exc_traceback=exc_traceback,
            detail=detail,
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
    task_params = {
        "user_id": user_id,
        "username": username,
        "collection_acron": collection_acron,
        "journal_acron": journal_acron,
        "issue_folder": issue_folder,
        "publication_year": publication_year,
        "force_update": force_update,
    }
    
    task_tracker = TaskTracker.create(
        name="proc.tasks.task_publish_articles",
        detail=task_params,
    )
    
    try:
        params = {}
        total_scheduled = 0

        if journal_acron:
            params["issue_proc__journal_proc__acron"] = journal_acron
        if issue_folder:
            params["issue_proc__issue_folder"] = issue_folder
        if publication_year:
            params["issue_proc__issue__publication_year"] = publication_year

        for collection in _get_collections(collection_acron):
            for website_kind in (QA, PUBLIC):
                api_data = get_api_data(collection, "article", website_kind)
                if api_data.get("error"):
                    continue

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
                    total_scheduled += 1

        task_tracker.finish(
            completed=True,
            detail={"total_articles_scheduled": total_scheduled}
        )

    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        task_tracker.finish(
            completed=False,
            exception=e,
            exc_traceback=exc_traceback,
            detail=task_params,
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
    user = None
    detail = {"published": False, "available": False}
    article_proc = None
    event = None
    
    try:
        user = _get_user(user_id, username)
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
            if event and user:
                event.finish(user, exc_traceback=exc_traceback, exception=e, detail=detail)
            else:
                raise e
        except Exception as ignored_exception:
            UnexpectedEvent.create(
                e=e,
                exc_traceback=exc_traceback,
                detail={
                    "task": "proc.task.publish_article",
                    "user_id": user_id,
                    "username": username,
                    "website_kind": website_kind,
                    "pid": article_proc.pid if article_proc else None,
                    "article_proc_id": article_proc_id,
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
