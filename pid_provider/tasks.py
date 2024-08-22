import logging

from django.contrib.auth import get_user_model

from config import celery_app
from pid_provider.provider import PidProvider
from pid_provider.requester import PidRequester
from proc.models import ArticleProc

User = get_user_model()


def _get_user(request, username=None, user_id=None):
    try:
        return User.objects.get(pk=request.user.id)
    except AttributeError:
        if user_id:
            return User.objects.get(pk=user_id)
        if username:
            return User.objects.get(username=username)


@celery_app.task(bind=True, name="provide_pid_for_file")
def provide_pid_for_file(
    self,
    username=None,
    file_path=None,
    is_published=None,
):
    user = _get_user(self.request, username=username)

    pid_provider = PidProvider()
    for resp in pid_provider.provide_pid_for_xml_zip(
        file_path, user, is_published=is_published
    ):
        logging.info(resp)
    # return response


@celery_app.task(bind=True)
def task_fix_pid_v2(
    self,
    username=None,
    user_id=None,
):
    for article_proc in ArticleProc.objects.filter(sps_pkg__isnull=False).iterator():
        subtask_fix_pid_v2.apply_async(
            kwargs=dict(
                username=username,
                user_id=user_id,
                article_proc_id=article_proc.id,
            )
        )


@celery_app.task(bind=True)
def subtask_fix_pid_v2(
    self,
    username=None,
    user_id=None,
    article_proc_id=None,
):
    user = _get_user(self.request, username=username, user_id=user_id)
    article_proc = ArticleProc.objects.get(pk=article_proc_id)
    article_proc.fix_pid_v2(user)
