import logging
from datetime import datetime

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from article.controller import create_article
from article.models import Article
from config import celery_app
from package.models import SPSPkg

User = get_user_model()


def _get_user(user_id, username):
    if user_id:
        return User.objects.get(pk=user_id)
    if username:
        return User.objects.get(username=username)


@celery_app.task(bind=True)
def task_create_or_update_articles(
    self,
    user_id=None,
    username=None,
    from_date=None,
    force_update=None,
):
    user = _get_user(user_id, username)

    try:
        if force_update:
            from_date = "2000-01-01"
        if from_date:
            from_date = datetime.strptime(from_date, "%Y-%M-%d")
        last = from_date or Article.get_latest_change()
        items = SPSPkg.objects.filter(
            Q(updated__gte=last) | Q(created__gte=last),
            # is_approved=True
        ).iterator()
    except Exception as e:
        logging.exception(e)
        items = SPSPkg.objects.iterator()

    for item in items:
        task_create_or_update_article.apply_async(
            kwargs={
                "username": user.username,
                "pkg_id": item.id,
            }
        )


@celery_app.task(bind=True)
def task_create_or_update_article(
    self,
    user_id=None,
    username=None,
    pkg_id=None,
):
    user = _get_user(user_id, username)
    item = SPSPkg.objects.get(id=pkg_id)
    create_article(item, user)
