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


@celery_app.task(bind=True, name=_('Migrate and publish journals'))
def task_migrate_and_publish_journals(
        self,
        user_id,
        collection_acron,
        force_update=False,
        ):
    controller.migrate_and_publish_journals(
        user_id,
        collection_acron,
        force_update,
    )
