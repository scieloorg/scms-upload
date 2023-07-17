import logging

from django.db.models import Q
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from . import controller
from article.models import ArticlePackages, Article
from article.controller import request_pid_v3_and_create_article
from config import celery_app


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
    source,
):

    items = ArticlePackages.objects.filter(
        article__isnull=True,
        optimised_zip_file__isnull=False,
        not_optimised_zip_file__isnull=False,
    )
    for article_pkgs in items.iterator():
        task_request_pid_v3_and_create_article.apply_async(
            kwargs={
                "username": username,
                "article_pkgs_id": article_pkgs.id,
                "source": source,
            }
        )


@celery_app.task(bind=True, name="request_pid_v3_and_create_article")
def task_request_pid_v3_and_create_article(
    self,
    username,
    article_pkgs_id,
    source,
):
    user = _get_user(self.request, username)
    article_pkgs = ArticlePackages.objects.get(id=article_pkgs_id)

    xml_name = article_pkgs.sps_pkg_name + ".xml"

    try:
        logging.info(f"Solicita/Confirma PID v3 para {xml_name}")

        # solicita pid v3 e obtém o article criado
        xml_with_pre = article_pkgs.get_xml_with_pre()
        response = request_pid_v3_and_create_article(
            xml_with_pre, xml_name, user, source,
        )
        if response["xml_changed"]:
            article_pkgs.update_xml(xml_with_pre)
        # cria / obtém article
        logging.info(f"Cria / obtém article para {xml_name}")
        article_pkgs.article = response["article"]
        article_pkgs.save()

    except Exception as e:
        # TODO registra falha e deixa acessível na área restrita
        logging.exception(e)


@celery_app.task(bind=True, name="push_articles_files_to_remote_storage")
def task_push_articles_files_to_remote_storage(
    self,
    username,
):

    items = ArticlePackages.objects.filter(
        Q(components__isnull=True) | Q(components__uri__isnull=True),
        article__isnull=False,
        optimised_zip_file__isnull=False,
        not_optimised_zip_file__isnull=False,
    )
    for article_pkgs in items.iterator():
        task_push_one_article_files_to_remote_storage.apply_async(
            kwargs={
                "username": username,
                "article_pkgs_id": article_pkgs.id,
            }
        )


def minio_push_file_content(content, mimetype, object_name):
    # TODO MinioStorage.fput_content
    return {"uri": "https://localhost/article/x"}


@celery_app.task(bind=True, name="push_one_article_files_to_remote_storage")
def task_push_one_article_files_to_remote_storage(
    self,
    username,
    article_pkgs_id,
):
    user = _get_user(self.request, username)
    article_pkgs = ArticlePackages.objects.get(id=article_pkgs_id)

    responses = article_pkgs.publish_package(
        minio_push_file_content,
        user,
    )
    for response in responses:
        try:
            uri = response["uri"]
        except KeyError as e:
            # TODO registra falha e deixa acessível na área restrita
            logging.error(f"Falha ao registrar arquivo em storage remoto {response}")
            logging.exception(e)
