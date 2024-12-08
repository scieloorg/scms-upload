import logging


from core.utils.get_user import _get_user
from bigbang import tasks_scheduler
from bigbang.setup import setup
from config import celery_app



@celery_app.task(bind=True)
def task_start(
    self,
    user_id=None,
    username=None,
    enable=False,
):
    tasks_scheduler.delete_migration_tasks()
    tasks_scheduler.schedule_publication_subtasks(username)
    tasks_scheduler.schedule_migration_subtasks(username)
    # FIXME tasks_scheduler.schedule_task_synchronize_to_pid_provider(username, enabled=enable)


@celery_app.task(bind=True)
def task_setup(
    self,
    user_id=None,
    username=None,
    file_path=None,
    config=None,
):
    user = _get_user(self.request, user_id, username)

    if file_path or config:
        setup(user, file_path, config)
