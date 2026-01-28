import logging
import sys
import traceback

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from article.models import Article
from journal.models import Journal
from issue.models import Issue
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
from publication.api.issue import publish_issue, sync_issue
from publication.api.journal import publish_journal
from publication.api.publication import get_api, get_api_data
from publication.models import ArticleAvailability
from tracker import choices as tracker_choices
from tracker.models import TaskTracker, UnexpectedEvent

User = get_user_model()

class NothingToProcess(Exception):
    ...


class TaskExecution:
    def __init__(self, name, item, params):
        self.params = params
        self.task_tracker = TaskTracker.create(
            name=name,
            item=item,
        )
        self.events = []
        self.stats = {}
        self.exceptions = []

    @property
    def item(self):
        return self.task_tracker.item
    
    @item.setter
    def item(self, value):
        self.task_tracker.item = value

    @property
    def total_to_process(self):
        return self.task_tracker.total_to_process
    
    @total_to_process.setter
    def total_to_process(self, value):
        self.task_tracker.total_to_process = value

    @property
    def total_processed(self):
        return self.task_tracker.total_processed
    
    @total_processed.setter
    def total_processed(self, value):
        self.task_tracker.total_processed = value

    def add_exception(self, exception):
        self.exceptions.append({"type": str(type(exception)), "message": str(exception)})

    def add_event(self, event):
        if isinstance(event, list):
            self.events.extend(event)
        else:
            self.events.append(event)

    def add_number(self, name, number):
        self.stats[name] = number

    def finish(self, exception=None, exc_traceback=None):
        if exception or exc_traceback or self.exceptions:
            completed = False
        else:
            completed = True
        self.params["item"] = self.item

        self.stats["total_to_process"] = self.total_to_process
        self.stats["total_processed"] = self.total_processed
        detail = {
            "params": self.params,
            "stats": self.stats,
            "events": self.events,
            "exceptions": self.exceptions,
        }
        self.task_tracker.finish(
            completed=completed,
            exception=exception,
            exc_traceback=exc_traceback,
            detail=detail,
        )


def _get_user(user_id, username):
    try:
        if user_id:
            return User.objects.get(pk=user_id)
        if username:
            return User.objects.get(username=username)
        return None
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
        return None


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
        return []


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
        for collection in _get_collections(collection_acron):
            task_migrate_and_publish_journals_by_collection.delay(
                user_id=user_id,
                username=username,
                collection_acron=collection.acron,
                journal_acron=journal_acron,
                force_update=force_update,
                status=status,
                force_import_acron_id_file=force_import_acron_id_file,
            )
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            action="proc.tasks.task_migrate_and_publish_journals",
            item=f"{collection_acron}-{journal_acron}",
            e=e,
            exc_traceback=exc_traceback,
            detail={"task_params": task_params},
        )


@celery_app.task(bind=True)
def task_migrate_and_publish_journals_by_collection(
    self,
    user_id=None,
    username=None,
    collection_acron=None,
    journal_acron=None,
    force_update=False,
    status=None,
    force_import_acron_id_file=False,
):
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
    
    task_exec = TaskExecution(
        name="proc.tasks.task_migrate_and_publish_journals_by_collection",
        item=f"{collection_acron}-{journal_acron}",
        params=task_params,
    )
    
    try:
        user = _get_user(user_id, username)

        classic_website = controller.get_classic_website(collection_acron)
        collection = Collection.objects.get(acron=collection_acron)
        create_or_update_migrated_journal(
            user,
            collection,
            classic_website,
            force_update,
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
        items_to_process = JournalProc.objects.filter(
            query_by_status, collection=collection, **journal_filter
        )
        task_exec.total_to_process = items_to_process.count()
        if not task_exec.total_to_process:
            task_exec.finish()
            return
        
        qa_api_data = get_api_data(collection, "journal", "QA")
        public_api_data = get_api_data(collection, "journal", "PUBLIC")

        for journal_proc in items_to_process:
            try:
                detail = {}
                event = journal_proc.start(user, "migrate journal")
                # cria ou atualiza Journal e atualiza journal_proc
                completed = journal_proc.create_or_update_item(
                    user, force_update, controller.create_or_update_journal
                )
                # atualiza Journal e atualiza journal_proc com dados do Core
                if force_update or not journal_proc.journal.core_synchronized:
                    fetch_and_create_journal(
                        user,
                        collection_acron=collection.acron,
                        issn_electronic=journal_proc.issn_electronic,
                        issn_print=journal_proc.issn_print,
                        force_update=force_update,
                    )                
                if qa_api_data and not qa_api_data.get("error"):
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
                if public_api_data and not public_api_data.get("error"):
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
                event.finish(user, completed=True, detail=detail)
                task_exec.total_processed += 1
            except Exception as e:
                exc_type, exc_value, exc_traceback = sys.exc_info()
                if event:
                    event.finish(
                        user,
                        completed=False,
                        exception=e,
                        exc_traceback=exc_traceback,
                        detail=detail
                    )
                else:
                    UnexpectedEvent.create(
                        action="proc.tasks.task_migrate_and_publish_journals_by_collection",
                        item=f"{journal_proc}",
                        e=e,
                        exc_traceback=exc_traceback,
                        detail=detail,
                    )
        task_exec.finish()
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        try:
            task_exec.finish(
                exception=e,
                exc_traceback=exc_traceback,
            )
        except Exception:
            UnexpectedEvent.create(
                action="proc.tasks.task_migrate_and_publish_journals_by_collection",
                item=f"{collection_acron}-{journal_acron}",
                e=e,
                exc_traceback=exc_traceback,
                detail=task_params,
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
    task_params = {
        "task": "proc.tasks.task_publish_journals",
        "user_id": user_id,
        "username": username,
        "collection_acron": collection_acron,
        "journal_acron": journal_acron,
        "force_update": force_update,
    }

    try:
        user = _get_user(user_id, username)

        params = {}
        if journal_acron:
            params["acron"] = journal_acron

        for collection in _get_collections(collection_acron):
            for website_kind in (QA, PUBLIC):
                api_data = get_api_data(collection, "journal", website_kind)
                if not api_data or api_data.get("error"):
                    continue
                task_exec = TaskExecution(
                    name="proc.tasks.task_publish_journals",
                    item=f"{collection_acron}-{journal_acron} {website_kind}",
                    params=task_params,
                )

                items = JournalProc.items_to_publish(
                    website_kind=website_kind,
                    content_type="journal",
                    collection=collection,
                    force_update=force_update,
                    params=params,
                )
                task_exec.total_to_process = items.count()

                for journal_proc in items:
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
                        task_exec.total_processed += 1
                    except Exception as e:
                        exc_type, exc_value, exc_traceback = sys.exc_info()
                        UnexpectedEvent.create(
                            item=str(journal_proc),
                            action="task_publish_journal",
                            e=e,
                            exc_traceback=exc_traceback,
                            detail=task_params,
                        )
                task_exec.finish()
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            item=f"{collection_acron}-{journal_acron}",
            action="task_publish_journal",
            e=e,
            exc_traceback=exc_traceback,
            detail=task_params,
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
        event.finish(user, completed=True)
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        try:
            event.finish(
                user, completed=False, exception=e, exc_traceback=exc_traceback
            )
        except Exception as ignored_exception:
            UnexpectedEvent.create(
                action="proc.tasks.publish_journal",
                item=f"{journal_proc_id}",
                e=e,
                exc_traceback=exc_traceback,
                detail={
                    "task": "proc.tasks.publish_journal",
                    "user_id": user_id,
                    "username": username,
                    "website_kind": website_kind,
                    "journal_proc_id": journal_proc_id,
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
    task_params = {
        "user_id": user_id,
        "username": username,
        "collection_acron": collection_acron,
        "journal_acron": journal_acron,
        "publication_year": publication_year,
        "issue_folder": issue_folder,
        "status": status,
        "force_update": force_update,
        "force_migrate_document_records": force_migrate_document_records,
    }
    try:
        user = _get_user(user_id, username)
        for collection in _get_collections(collection_acron):
            task_params["collection_acron"] = collection.acron
            task_migrate_and_publish_issues_by_collection.delay(**task_params)
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            action="proc.tasks.task_migrate_and_publish_issues",
            item=f"{collection_acron}-{journal_acron}-{issue_folder}-{publication_year}",
            e=e,
            exc_traceback=exc_traceback,
            detail=task_params
        )


@celery_app.task(bind=True)
def task_migrate_and_publish_issues_by_collection(
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
    task_params = {
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
    task_exec = TaskExecution(
        name="proc.tasks.task_migrate_and_publish_issues_by_collection",
        item=f"{collection_acron}-{journal_acron}-{issue_folder}-{publication_year}",
        params=task_params,
    )
    try:
        user = _get_user(user_id, username)

        task_exec.add_event("Read issue.id")
        # obtém os dados do site clássico
        classic_website = controller.get_classic_website(collection_acron)
        collection = Collection.objects.get(acron=collection_acron)
        create_or_update_migrated_issue(
            user,
            collection,
            classic_website,
            force_update,
        )
        
        # filtra os issues para processar
        task_exec.add_event("Select issue to process")
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
        items = IssueProc.objects.filter(
            query_by_status,
            collection=collection,
            **params,
        )
        task_exec.total_to_process = items.count()
        
        if not task_exec.total_to_process:
            task_exec.finish()
            return

        qa_api_data = get_api_data(collection, "issue", "QA")
        public_api_data = get_api_data(collection, "issue", "PUBLIC")

        for issue_proc in items:
            try:
                # issue_proc -> issue
                task_exec.add_event("issue_proc -> issue")
                migrate_issue(user, issue_proc, force_update)

                if qa_api_data and not qa_api_data.get("error"):
                    task_exec.add_event("Schedule to publish issue on QA")
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
                if public_api_data and not public_api_data.get("error"):
                    task_exec.add_event("Schedule to publish issue on PUBLIC")
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
                task_exec.total_processed += 1
            except Exception as e:
                exc_type, exc_value, exc_traceback = sys.exc_info()
                task_exec.add_exception(traceback.format_exc())
        task_exec.finish()
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        try:
            task_exec.finish(
                exception=e,
                exc_traceback=exc_traceback,
            )
        except Exception:
            UnexpectedEvent.create(
                action="proc.tasks.task_migrate_and_publish_issues_by_collection",
                item=f"{collection_acron}-{journal_acron}",
                e=e,
                exc_traceback=exc_traceback,
                detail=task_params,
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
    task_params = {
       "collection_acron": collection_acron,
        "journal_acron": journal_acron,
        "issue_folder": issue_folder,
        "publication_year": publication_year,
        "force_update": force_update,
    }
    
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
                total_processed = 0
                api_data = get_api_data(collection, "issue", website_kind)
                if not api_data or api_data.get("error"):
                    continue
                task_exec = TaskExecution(
                    name="proc.tasks.task_publish_issues",
                    item=f"{collection_acron}-{journal_acron}-{issue_folder}-{publication_year} {website_kind}",
                    params=task_params,
                )
                items = IssueProc.items_to_publish(
                    website_kind=website_kind,
                    content_type="issue",
                    collection=collection,
                    force_update=force_update,
                    params=params,
                )
                task_exec.total_to_process = items.count()
                for issue_proc in items:
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
                        total_processed += 1
                    except Exception as e:
                        exc_type, exc_value, exc_traceback = sys.exc_info()
                        task_exec.add_exception(traceback.format_exc())
                task_exec.total_processed = total_processed
                task_exec.finish()
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            item=f"{collection_acron}-{journal_acron}-{issue_folder}-{publication_year}",
            action="task_publish_issues",
            e=e,
            exc_traceback=exc_traceback,
            detail=task_params,
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
                item=f"{issue_proc_id}",
                action="proc.tasks.publish_issue",
                e=e,
                exc_traceback=exc_traceback,
                detail={
                    "task": "proc.tasks.publish_issue",
                    "user_id": user_id,
                    "username": username,
                    "website_kind": website_kind,
                    "issue_proc_id": issue_proc_id,
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
    title = f"{collection_acron or collection_acron_list}-{journal_acron or journal_acron_list}-{issue_folder}-{publication_year}"
    task_exec = TaskExecution(
        name="proc.tasks.task_migrate_and_publish_articles",
        item=title,
        params=task_params,
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
            params["collection__acron__in"] = collection_acron_list

        task_exec.add_event(_("Select journals by collection"))
        journal_collection_pairs = JournalProc.objects.filter(**params).values_list("acron", "collection__acron").distinct()

        total_journals_to_process = journal_collection_pairs.count()
        task_exec.add_number("total_journals_to_process", total_journals_to_process)

        kwargs_ = {}
        kwargs_.update(task_params)
        kwargs_.pop("collection_acron_list", None)
        kwargs_.pop("journal_acron_list", None)

        task_exec.total_to_process = total_journals_to_process
        total_processed = 0
        for journal_acron, collection_acron in journal_collection_pairs:
            kwargs = {}
            kwargs.update(kwargs_)
            kwargs["journal_acron"] = journal_acron
            kwargs["collection_acron"] = collection_acron
            total_processed += 1
            task_migrate_and_publish_articles_by_journal.delay(**kwargs)

        task_exec.total_processed = total_processed
        task_exec.finish()

    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        try:
            task_exec.finish(
                exception=e,
                exc_traceback=exc_traceback,
            )
        except Exception as ignored_exception:
            UnexpectedEvent.create(
                item=title,
                action="proc.tasks.task_migrate_and_publish_articles",
                e=e,
                exc_traceback=exc_traceback,
                detail=task_params,
            )


@celery_app.task(bind=True)
def task_migrate_and_publish_articles_by_journal(
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
    title = f"{collection_acron}-{journal_acron}-{issue_folder}-{publication_year}"
    task_exec = TaskExecution(
        name=f"proc.tasks.task_migrate_and_publish_articles_by_journal",
        item=title,
        params=task_params,
    )
    try:
        user = _get_user(user_id, username)
        journal_proc = JournalProc.objects.select_related("collection").get(
            collection__acron=collection_acron,
            acron=journal_acron,
        )

        task_exclude_article_repetition(
            journal_proc.id,
            qa_api_data=None,
            public_api_data=None,
            username=user.username,
            user_id=user.id,
            timeout=None,
        )

        task_exec.add_event("Read journal acron id file")
        response = controller.register_acron_id_file_content(
            user,
            journal_proc,
            force_update=force_import_acron_id_file,
        )

        try:
            article_pids = response.pop("article_pids")
        except KeyError:
            article_pids = []
        task_exec.add_event(f"acron.id response: {response}")
        task_exec.total_to_process = len(article_pids)
        task_exec.add_number("total_articles_to_process", len(article_pids))
        
        # Agrupa os article_pids por issue_pid
        task_exec.add_event("Group article pids by issue")
        article_pids_by_issue = {}
        for article_pid in article_pids:
            if len(article_pid) >= 23:  # Verificação de segurança para PID válido
                issue_pid = article_pid[1:-5]
                article_pids_by_issue.setdefault(issue_pid, set()).add(article_pid)

        # Lista de issue_pids a serem processados
        issue_pids = list(article_pids_by_issue.keys())
        task_exec.add_number("total_issues_with_articles_to_process", len(issue_pids))

        status = tracker_choices.get_valid_status(status, force_update)
        task_exec.add_event(f"Select journal issues which docs_status or files_status in {status} and/or has articles to process")

        events = []
        issue_proc_list = IssueProc.get_id_and_pid_list_to_process(
            journal_proc,
            issue_folder,
            publication_year,
            issue_pids,
            status,
            events,
        )
        total_issues_to_process = issue_proc_list.count()
        task_exec.add_event(events)
        task_exec.add_number("total_issues_to_process", total_issues_to_process)
        task_exec.total_to_process = total_issues_to_process
        
        if not total_issues_to_process:
            task_exec.finish()
            return
    
        task_exec.add_event("Schedule to process articles by issue")
        # para cada issue:
        # - (docs_status) obtém os registros dos documentos (IdFileRecord -> ArticleProc)
        # - (files_status) obtém os arquivos dos documentos (img, pdf, translation, xml, etc)
        # - processamento de artigos
        qa_api_data = get_api_data(journal_proc.collection, "issue", "QA")
        public_api_data = get_api_data(journal_proc.collection, "issue", "PUBLIC")
        total_processed = 0
        for issue_proc_id, issue_pid in issue_proc_list:
            total_processed += 1
            task_migrate_and_publish_articles_by_issue.delay(
                user_id=user_id,
                username=username,
                issue_proc_id=issue_proc_id,
                article_pids=list(article_pids_by_issue.get(issue_pid) or []),
                status=status,
                force_update=force_update,
                force_migrate_document_records=force_migrate_document_records,
                force_migrate_document_files=force_migrate_document_files,
                qa_api_data=qa_api_data,
                public_api_data=public_api_data,
        )
        task_exec.total_processed = total_processed
        task_exec.finish()
    
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        task_exec.finish(
            exception=e,
            exc_traceback=exc_traceback,
        )


@celery_app.task(bind=True)
def task_migrate_and_publish_articles_by_issue(
    self,
    user_id=None,
    username=None,
    issue_proc_id=None,
    article_pids=None,
    status=None,
    force_update=False,
    force_migrate_document_records=False,
    force_migrate_document_files=False,
    qa_api_data=None,
    public_api_data=None,
):
    task_params = {
        "user_id": user_id,
        "username": username,
        "issue_proc_id": issue_proc_id,
        "article_pids": article_pids,
        "status": status,
        "force_update": force_update,
        "force_migrate_document_records": force_migrate_document_records,
        "force_migrate_document_files": force_migrate_document_files,
    }
    task_exec = TaskExecution(
        name=f"proc.tasks.task_migrate_and_publish_articles_by_issue",
        item=issue_proc_id,
        params=task_params,
    )
    try:
        user = _get_user(user_id, username)
        issue_proc = IssueProc.objects.select_related(
            "collection", "journal_proc",
        ).get(id=issue_proc_id)
        task_exec.item = str(issue_proc)
        task_exec.total_to_process = len(article_pids)
        task_exec.add_event(f"STATUS={status}")
        task_exec.add_event(f"docs_status: {issue_proc.docs_status}")

        task_exec.add_event("Migrate document records")
        total_migrated_records = issue_proc.migrate_document_records(user, force_migrate_document_records)
        task_exec.add_number("total_migrated_records", total_migrated_records)

        task_exec.add_event("Migrate issue files")
        total_migrated_files = issue_proc.get_files_from_classic_website(
            user, force_migrate_document_files, controller.migrate_issue_files
        )
        task_exec.add_number("total_migrated_files", total_migrated_files)

        task_exec.add_event("Mark articles for reprocessing")
        ArticleProc.mark_for_reprocessing(issue_proc, article_pids)

        task_exec.add_event("Select articles to migrate and/or publish")
        query_by_status = (
            Q(migration_status__in=status)
            | Q(xml_status__in=status)
            | Q(sps_pkg_status__in=status)
        )
        articles_to_process = ArticleProc.objects.select_related(
            "issue_proc",
        ).filter(
            query_by_status, issue_proc=issue_proc,
        )
        total_articles_to_process = articles_to_process.count()
        task_exec.total_to_process = total_articles_to_process
        task_exec.add_event("Migrate articles")
        total_processed = 0
        exceptions = {}
        for article_proc in articles_to_process:
            try:
                article = article_proc.migrate_article(user, force_update)
                total_processed += 1
            except Exception as e:
                exc_type, exc_value, exc_traceback = sys.exc_info()
                exceptions[article_proc.pid] = traceback.format_exc()
                task_exec.add_exception(exceptions[article_proc.pid])

        task_exec.total_processed = total_processed
            
        article_ids_to_publish = ArticleProc.objects.select_related(
            "issue_proc", "sps_pkg",
        ).filter(
            Q(qa_ws_status__in=status) | Q(public_ws_status__in=status),
            issue_proc=issue_proc,
            sps_pkg__pid_v3__isnull=False,
        ).values_list("id", flat=True)
        total_articles_to_publish = article_ids_to_publish.count()
        task_exec.add_number("total_articles_to_publish", total_articles_to_publish)

        for website_label in (QA, PUBLIC):
            task_exec.add_event(f"Schedule Publish articles / sync issue tasks for {website_label}")
            task_sync_issue.apply_async(
                kwargs=dict(
                    user_id=user_id,
                    username=username,
                    issue_proc_id=issue_proc.id,
                    website_kind=website_label,
                    status=status,
                    force_update=force_update,
                )
            )

        task_exec.finish()
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        task_exec.finish(
            exception=e,
            exc_traceback=exc_traceback,
        )


@celery_app.task(bind=True)
def task_sync_issue(
    self,
    user_id=None,
    username=None,
    issue_proc_id=None,
    website_kind=None,
    status=None,
    force_update=False,
):
    task_params = {
        "user_id": user_id,
        "username": username,
        "issue_proc_id": issue_proc_id,
        "website_kind": website_kind,
        "status": status,
        "force_update": force_update,
    }
    task_exec = TaskExecution(
        name="proc.tasks.task_sync_issue",
        item=f"{issue_proc_id}",
        params=task_params,
    )
    try:
        user = _get_user(user_id, username)
        issue_proc = IssueProc.objects.select_related(
            "collection", "journal_proc", "issue"
        ).get(id=issue_proc_id)
        
        task_exec.item = f"{issue_proc} {website_kind}"
        
        status = tracker_choices.get_valid_status(status, force_update)
        task_exec.add_event(f"Publishing articles for {website_kind} with status {status}")

        query_by_status = Q()
        if website_kind == QA:
            query_by_status = Q(qa_ws_status__in=status)
        elif website_kind == PUBLIC:
            query_by_status = Q(public_ws_status__in=status)

        article_ids_to_publish = ArticleProc.objects.select_related(
            "issue_proc", "sps_pkg",
        ).filter(
            query_by_status,
            issue_proc=issue_proc,
            sps_pkg__pid_v3__isnull=False,
        ).values_list("id", flat=True)

        task_exec.total_to_process = article_ids_to_publish.count()
        total_processed = 0

        api_data = get_api_data(issue_proc.collection, "article", website_kind)
        if not api_data or api_data.get("error"):
            task_exec.add_event(f"API data not available for {website_kind} {api_data}")
            task_exec.finish()
            return

        for article_proc_id in article_ids_to_publish:
            try:
                task_publish_article(
                    user_id=user_id,
                    username=username,
                    website_kind=website_kind,
                    article_proc_id=article_proc_id,
                    api_data=api_data,
                    force_update=force_update,
                )
                total_processed += 1
            except Exception as e:
                exc_type, exc_value, exc_traceback = sys.exc_info()
                task_exec.add_exception(traceback.format_exc())
        task_exec.total_processed = total_processed

        api_data = get_api_data(issue_proc.collection, "issue", website_kind)
        if not api_data or api_data.get("error"):
            task_exec.add_event(f"API data not available for {website_kind} {api_data}")
            task_exec.finish()
            return

        task_exec.add_event(f"Syncing issue in {website_kind} website")
        sync_issue(issue_proc, api_data)
        task_exec.add_event(f"Issue synced in {website_kind} website")
        
        task_exec.finish()
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        task_exec.finish(
            exception=e,
            exc_traceback=exc_traceback,
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
    title = f"{collection_acron}-{journal_acron}-{issue_folder}-{publication_year}"
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
                if not api_data or api_data.get("error"):
                    continue

                task_exec = TaskExecution(
                    name="proc.tasks.task_publish_articles",
                    item=f"{title} {website_kind}",
                    params=task_params,
                )
                items_to_publish = ArticleProc.items_to_publish(
                    website_kind=website_kind,
                    content_type="article",
                    collection=collection,
                    force_update=force_update,
                    params=params,
                )
                total_scheduled = 0
                task_exec.total_to_process = items_to_publish.count()
                for article_proc in items_to_publish:
                    task_publish_article.delay(
                        user_id=user_id,
                        username=username,
                        website_kind=website_kind,
                        article_proc_id=article_proc.id,
                        api_data=api_data,
                        force_update=force_update,
                    )
                    total_scheduled += 1
                task_exec.total_processed = total_scheduled
                task_exec.finish()

    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            item=title,
            action="proc.tasks.task_publish_articles",
            e=e,
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
    task_params = {
        "username": username,
        "collection_acron": collection_acron,
        "force_update": force_update,
    }
    task_exec = TaskExecution(
        name="proc.tasks.task_create_collection_procs_from_pid_list",
        item=f"{collection_acron}",
        params=task_params,
    )
    try:
        user = _get_user(user_id=None, username=username)
        classic_website_config = controller.get_classic_website_config(collection_acron)
        collection = classic_website_config.collection
        create_collection_procs_from_pid_list(
            user,
            classic_website_config.collection,
            classic_website_config.pid_list_path,
            force_update,
        )
        task_exec.finish()
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        task_exec.finish(
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
    task_params = {
        "task": "proc.tasks.task_fetch_and_create_journal",
        "user_id": user_id,
        "username": username,
        "collection_acron": collection_acron,
        "issn_electronic": issn_electronic,
        "issn_print": issn_print,
        "force_update": force_update,
    }
    task_exec = TaskExecution(
        name="proc.tasks.task_fetch_and_create_journal",
        item=f"{collection_acron}-{issn_electronic or ''}-{issn_print or ''}",
        params=task_params,
    )
    
    try:
        user = _get_user(user_id=user_id, username=username)
        fetch_and_create_journal(
            user,
            collection_acron=collection_acron,
            issn_electronic=issn_electronic,
            issn_print=issn_print,
            force_update=force_update,
        )
        task_exec.finish()
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        task_exec.finish(
            exception=e,
            exc_traceback=exc_traceback,
        )

###############################


@celery_app.task(bind=True)
def task_exclude_article_repetition(self, journal_proc_id, qa_api_data=None, public_api_data=None, username=None, user_id=None, timeout=None):
    task_params = {
        "journal_proc_id": journal_proc_id,
        "qa_api_data": bool(qa_api_data),
        "public_api_data": bool(public_api_data),
    }
    journal_proc_str = str(journal_proc_id)
    task_exec = TaskExecution(
        name="task_exclude_article_repetition",
        item=journal_proc_str,
        params=task_params,
    )
    try:
        user = _get_user(user_id=user_id, username=username)
        journal_proc = JournalProc.objects.get(id=journal_proc_id)
        journal = journal_proc.journal
        collection = journal_proc.collection

        task_exec.item = str(journal_proc)
        journal_proc_str = str(journal_proc)

        journal_articles_qs = Article.objects.filter(journal=journal)
        task_exec.add_number("total_articles_in_journal", journal_articles_qs.count())

        journal_articles_to_fix_sps_pkg_names_qs = journal_articles_qs.filter(
            Q(issue__supplement__isnull=True),
            ~Q(sps_pkg__sps_pkg_name__contains="-s"),
            sps_pkg__isnull=False,
        )
        response = Article.fix_sps_pkg_names(journal_articles_to_fix_sps_pkg_names_qs)
        task_exec.add_event(f"fixed sps_pkg_names: {response}")

        issues = set()
        for field_name in ("pid_v2", "sps_pkg__sps_pkg_name"):
            repeated_items = Article.get_repeated_items(field_name, journal)
            task_exec.add_number(f"repeated_by_{field_name}", repeated_items.count())
            for repeated_value in repeated_items:
                try:
                    events = Article.exclude_repetitions(user, field_name, repeated_value, timeout=timeout)
                    task_exec.add_event(events)
                except Exception as e:
                    exc_type, exc_value, exc_traceback = sys.exc_info()
                    task_exec.add_exception(
                        {
                            f"repeated_by_{field_name}": repeated_value,
                            "traceback": traceback.format_exc(),
                        }
                    )
        task_exec.finish()
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        try:
            task_exec.finish(
                exception=e,
                exc_traceback=exc_traceback,
            )
        except Exception:
            UnexpectedEvent.create(
                item=journal_proc_str,
                action="proc.tasks.task_exclude_article_repetition",
                e=e,
                exc_traceback=exc_traceback,
                detail=task_params,
            )


@celery_app.task(bind=True)
def task_remove_duplicate_issues(
    self,
    user_id=None,
    username=None,
    journal_id=None,
):
    """
    Remove Issue duplicados.
    
    Args:
        dry_run: Se True, apenas identifica duplicatas sem remover.
    """
    task_params = {
        "user_id": user_id,
        "username": username,
        "journal_id": journal_id,
    }
    task_exec = TaskExecution(
        name="proc.tasks.task_remove_duplicate_issues",
        item=f"{journal_id or 'all'}",
        params=task_params,
    )
    try:
        user = _get_user(user_id, username)
        stats = {}
        journal = None
        if journal_id:
            journal = Journal.objects.get(id=journal_id)
        
        duplicates = Issue.get_duplicates(journal)
        stats["total_duplicated_issues"] = duplicates.count()
        task_exec.total_to_process = stats["total_duplicated_issues"]
        duplicated_issues = []
        for duplicated_issue_data in duplicates.iterator():
            try:
                duplicated_issues.append(duplicated_issue_data)
                issues = list(Issue.objects.filter(**duplicated_issue_data).order_by("-updated"))
                keep = issues[0]
                task_exec.add_event(f"Remove duplicated Issues, (keeping {keep})")
                for issue in issues[1:]:
                    try:
                        # Migra artigos para o Issue mantido
                        Article.objects.filter(issue=issue).update(issue=keep)
                        # Atualiza IssueProc se existir
                        IssueProc.objects.filter(issue=issue).update(issue=keep)
                        issue.delete()
                    except Exception as e:
                        exc_type, exc_value, exc_traceback = sys.exc_info()
                        task_exec.add_exception(
                            {
                                "duplicated_issue_data": duplicated_issue_data,
                                "issue_id": issue.id,
                                "traceback": traceback.format_exc(),
                            }
                        )
                task_exec.total_processed += 1
            except Exception as e:
                exc_type, exc_value, exc_traceback = sys.exc_info()
                task_exec.add_exception(
                    {
                        "duplicated_issue_data": duplicated_issue_data,
                        "traceback": traceback.format_exc(),
                    }
                )
        task_exec.finish()
        
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        task_exec.finish(exception=e, exc_traceback=exc_traceback)
