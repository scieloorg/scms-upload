import logging

from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _
from django.db.models import Q

from config import celery_app
from files_storage.models import MinioConfiguration, RemoteSPSPkg
from package import choices
from package.models import SPSPkg

from . import controller

User = get_user_model()


def _get_user(request, username):
    try:
        return User.objects.get(pk=request.user.id)
    except AttributeError:
        return User.objects.get(username=username)


@celery_app.task(bind=True, name="request_pid_v3_and_create_articles")
def task_request_pid_v3_and_create_articles(
    self,
    username,
):
    last = Article.get_latest_change()
    items = RemoteSPSPkg.get_items_for_task(
        from_date=last, task_name="request_pid_v3_and_create_articles")
    for item in items:
        task_request_pid_v3_and_create_article.apply_async(
            kwargs={
                "username": username,
                "pkg_id": item.id,
            }
        )


@celery_app.task(bind=True, name="request_pid_v3_and_create_article")
def task_request_pid_v3_and_create_article(
    self,
    username,
    pkg_id,
):
    user = _get_user(self.request, username)
    item = RemoteSPSPkg.objects.get(id=pkg_id)

    xml_name = item.sps_pkg_name + ".xml"

    try:
        logging.info(f"Solicita/Confirma PID v3 para {xml_name}")

        # solicita pid v3 e obtém o article criado
        xml_with_pre = item.xml_with_pre
        response = request_pid_v3_and_create_article(
            xml_with_pre,
            xml_name,
            user,
        )
        if response["xml_changed"]:
            item.update_xml(xml_with_pre)
        # cria / obtém article
        logging.info(f"Cria / obtém article para {xml_name}")
        item.task_name = None
        item.save()
    except Exception as e:
        # TODO registra falha e deixa acessível na área restrita
        logging.exception(e)


@celery_app.task(bind=True, name="push_articles_files_to_remote_storage")
def task_push_articles_files_to_remote_storage(
    self,
    username,
):
    last = RemoteSPSPkg.get_latest_change()
    items = SPSPkg.get_items_for_task(
        from_date=last, task_name="push_articles_files_to_remote_storage")
    for item in items:
        task_push_one_article_files_to_remote_storage.apply_async(
            kwargs={
                "username": username,
                "pkg_id": item.id,
            }
        )


def minio_push_file_content(content, mimetype, object_name):
    # TODO MinioStorage.fput_content
    try:
        minio = MinioConfiguration.get_files_storage(name="website")
        return minio.fput_content(content, mimetype, object_name)
    except Exception as e:
        logging.exception(e)
        return {"uri": "https://localhost/article/x"}


@celery_app.task(bind=True, name="push_one_article_files_to_remote_storage")
def task_push_one_article_files_to_remote_storage(
    self,
    username,
    pkg_id,
):
    failures = 0
    user = _get_user(self.request, username)
    sps_pkg = SPSPkg.objects.get(id=pkg_id)

    remote = RemoteSPSPkg.create_or_update(user, sps_pkg)
    responses = remote.publish_package(minio_push_file_content, user)
    for response in responses:
        try:
            uri = response["uri"]
        except KeyError as e:
            # TODO registra falha e deixa acessível na área restrita
            logging.error(f"Falha ao registrar arquivo em storage remoto {response}")
            logging.exception(e)
            failures += 1

    if not failures:
        remote.task_name = "request_pid_v3_and_create_articles"
        remote.save()
        sps_pkg.task_name = None
        sps_pkg.save()
