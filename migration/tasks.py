import logging

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from collection.models import Collection
from config import celery_app
from bigbang import tasks_scheduler
from migration.models import (
    MigratedDocument,
    MigratedDocumentHTML,
    MigratedIssue,
    MigratedJournal,
)

from . import controller
from .choices import (
    DOC_GENERATED_SPS_PKG,
    DOC_TO_GENERATE_SPS_PKG,
    DOC_TO_GENERATE_XML,
    DOC_GENERATED_XML,
    MS_IMPORTED,
    MS_TO_IGNORE,
    MS_TO_MIGRATE,
)

User = get_user_model()


def _get_user(user_id, username):
    if user_id:
        return User.objects.get(pk=user_id)
    if username:
        return User.objects.get(username=username)


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
    username : str
        identificacao do usuário
    collection_acron : str
        acrônimo da coleção
    force_update : bool
        atualiza mesmo se já existe
    """
    user = _get_user(user_id, username)

    if collection_acron:
        collections = Collection.objects.filter(
            collection__acron=collection_acron
        ).iterator()
    else:
        collections = Collection.objects.iterator()

    for collection in collections:
        task_migrate_title_db.apply_async(
            kwargs=dict(
                username=user.username,
                collection_acron=collection.acron,
                force_update=force_update,
            )
        )


@celery_app.task(bind=True)
def task_migrate_title_db(
    self,
    user_id=None,
    username=None,
    collection_acron=None,
    force_update=False,
):
    """
    Para uma dada coleção,
    obtém os registros da base de dados "title",
    cria registros MigratedJournal sequencialmente
    cria concorrentemente os registros OfficialJournal, SciELOJournal e Journal

    Parameters
    ----------
    username : str
        identificacao do usuário
    collection_acron : str
        acrônimo da coleção
    force_update : bool
        atualiza mesmo se já existe

    """
    user = _get_user(user_id, username)

    # Cria ou atualiza os registros de OfficialJournal, SciELOJournal e Journal
    # somente para os registros de MigratedJournal cujo status=MS_TO_MIGRATE
    if force_update:
        # modifica os status = MS_IMPORTED para MS_TO_MIGRATE
        items = MigratedJournal.objects.filter(
            collection=collection, status=MS_IMPORTED
        ).update(status=MS_TO_MIGRATE)

    # para cada registro da base de dados "title",
    # cria um registro MigratedJournal
    collection = Collection.get_or_create(acron=collection_acron, user=user)
    controller.migrate_title_db(user, collection, force_update)

    # seleciona os registros MigratedJournal para disparar as tarefas
    items = MigratedJournal.objects.filter(
        collection=collection, status=MS_TO_MIGRATE
    ).iterator()

    for item in items:
        # dispara tarefas para gerar os registros
        # OfficialJournal, SciELOJournal e Journal
        task_create_or_update_journal.apply_async(
            kwargs=dict(
                username=user.username,
                migrated_item_id=item.id,
                force_update=force_update,
            )
        )


@celery_app.task(bind=True)
def task_create_or_update_journal(
    self,
    username,
    migrated_item_id,
    force_update=False,
    user_id=None,
):
    """
    Para um dado registro de MigratedJournal,
    cria ou atualiza os registros de OfficialJournal, SciELOJournal e Journal

    Parameters
    ----------
    username : str
        identificacao do usuário
    migrated_item_id : int
        id de MigratedJournal
    force_update : bool
        atualiza mesmo se já existe

    """
    user = _get_user(user_id, username)
    item = MigratedJournal.objects.get(pk=migrated_item_id)
    controller.create_or_update_journal(user, item, force_update)


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
    username : str
        identificacao do usuário
    collection_acron : str
        acrônimo da coleção
    force_update : bool
        atualiza mesmo se já existe
    """
    user = _get_user(user_id, username)

    if collection_acron:
        collections = Collection.objects.filter(
            collection__acron=collection_acron
        ).iterator()
    else:
        collections = Collection.objects.iterator()

    for collection in collections:
        task_migrate_issue_db.apply_async(
            kwargs=dict(
                username=user.username,
                collection_acron=collection.acron,
                force_update=force_update,
            )
        )


@celery_app.task(bind=True)
def task_migrate_issue_db(
    self,
    username=None,
    collection_acron=None,
    force_update=False,
    user_id=None,
):
    """
    Para uma dada coleção,
    obtém os registros da base de dados "issue",
    cria / atualiza sequencialmente os registros MigratedIssue
    cria concorrentemente os registros SciELOIssue e Issue

    Parameters
    ----------
    username : str
        identificacao do usuário
    collection_acron : str
        acrônimo da coleção
    force_update : bool
        atualiza mesmo se já existe

    """
    user = _get_user(user_id, username)

    # Cria ou atualiza os registros de SciELOIssue e Issue
    # somente para os registros de MigratedIssue cujo status=MS_TO_MIGRATE
    if force_update:
        # modifica os status = MS_IMPORTED para MS_TO_MIGRATE
        items = MigratedIssue.objects.filter(
            collection=collection, status=MS_IMPORTED
        ).update(status=MS_TO_MIGRATE)

    # para cada registro da base de dados "issue",
    # cria um registro MigratedIssue
    collection = Collection.get_or_create(acron=collection_acron, user=user)
    controller.migrate_issue_db(user, collection, force_update)

    # seleciona os registros MigratedIssue para disparar as tarefas
    items = MigratedIssue.objects.filter(
        collection=collection, status=MS_TO_MIGRATE
    ).iterator()

    for item in items:
        # dispara tarefas para gerar os registros
        # SciELOIssue e Issue
        task_create_or_update_issue.apply_async(
            kwargs=dict(
                username=user.username,
                migrated_item_id=item.id,
                force_update=force_update,
            )
        )


@celery_app.task(bind=True)
def task_create_or_update_issue(
    self,
    username,
    migrated_item_id,
    force_update=False,
    user_id=None,
):
    """
    Para um dado registro de MigratedIssue,
    cria ou atualiza os registros de SciELOIssue e Issue

    Parameters
    ----------
    username : str
        identificacao do usuário
    migrated_item_id : int
        id de MigratedIssue
    force_update : bool
        atualiza mesmo se já existe

    """
    user = _get_user(user_id, username)
    item = MigratedIssue.objects.get(pk=migrated_item_id)
    controller.create_or_update_issue(user, item, force_update)


@celery_app.task(bind=True)
def task_migrate_document_files(
    self,
    user_id=None,
    username=None,
    collection_acron=None,
    force_update=False,
):
    """
    Se force_update=True, troca files_status de MS_IMPORTED para MS_TO_MIGRATE
    Para os registros de MigratedIssue cujo files_status = MS_TO_MIGRATE
    dispara a tarefa de migrar seus arquivos
    """
    if collection_acron:
        collections = Collection.objects.filter(
            collection__acron=collection_acron
        ).iterator()
    else:
        collections = Collection.objects.iterator()

    user = _get_user(user_id, username)
    for collection in collections:
        if force_update:
            items = MigratedIssue.objects.filter(
                collection=collection, files_status=MS_IMPORTED
            ).update(files_status=MS_TO_MIGRATE)

        items = MigratedIssue.objects.filter(
            Q(files_status=MS_TO_MIGRATE) | Q(files_status__isnull=True),
            collection=collection,
        ).iterator()

        for item in items:
            # Importa os arquivos das pastas */acron/volnum/*
            task_import_one_issue_files.apply_async(
                kwargs=dict(
                    username=user.username,
                    migrated_item_id=item.id,
                    force_update=force_update,
                )
            )


@celery_app.task(bind=True)
def task_import_one_issue_files(
    self,
    username,
    migrated_item_id,
    force_update=False,
    user_id=None,
):
    """
    Cria ou atualiza os registros de MigratedFile
    somente para os registros de MigratedIssue cujo files_status=MS_TO_MIGRATE
    """
    user = _get_user(user_id, username)
    item = MigratedIssue.objects.get(pk=migrated_item_id)
    controller.import_one_issue_files(user, item, force_update)


@celery_app.task(bind=True)
def task_migrate_document_records(
    self,
    user_id=None,
    username=None,
    collection_acron=None,
    force_update=False,
):
    """
    Se force_update=True, troca docs_status de MS_IMPORTED para MS_TO_MIGRATE
    Para os registros de MigratedIssue cujo docs_status = MS_TO_MIGRATE
    dispara a tarefa de migrar seus arquivos
    """
    if collection_acron:
        collections = Collection.objects.filter(
            collection__acron=collection_acron
        ).iterator()
    else:
        collections = Collection.objects.iterator()

    user = _get_user(user_id, username)
    for collection in collections:
        if force_update:
            items = MigratedIssue.objects.filter(
                collection=collection, docs_status=MS_IMPORTED
            ).update(docs_status=MS_TO_MIGRATE)

        items = MigratedIssue.objects.filter(
            Q(docs_status=MS_TO_MIGRATE) | Q(docs_status=None),
            collection=collection,
        ).iterator()

        for item in items:
            # Importa os registros de documentos
            task_import_one_issue_document_records.apply_async(
                kwargs=dict(
                    username=user.username,
                    migrated_item_id=item.id,
                    issue_folder=item.scielo_issue.issue_folder,
                    issue_pid=item.pid,
                    force_update=force_update,
                )
            )


@celery_app.task(bind=True)
def task_import_one_issue_document_records(
    self,
    username,
    migrated_item_id,
    issue_folder=None,
    issue_pid=None,
    force_update=False,
    user_id=None,
):
    """
    Cria ou atualiza os registros de MigratedDocument
    """
    user = _get_user(user_id, username)
    item = MigratedIssue.objects.get(pk=migrated_item_id)
    controller.import_one_issue_document_records(
        user=user,
        migrated_issue=item,
        issue_folder=issue_folder,
        issue_pid=issue_pid,
        force_update=force_update,
    )


@celery_app.task(bind=True)
def task_html_to_xmls(
    self,
    user_id=None,
    username=None,
    collection_acron=None,
    journal_acron=None,
    publication_year=None,
    issue_folder=None,
    force_update=False,
):
    user = _get_user(user_id, username)
    params = {}

    if collection_acron:
        params["collection__acron"] = collection_acron
    if journal_acron:
        params[
            "migrated_issue__migrated_journal__scielo_journal__acron"
        ] = journal_acron
    if publication_year:
        params[
            "migrated_issue__scielo_issue__official_issue__publication_year"
        ] = publication_year
    if issue_folder:
        params["migrated_issue__scielo_issue__issue_folder"] = issue_folder

    if force_update:
        items = MigratedDocumentHTML.objects.filter(
            Q(xml_status=DOC_TO_GENERATE_SPS_PKG)
            | Q(xml_status=DOC_GENERATED_SPS_PKG)
            | Q(xml_status=DOC_GENERATED_XML),
            **params,
        ).update(xml_status=DOC_TO_GENERATE_XML)

    items = MigratedDocumentHTML.objects.filter(
        xml_status=DOC_TO_GENERATE_XML,
        **params,
    )

    for migrated_doc in items.iterator():
        task_html_to_xml.apply_async(
            kwargs={
                "username": user.username,
                "migrated_item_id": migrated_doc.id,
                "body_and_back_xml": force_update,
                "html_to_xml": force_update,
            }
        )


@celery_app.task(bind=True)
def task_html_to_xml(
    self,
    username,
    migrated_item_id,
    body_and_back_xml,
    html_to_xml,
    user_id=None,
):
    user = _get_user(user_id, username)
    migrated_document = MigratedDocumentHTML.objects.get(pk=migrated_item_id)
    migrated_document.html_to_xml(user, body_and_back_xml, html_to_xml)


@celery_app.task(bind=True)
def task_generate_sps_packages(
    self,
    user_id=None,
    username=None,
    collection_acron=None,
    journal_acron=None,
    publication_year=None,
    issue_folder=None,
    force_update=False,
    body_and_back_xml=False,
    html_to_xml=False,
):
    user = _get_user(user_id, username)
    params = {}
    if collection_acron:
        params["collection__acron"] = collection_acron
    if journal_acron:
        params[
            "migrated_issue__migrated_journal__scielo_journal__acron"
        ] = journal_acron
    if publication_year:
        params[
            "migrated_issue__scielo_issue__official_issue__publication_year"
        ] = publication_year
    if issue_folder:
        params["migrated_issue__scielo_issue__issue_folder"] = issue_folder

    if force_update:
        # params["sps_pkg__isnull"] = False
        items = MigratedDocument.objects.filter(
            Q(sps_pkg__isnull=False), **params
        ).update(sps_pkg=None)

    items = MigratedDocument.objects.filter(Q(sps_pkg__isnull=True), **params)
    for migrated_doc in items.iterator():
        task_generate_sps_package.apply_async(
            kwargs={
                "username": user.username,
                "migrated_item_id": migrated_doc.id,
                "body_and_back_xml": body_and_back_xml,
                "html_to_xml": html_to_xml,
            }
        )


@celery_app.task(bind=True)
def task_generate_sps_package(
    self,
    username,
    migrated_item_id,
    body_and_back_xml=False,
    html_to_xml=False,
    user_id=None,
):
    user = _get_user(user_id, username)
    migrated_document = MigratedDocument.objects.get(pk=migrated_item_id)
    migrated_document.generate_sps_package(
        user,
        body_and_back_xml,
        html_to_xml,
    )


@celery_app.task(bind=True)
def task_run_migrations(
    self,
    user_id=None,
    username=None,
    collection_acron=None,
    force_update=False,
):
    user = _get_user(user_id, username)
    # migra os registros da base TITLE
    task_migrate_title_databases.apply_async(
        kwargs={
            "user_id": user.id,
            "collection_acron": collection_acron,
            "force_update": force_update,
        }
    )
    # migra os registros da base ISSUE
    task_migrate_issue_databases.apply_async(
        kwargs={
            "user_id": user.id,
            "collection_acron": collection_acron,
            "force_update": force_update,
        }
    )
    # migra os arquivos contidos nas pastas dos fascículos
    task_migrate_document_files.apply_async(
        kwargs={
            "user_id": user.id,
            "collection_acron": collection_acron,
            "force_update": force_update,
        }
    )
    # migra os registros das bases de artigos
    task_migrate_document_records.apply_async(
        kwargs={
            "user_id": user.id,
            "collection_acron": collection_acron,
            "force_update": force_update,
        }
    )
    task_html_to_xmls.apply_async(
        kwargs={
            "user_id": user.id,
            "collection_acron": collection_acron,
        }
    )
    # se aplicável, gera XML a partir do HTML
    # gera pacote sps
    task_generate_sps_packages.apply_async(
        kwargs={
            "user_id": user.id,
            "collection_acron": collection_acron,
        }
    )
