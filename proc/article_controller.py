import logging
import sys

from django.utils.translation import gettext_lazy as _

from collection.models import WebSiteConfiguration
from migration import choices as migration_choices
from migration.models import ClassicWebsiteConfiguration
from proc.models import ArticleProc


def log_event(execution_log, level, event_type, message, extra_data=None):
    """
    Adiciona um evento ao log de execução
    """
    event = {"message": message}
    if extra_data:
        event["data"] = extra_data
    execution_log.append(event)


def schedule_article_publication(
    task_publish_article,
    article_proc_id,
    user_id,
    username,
    qa_api_data,
    public_api_data,
    force_update,
):
    scheduled = {"qa": False, "public": False}

    if not qa_api_data.get("error"):
        task_publish_article.apply_async(
            kwargs=dict(
                user_id=user_id,
                username=username,
                website_kind="QA",
                article_proc_id=article_proc_id,
                api_data=qa_api_data,
                force_update=force_update,
            )
        )
        scheduled["qa"] = True

    if not public_api_data.get("error"):
        task_publish_article.apply_async(
            kwargs=dict(
                user_id=user_id,
                username=username,
                website_kind="PUBLIC",
                article_proc_id=article_proc_id,
                api_data=public_api_data,
                force_update=force_update,
            )
        )
        scheduled["public"] = True

    return scheduled


def migrate_collection_articles(user, collection_acron, items, force_update):
    statistics = {
        "total_articles_to_process": 0,
        "total_articles_migrated": 0,
    }
    execution_log = []
    articles_count = items.count()
    statistics["total_articles_to_process"] = articles_count

    log_event(
        execution_log, "info", "articles_migration",
        f"Found {articles_count} articles to migrate",
        dict(collection=collection_acron, count=articles_count),
    )
    articles_migrated = 0
    for article_proc in items.iterator():
        try:
            logging.info(f"Migrating article_proc {article_proc}")
            article = article_proc.migrate_article(user, force_update)
            if article:
                articles_migrated += 1
        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            event = article_proc.start(user, "Migrate article error")
            event.finish(user, completed=False, exception=e, exc_traceback=exc_traceback)

    statistics["total_articles_migrated"] = articles_migrated
    return statistics, execution_log


def publish_collection_articles(
    user, collection_acron, items, task_publish_article,
    qa_api_data, public_api_data, force_update,
):
    execution_log = []
    qa_scheduled = 0
    public_scheduled = 0
    processed = 0
    articles_count = items.count()

    log_event(
        execution_log, "info", "articles_publication",
        f"Found {articles_count} articles to publish",
        dict(
            collection=collection_acron, count=articles_count,
            qa_api_data_error=qa_api_data.get("error"),
            public_api_data_error=public_api_data.get("error"),
        ),
    )

    if not qa_api_data.get("error") or not public_api_data.get("error"):
        for article_proc in items.iterator():
            try:
                processed += 1
                response = schedule_article_publication(
                    task_publish_article, article_proc.id,
                    user.id, user.username, qa_api_data, public_api_data, force_update,
                )
                if response["qa"]:
                    qa_scheduled += 1
                if response["public"]:
                    public_scheduled += 1
            except Exception as e:
                exc_type, exc_value, exc_traceback = sys.exc_info()
                event = article_proc.start(user, "Schedule article publication error")
                event.finish(user, completed=False, exception=e, exc_traceback=exc_traceback)

    statistics = {
        "total_articles_to_publish": articles_count,
        "processed": processed,
        "total_qa_scheduled": qa_scheduled,
        "total_public_scheduled": public_scheduled,
        "qa_api_data_error": bool(qa_api_data.get("error")),
        "public_api_data_error": bool(public_api_data.get("error")),
    }
    return statistics, execution_log


class ClassicWebsiteArticlePidTracker:
    """
    Rastreia e reconcilia PIDs do site clássico com ArticleProcs.

    Fluxo: MISSING → MATCHED → PUBLISHED → CONTENT_VALID / CONTENT_UNMATCHED
    """

    COMPLETED_STATUSES = (
        migration_choices.PID_STATUS_MATCHED,
        migration_choices.PID_STATUS_PUBLISHED,
        migration_choices.PID_STATUS_PUBLIC_VALID,
        migration_choices.PID_STATUS_PUBLIC_MISMATCHED,
    )

    def __init__(self, user, collection, timeout=10):
        self.user = user
        self.collection = collection
        self.config = ClassicWebsiteConfiguration.objects.get(collection=collection)
        self.articles = ArticleProc.objects.filter(collection=collection)
        self.classic_website_url = self.config.url
        self.public_website_url = WebSiteConfiguration.get_website_url(collection)
        self.timeout = timeout

    def update_pid_status(self):
        qs = self.articles
        pids_to_check = self.config.get_pid_list()
        totals = {"input list total": len(pids_to_check)}
        new_pids = set(self._update_pid_status(pids_to_check))
        result = self.bulk_create(new_pids)
        totals.update(result)
        return totals

    def create_article_proc_for_pids(self, new_pids):
        if not new_pids:
            return []
        for pid in new_pids:
            yield ArticleProc(
                creator=self.user,
                collection=self.collection,
                pid=pid,
                pid_status=migration_choices.PID_STATUS_MISSING,
            )

    def _update_pid_status(self, pids_to_check):
        qs = self.articles
        pids_to_check = set(pids_to_check)
        migrated_and_completed_pids = set(qs.filter(
            migrated_data__isnull=False,
            pid_status__in=self.COMPLETED_STATUSES,
        ).values_list("pid", flat=True))
        pids_to_check = pids_to_check - migrated_and_completed_pids

        migrated_pids = set(qs.filter(
            migrated_data__isnull=False,
        ).exclude(
            pid_status__in=self.COMPLETED_STATUSES,
        ).values_list("pid", flat=True))
        matched_pids = pids_to_check.intersection(migrated_pids)
        qs.filter(pid__in=matched_pids).update(
            pid_status=migration_choices.PID_STATUS_MATCHED
        )
        pids_to_check = pids_to_check - matched_pids

        registered_pids_except_completed = set(qs.exclude(
            pid_status__in=self.COMPLETED_STATUSES,
        ).values_list("pid", flat=True))

        exceeding_pids = registered_pids_except_completed - pids_to_check
        if exceeding_pids:
            qs.filter(pid__in=exceeding_pids).exclude(
                pid_status=migration_choices.PID_STATUS_EXCEEDING
            ).update(pid_status=migration_choices.PID_STATUS_EXCEEDING)

        return pids_to_check - registered_pids_except_completed

    def bulk_create(self, new_pids, batch_size=500):
        if new_pids:
            ArticleProc.objects.bulk_create(
                self.create_article_proc_for_pids(new_pids), batch_size
            )
        return ArticleProc.get_pid_status_total(self.collection)
