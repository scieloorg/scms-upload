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
