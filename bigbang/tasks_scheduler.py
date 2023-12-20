from django.utils.translation import gettext_lazy as _

from bigbang.utils.scheduler import schedule_task

# "6,16,26,36,46,56"

MINUTES = (
    "0,10,20,30,40,50",
    "1,11,21,31,41,51",
    "2,12,22,32,42,52",
    "3,13,23,33,43,53",
    "4,14,24,34,44,54",
    "5,15,25,35,45,55",
    "6,16,26,36,46,56",
    "7,17,27,37,47,57",
    "8,18,28,38,48,58",
    "9,19,29,39,49,59",
)

TITLE_DB_MIGRATION_MINUTES = MINUTES[0]
ISSUE_DB_MIGRATION_MINUTES = MINUTES[0]

JOURNAL_REGISTRATION_MINUTES = MINUTES[1]
ISSUE_REGISTRATION_MINUTES = MINUTES[2]

IMPORT_ARTICLE_RECORDS_MINUTES = MINUTES[3]
IMPORT_ARTICLE_FILES_MINUTES = MINUTES[3]
HTML_TO_XMLS_MINUTES = MINUTES[7]
GENERATE_SPS_PACKAGES_MINUTES = MINUTES[9]

ARTICLE_REGISTRATION_MINUTES = MINUTES[1]

JOURNAL_PUBLICATION_MINUTES = MINUTES[2]
ISSUE_PUBLICATION_MINUTES = MINUTES[3]
ARTICLE_PUBLICATION_MINUTES = MINUTES[4]


def schedule_migration_subtasks(username, enabled=None):
    _schedule_generate_sps_packages(username, enabled)
    _schedule_get_xmls(username, enabled)
    _schedule_migrate_document_files_and_records(username, enabled)
    _schedule_issue_registration(username, enabled)
    _schedule_title_registration(username, enabled)
    _schedule_issue_db_migration(username, enabled)
    _schedule_title_db_migration(username, enabled)


def schedule_publication_subtasks(username, enabled=None):
    _schedule_article_registration(username, enabled)
    _schedule_issue_publication(username, enabled)
    _schedule_journal_publication(username, enabled)
    _schedule_article_publication(username, enabled)


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
        priority=7,
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
        priority=8,
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
        task="proc.tasks.task_create_or_update_articles",
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
        priority=9,
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
        priority=0,
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


def _schedule_title_registration(username, enabled):
    """
    Agenda a tarefa de publicar os artigos
    """
    schedule_task(
        task="proc.tasks.task_create_or_update_journals",
        name="create_or_update_journals",
        kwargs=dict(
            username=username,
        ),
        description=_("Register journals"),
        priority=1,
        enabled=enabled,
        run_once=False,
        day_of_week="*",
        hour="*",
        minute=JOURNAL_REGISTRATION_MINUTES,
    )


def _schedule_issue_registration(username, enabled):
    """
    Agenda a tarefa de publicar os artigos
    """
    schedule_task(
        task="proc.tasks.task_create_or_update_issues",
        name="create_or_update_issues",
        kwargs=dict(
            username=username,
        ),
        description=_("Register issues"),
        priority=2,
        enabled=enabled,
        run_once=False,
        day_of_week="*",
        hour="*",
        minute=ISSUE_REGISTRATION_MINUTES,
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
        priority=3,
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
        priority=2,
        enabled=enabled,
        run_once=False,
        day_of_week="*",
        hour="*",
        minute=IMPORT_ARTICLE_RECORDS_MINUTES,
    )


def _schedule_get_xmls(username, enabled):
    """
    Agenda a tarefa de gerar os pacotes SPS dos documentos migrados
    Deixa a tarefa desabilitada
    Quando usuário quiser executar, deve preencher os valores e executar
    """
    schedule_task(
        task="migration.tasks.task_get_xmls",
        name="get_xmls",
        kwargs=dict(
            username=username,
            force_update=False,
        ),
        description=_("Obtém XML"),
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
        task="proc.tasks.task_generate_sps_packages",
        name="generate_sps_packages",
        kwargs=dict(
            username=username,
            force_update=False,
        ),
        description=_("Gera os pacotes SPS"),
        priority=5,
        enabled=enabled,
        run_once=False,
        day_of_week="*",
        hour="*",
        minute=GENERATE_SPS_PACKAGES_MINUTES,
    )
