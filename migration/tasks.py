from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from config import celery_app

from . import controller

User = get_user_model()


def _get_user(request, username):
    try:
        return User.objects.get(pk=request.user.id)
    except AttributeError:
        return User.objects.get(username=username)


@celery_app.task(bind=True, name=_("schedule_migrations"))
def task_schedule_migrations(
    self,
    username=None,
    collection_acron=None,
):
    user = _get_user(self.request, username)
    controller.schedule_migrations(user, collection_acron)


@celery_app.task(bind=True, name="migrate_journal_records")
def task_migrate_journal_records(
    self,
    username,
    collection_acron,
    force_update=False,
):
    user = _get_user(self.request, username)
    controller.migrate_journal_records(
        user,
        collection_acron,
        force_update,
    )


@celery_app.task(bind=True, name="migrate_issue_records")
def task_migrate_issue_records(
    self,
    username,
    collection_acron,
    force_update=False,
):
    user = _get_user(self.request, username)
    controller.migrate_issue_records(
        user,
        collection_acron,
        force_update,
    )


@celery_app.task(bind=True, name="migrate_issue_files_and_document_records")
def task_migrate_issue_files_and_document_records(
    self,
    username,
    collection_acron,
    scielo_issn=None,
    publication_year=None,
    force_update=False,
):
    user = _get_user(self.request, username)
    controller.migrate_issue_files_and_document_records(
        user,
        collection_acron,
        scielo_issn,
        publication_year,
        force_update,
    )


@celery_app.task(bind=True, name="create_articles")
def task_create_articles(
    self,
    username,
    collection_acron=None,
    from_date=None,
    force_update=False,
):
    user = _get_user(self.request, username)
    controller.create_articles(
        user,
        collection_acron,
        from_date,
        force_update,
    )
