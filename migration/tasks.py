import logging
import sys

from django.utils.translation import gettext_lazy as _

from collection.models import Collection
from core.utils.get_user import _get_user
from config import celery_app
from htmlxml.models import HTMLXML
from proc.models import ArticleProc, IssueProc, JournalProc
from tracker.models import UnexpectedEvent

from . import controller


def _get_collections(collection_acron):
    try:
        if collection_acron:
            return Collection.objects.filter(acron=collection_acron).iterator()
        else:
            return Collection.objects.iterator()
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "migration.tasks._get_collections",
                "collection_acron": collection_acron,
            },
        )


@celery_app.task(bind=True)
def task_migrate_title_databases(
    self,
    user_id=None,
    username=None,
    collection_acron=None,
    force_update=False,
):
    """
    Para todas ou para uma dada coleção,
    aciona uma tarefa para migrar a base de dados "title"

    Parameters
    ----------
    user_id : int
        identificacao do usuário
    username : str
        identificacao do usuário
    collection_acron : str
        acrônimo da coleção
    force_update : bool
        atualiza mesmo se já existe
    """
    try:
        for collection in _get_collections(collection_acron):

            # obtém os dados do site clássico
            classic_website = controller.get_classic_website(collection.acron)

            for (
                scielo_issn,
                journal_data,
            ) in classic_website.get_journals_pids_and_records():
                # para cada registro da base de dados "title",
                # cria um registro MigratedData (source="journal")
                task_migrate_title_record.apply_async(
                    kwargs=dict(
                        user_id=user_id,
                        username=username,
                        collection_acron=collection.acron,
                        pid=scielo_issn,
                        data=journal_data[0],
                        force_update=force_update,
                    )
                )
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "migration.tasks._get_collections",
                "user_id": user_id,
                "username": username,
                "collection_acron": collection_acron,
                "force_update": force_update,
            },
        )


@celery_app.task(bind=True)
def task_migrate_title_record(
    self,
    user_id=None,
    username=None,
    collection_acron=None,
    pid=None,
    data=None,
    force_update=False,
):
    """
    Cria um registro MigratedData (source="journal")
    """
    try:
        user = _get_user(self.request, user_id, username)
        collection = Collection.get(acron=collection_acron)
        JournalProc.register_classic_website_data(
            user,
            collection,
            pid,
            data,
            "journal",
            force_update,
        )
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "migration.tasks._get_collections",
                "user_id": user_id,
                "username": username,
                "collection_acron": collection_acron,
                "pid": pid,
                "data": data,
                "force_update": force_update,
            },
        )


@celery_app.task(bind=True)
def task_migrate_issue_databases(
    self,
    user_id=None,
    username=None,
    collection_acron=None,
    force_update=False,
):
    """
    Para todas ou para uma dada coleção,
    aciona uma tarefa para migrar a base de dados "issue"

    Parameters
    ----------
    user_id : int
        identificacao do usuário
    username : str
        identificacao do usuário
    collection_acron : str
        acrônimo da coleção
    force_update : bool
        atualiza mesmo se já existe
    """

    try:
        for collection in _get_collections(collection_acron):
            # obtém os dados do site clássico
            classic_website = controller.get_classic_website(collection.acron)

            for (
                pid,
                issue_data,
            ) in classic_website.get_issues_pids_and_records():
                # para cada registro da base de dados "issue",
                # cria um registro MigratedData (source="issue")
                task_migrate_issue_record.apply_async(
                    kwargs=dict(
                        user_id=user_id,
                        username=username,
                        collection_acron=collection.acron,
                        pid=pid,
                        data=issue_data[0],
                        force_update=force_update,
                    )
                )
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "migration.tasks.task_migrate_issue_db",
                "user_id": user_id,
                "username": username,
                "collection_acron": collection_acron,
                "force_update": force_update,
            },
        )


@celery_app.task(bind=True)
def task_migrate_issue_record(
    self,
    user_id=None,
    username=None,
    collection_acron=None,
    pid=None,
    data=None,
    force_update=False,
):
    """
    Cria um registro MigratedData (source="issue")
    """
    try:
        user = _get_user(self.request, user_id, username)
        collection = Collection.get(acron=collection_acron)

        IssueProc.register_classic_website_data(
            user,
            collection,
            pid,
            data,
            "issue",
            force_update,
        )
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "migration.tasks.task_migrate_issue_record",
                "user_id": user_id,
                "username": username,
                "collection_acron": collection_acron,
                "pid": pid,
                "data": data,
                "force_update": force_update,
            },
        )


############################################
@celery_app.task(bind=True)
def task_migrate_document_files(
    self,
    user_id=None,
    username=None,
    collection_acron=None,
    journal_acron=None,
    publication_year=None,
    force_update=False,
):
    try:
        publication_year = publication_year and str(publication_year)
        for collection in _get_collections(collection_acron):
            items = IssueProc.files_to_migrate(
                collection, journal_acron, publication_year, force_update)
            for item in items:
                # Importa os arquivos das pastas */acron/volnum/*
                task_import_one_issue_files.apply_async(
                    kwargs=dict(
                        user_id=user_id,
                        username=username,
                        item_id=item.id,
                        force_update=force_update,
                    )
                )
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "migration.tasks.task_migrate_document_files",
                "user_id": user_id,
                "username": username,
                "collection_acron": collection_acron,
                "force_update": force_update,
            },
        )


@celery_app.task(bind=True)
def task_import_one_issue_files(
    self,
    user_id=None,
    username=None,
    item_id=None,
    force_update=False,
):
    try:
        user = _get_user(self.request, user_id, username)
        item = IssueProc.objects.get(pk=item_id)
        item.get_files_from_classic_website(
            user, force_update, controller.import_one_issue_files
        )
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "migration.tasks.task_import_one_issue_files",
                "user_id": user_id,
                "username": username,
                "item_id": item_id,
                "force_update": force_update,
            },
        )


############################################
@celery_app.task(bind=True)
def task_migrate_document_records(
    self,
    user_id=None,
    username=None,
    collection_acron=None,
    journal_acron=None,
    publication_year=None,
    force_update=False,
):
    try:
        publication_year = publication_year and str(publication_year)

        for collection in _get_collections(collection_acron):
            items = IssueProc.docs_to_migrate(
                collection, journal_acron, publication_year, force_update)
            for item in items:
                # Importa os registros de documentos
                task_import_one_issue_document_records.apply_async(
                    kwargs=dict(
                        item_id=item.id,
                        user_id=user_id,
                        username=username,
                        force_update=force_update,
                    )
                )
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "migration.tasks.task_migrate_document_records",
                "user_id": user_id,
                "username": username,
                "collection_acron": collection_acron,
                "force_update": force_update,
            },
        )


@celery_app.task(bind=True)
def task_import_one_issue_document_records(
    self,
    item_id,
    user_id=None,
    username=None,
    force_update=False,
):
    """
    Cria ou atualiza os registros de ArticleProc
    """
    try:
        user = _get_user(self.request, user_id, username)
        item = IssueProc.objects.get(pk=item_id)
        item.get_article_records_from_classic_website(
            user, force_update, controller.get_article_records_from_classic_website
        )
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "migration.tasks.task_import_one_issue_document_records",
                "item_id": item_id,
                "user_id": user_id,
                "username": username,
                "force_update": force_update,
            },
        )


@celery_app.task(bind=True)
def task_get_xmls(
    self,
    user_id=None,
    username=None,
    collection_acron=None,
    force_update=False,
):
    try:
        for collection in _get_collections(collection_acron):
            items = ArticleProc.items_to_get_xml(
                collection_acron=collection_acron,
                force_update=force_update,
            )
            for item in items:
                task_get_xml.apply_async(
                    kwargs={
                        "username": username,
                        "user_id": user_id,
                        "item_id": item.id,
                        "body_and_back_xml": force_update,
                    }
                )
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "migration.tasks.task_get_xmls",
                "user_id": user_id,
                "username": username,
                "collection_acron": collection_acron,
                "force_update": force_update,
            },
        )


@celery_app.task(bind=True)
def task_get_xml(
    self,
    user_id=None,
    username=None,
    item_id=None,
    body_and_back_xml=None,
):
    try:
        user = _get_user(self.request, user_id, username)

        item = ArticleProc.objects.get(pk=item_id)
        try:
            htmlxml = HTMLXML.get(migrated_article=item.migrated_data)
        except HTMLXML.DoesNotExist:
            htmlxml = None
        item.get_xml(user, htmlxml, body_and_back_xml)

    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "task": "migration.tasks.task_get_xml",
                "item_id": item_id,
                "user_id": user_id,
                "username": username,
                "body_and_back_xml": body_and_back_xml,
            },
        )
