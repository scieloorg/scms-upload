import logging
import sys

from django.contrib.auth import get_user_model

from config import celery_app
from pid_provider.models import CollectionPidV2
from pid_provider.provider import PidProvider
from proc.models import ArticleProc
from tracker.models import UnexpectedEvent

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
    # somente os ids: evita carregar os objetos
    for article_proc_id in (
        ArticleProc.objects.filter(sps_pkg_id__isnull=False)
        .values_list("id", flat=True)
        .iterator()
    ):
        subtask_fix_pid_v2.apply_async(
            kwargs=dict(
                username=username,
                user_id=user_id,
                article_proc_id=article_proc_id,
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


@celery_app.task(bind=True)
def task_complete_collection_pid_v2_sps_pkg_name(
    self,
    username=None,
    user_id=None,
    force_update=False,
    batch_size=100,
):
    """
    Preenche CollectionPidV2.sps_pkg_name a partir de
    current_version.xml_with_pre.build_sps_pkg_name()

    Divide os registros em lotes processados por subtarefas, para que cada
    uma termine dentro do limite de tempo de tarefa do celery
    """
    user = _get_user(self.request, username=username, user_id=user_id)
    ids = list(
        CollectionPidV2.get_ids_to_complete_sps_pkg_name(force_update=force_update)
    )
    for start in range(0, len(ids), batch_size):
        subtask_complete_collection_pid_v2_sps_pkg_name.apply_async(
            kwargs=dict(
                user_id=user.id,
                ids=ids[start : start + batch_size],
            )
        )
    return {"total": len(ids), "batch_size": batch_size}


@celery_app.task(bind=True)
def subtask_complete_collection_pid_v2_sps_pkg_name(
    self,
    username=None,
    user_id=None,
    ids=None,
):
    user = _get_user(self.request, username=username, user_id=user_id)
    return CollectionPidV2.complete_sps_pkg_name(user, ids)
