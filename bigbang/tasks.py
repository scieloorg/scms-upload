import logging

from django.contrib.auth import get_user_model
from bigbang.setup import setup
from bigbang import tasks_scheduler
from config import celery_app

User = get_user_model()


def _get_user(user_id, username):
    if user_id:
        return User.objects.get(pk=user_id)
    if username:
        return User.objects.get(username=username)


@celery_app.task(bind=True)
def task_start(
    self,
    user_id=None,
    username=None,
    file_path=None,
    activate_run_all=None,
    activate_run_partial=None,
):
    user = _get_user(user_id, username)
    setup(user, file_path)
    tasks_scheduler.schedule_migrations(
        user.username,
        activate_run_all=activate_run_all,
        activate_run_partial=activate_run_partial,
    )
    tasks_scheduler.schedule_publication(
        user.username,
        activate_run_all=activate_run_all,
        activate_run_partial=activate_run_partial,
    )
