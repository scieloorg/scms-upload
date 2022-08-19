import logging

from django.contrib.auth import get_user_model

from config import celery_app

from . import controller


User = get_user_model()


def migrate_journals(source_file_path, connection):
    controller.connect(connection)
    for pid, data in controller.get_classic_website_records("title", source_file_path):
        task_migrate_journal.delay(pid, data)


@celery_app.task(bind=True, max_retries=3)
def task_migrate_journal(self, pid, data):
    try:
        controller.migrate_journal(pid, data)
    except (
            controller.MigratedJournalSaveError,
            controller.JournalMigrationTrackSaveError,
            ) as e:
        logging.error(e)
    try:
        controller.publish_journal(pid)
    except (
            controller.PublishJournalError,
            ) as e:
        logging.error(e)


def migrate_issues(source_file_path, connection):
    controller.connect(connection)
    for pid, data in controller.get_classic_website_records("issue", source_file_path):
        task_migrate_issue.delay(pid, data)


@celery_app.task(bind=True, max_retries=3)
def task_migrate_issue(self, pid, data):
    try:
        controller.migrate_issue(pid, data)
    except (
            controller.MigratedIssueSaveError,
            controller.IssueMigrationTrackSaveError,
            ) as e:
        logging.error(e)
    try:
        controller.publish_issue(pid)
    except (
            controller.PublishIssueError,
            ) as e:
        logging.error(e)
