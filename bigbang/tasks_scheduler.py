from django.utils.translation import gettext_lazy as _

from bigbang.utils.scheduler import schedule_task

MIGRATION_TASKS_MINUTES = "5,10,15,20,25,30,35,40,45,50,55"
PUBLICATION_TASKS_MINUTES = "7,17,27,37,47,57"

TITLE_DB_MIGRATION_MINUTES = "1,11,21,31,41,51"
ISSUE_DB_MIGRATION_MINUTES = "1,11,21,31,41,51"
IMPORT_ARTICLE_RECORDS_MINUTES = "2,12,22,32,42,52"
IMPORT_ARTICLE_FILES_MINUTES = "3,13,23,33,43,53"
HTML_TO_XMLS_MINUTES = "4,14,24,34,44,54"
GENERATE_SPS_PACKAGES_MINUTES = "5,15,25,35,45,55"

JOURNAL_PUBLICATION_MINUTES = "2,12,22,32,42,52"
ISSUE_PUBLICATION_MINUTES = "4,14,24,34,44,54"
ARTICLE_REGISTRATION_MINUTES = "6,16,26,36,46,56"
ARTICLE_PUBLICATION_MINUTES = "7,17,27,37,47,57"


def schedule_migrations(
    username, collection_acron=None, activate_run_all=False, activate_run_partial=None
):
    _schedule_title_db_migration(username, activate_run_partial)
    _schedule_issue_db_migration(username, activate_run_partial)
    _schedule_migrate_document_files_and_records(username, activate_run_partial)
    _schedule_html_to_xmls(username, activate_run_partial)
    _schedule_generate_sps_packages(username, activate_run_partial)
    _schedule_run_migrations(username, activate_run_all)


def schedule_publication(
    username, collection_acron=None, activate_run_all=False, activate_run_partial=None
):
    _schedule_journal_publication(username, activate_run_partial)
    _schedule_issue_publication(username, activate_run_partial)
    _schedule_article_registration(username, activate_run_partial)
    _schedule_article_publication(username, activate_run_partial)
    _schedule_run_publication(username, activate_run_all)


def _schedule_run_publication(username, enabled):
    """
    Agenda a tarefa de migrar os registros da base de dados TITLE
    Deixa a tarefa desabilitada
    """
    schedule_task(
        task="publication.tasks.task_publish",
        name="run_publication",
        kwargs=dict(
            username=username,
            force_update=False,
        ),
        description=_("Executa todas as tarefas de publicação"),
        priority=1,
        enabled=enabled,
        run_once=False,
        day_of_week="*",
        hour="1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22",
        minute=PUBLICATION_TASKS_MINUTES,
    )


def _schedule_journal_publication(username, enabled):
    """
    Agenda a tarefa de publicar os registros da base de dados TITLE
    Deixa a tarefa desabilitada
    """
    schedule_task(
        task="publication.tasks.task_publish_journals",
        name="publish_journals",
        kwargs=dict(
            username=username,
            collection_acron=None,
        ),
        description=_("Publish journals"),
        priority=1,
        enabled=enabled,
        run_once=False,
        day_of_week="*",
        hour="*",
        minute=JOURNAL_PUBLICATION_MINUTES,
    )


def _schedule_issue_publication(username, enabled):
    """
    Agenda a tarefa de publicar os registros de fascículos
    Deixa a tarefa abilitada
    """
    schedule_task(
        task="publication.tasks.task_publish_issues",
        name="publish_issues",
        kwargs=dict(
            username=username,
            collection_acron=None,
        ),
        description=_("Publish issues"),
        priority=0,
        enabled=enabled,
        run_once=False,
        day_of_week="*",
        hour="*",
        minute=ISSUE_PUBLICATION_MINUTES,
    )


def _schedule_article_registration(username, enabled):
    """
    Agenda a tarefa de publicar os artigos
    """
    schedule_task(
        task="article.tasks.task_create_or_update_articles",
        name="create_or_update_articles",
        kwargs=dict(
            username=username,
        ),
        description=_("Register documents"),
        priority=1,
        enabled=enabled,
        run_once=False,
        day_of_week="*",
        hour="*",
        minute=ARTICLE_REGISTRATION_MINUTES,
    )


def _schedule_article_publication(username, enabled):
    """
    Agenda a tarefa de publicar os arquivos de issue_folder
    """
    schedule_task(
        task="publication.tasks.task_publish_articles",
        name="publish_articles",
        kwargs=dict(
            username=username,
            collection_acron=None,
        ),
        description=_("Publish documents"),
        priority=1,
        enabled=enabled,
        run_once=False,
        day_of_week="*",
        hour="*",
        minute=ARTICLE_PUBLICATION_MINUTES,
    )


def _schedule_title_db_migration(username, enabled):
    """
    Agenda a tarefa de migrar os registros da base de dados TITLE
    Deixa a tarefa desabilitada
    """
    schedule_task(
        task="migration.tasks.task_migrate_title_databases",
        name="migrate_title_databases",
        kwargs=dict(
            username=username,
            force_update=False,
        ),
        description=_("Migra os registros da base de dados TITLE"),
        priority=1,
        enabled=enabled,
        run_once=False,
        day_of_week="*",
        hour="*",
        minute=TITLE_DB_MIGRATION_MINUTES,
    )


def _schedule_issue_db_migration(username, enabled):
    """
    Agenda a tarefa de migrar os registros da base de dados ISSUE
    Deixa a tarefa abilitada
    """
    schedule_task(
        task="migration.tasks.task_migrate_issue_databases",
        name="migrate_issue_databases",
        kwargs=dict(
            username=username,
            force_update=False,
        ),
        description=_("Migra os registros da base de dados ISSUE"),
        priority=0,
        enabled=enabled,
        run_once=False,
        day_of_week="*",
        hour="*",
        minute=ISSUE_DB_MIGRATION_MINUTES,
    )


def _schedule_migrate_document_files_and_records(username, enabled):
    """
    Agenda a tarefa de migrar os arquivos de issue_folder
    """
    schedule_task(
        task="migration.tasks.task_migrate_document_files",
        name="task_migrate_document_files",
        kwargs=dict(
            username=username,
            force_update=False,
        ),
        description=_("Migra arquivos dos documentos"),
        priority=1,
        enabled=enabled,
        run_once=False,
        day_of_week="*",
        hour="*",
        minute=IMPORT_ARTICLE_FILES_MINUTES,
    )
    schedule_task(
        task="migration.tasks.task_migrate_document_records",
        name="task_migrate_document_records",
        kwargs=dict(
            username=username,
            force_update=False,
        ),
        description=_("Migra registros dos documentos"),
        priority=1,
        enabled=enabled,
        run_once=False,
        day_of_week="*",
        hour="*",
        minute=IMPORT_ARTICLE_RECORDS_MINUTES,
    )


def _schedule_html_to_xmls(username, enabled):
    """
    Agenda a tarefa de gerar os pacotes SPS dos documentos migrados
    Deixa a tarefa desabilitada
    Quando usuário quiser executar, deve preencher os valores e executar
    """
    schedule_task(
        task="migration.tasks.task_html_to_xmls",
        name="html_to_xmls",
        kwargs=dict(
            username=username,
            force_update=False,
        ),
        description=_("Converte HTML em XML"),
        priority=4,
        enabled=enabled,
        run_once=False,
        day_of_week="*",
        hour="*",
        minute=HTML_TO_XMLS_MINUTES,
    )


def _schedule_generate_sps_packages(username, enabled):
    """
    Agenda a tarefa de gerar os pacotes SPS dos documentos migrados
    Deixa a tarefa desabilitada
    Quando usuário quiser executar, deve preencher os valores e executar
    """
    schedule_task(
        task="migration.tasks.task_generate_sps_packages",
        name="generate_sps_packages",
        kwargs=dict(
            username=username,
            force_update=False,
        ),
        description=_("Gera os pacotes SPS"),
        priority=4,
        enabled=enabled,
        run_once=False,
        day_of_week="*",
        hour="*",
        minute=GENERATE_SPS_PACKAGES_MINUTES,
    )


def _schedule_run_migrations(username, enabled):
    """
    Agenda a tarefa de migrar os registros da base de dados TITLE
    Deixa a tarefa desabilitada
    """
    schedule_task(
        task="migration.tasks.task_run_migrations",
        name="run_migrations",
        kwargs=dict(
            username=username,
            force_update=False,
        ),
        description=_("Executa todas as tarefas de migração"),
        priority=1,
        enabled=enabled,
        run_once=False,
        day_of_week="*",
        hour="1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22",
        minute=MIGRATION_TASKS_MINUTES,
    )
