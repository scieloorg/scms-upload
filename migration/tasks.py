import logging

from django.utils.translation import gettext_lazy as _

from config import celery_app
from celery.exceptions import SoftTimeLimitExceeded

from . import controller


@celery_app.task(bind=True, name=_('Start'))
def start(
        self,
        ):
    controller.start()


@celery_app.task(bind=True, name=_('Start'))
def start(
        self,
        ):
    controller.start()


@celery_app.task(bind=True, name=_('Schedule journals and issues migrations'))
def task_schedule_journals_and_issues_migrations(
        self,
        user_id,
        collection_acron,
        force_update=False,
        ):
    controller.schedule_journals_and_issues_migrations(collection_acron, user_id)


@celery_app.task(bind=True, name=_('Migrate and publish issues'))
def task_migrate_and_publish_issues(
        self,
        user_id,
        collection_acron,
        force_update=False,
        ):
    controller.migrate_and_publish_issues(
        user_id,
        collection_acron,
        force_update,
    )
