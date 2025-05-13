from django.utils.translation import gettext_lazy as _

from bigbang.utils.scheduler import delete_tasks, schedule_task

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
    "10",
)

MIGRATION_MINUTES = MINUTES[10]

TITLE_DB_MIGRATION_MINUTES = MINUTES[10]
ISSUE_DB_MIGRATION_MINUTES = MINUTES[10]
ARTICLE_DB_MIGRATION_MINUTES = MINUTES[10]

JOURNAL_REGISTRATION_MINUTES = MINUTES[10]
ISSUE_REGISTRATION_MINUTES = MINUTES[10]

IMPORT_ARTICLE_RECORDS_MINUTES = MINUTES[10]
IMPORT_ARTICLE_FILES_MINUTES = MINUTES[10]
HTML_TO_XMLS_MINUTES = MINUTES[10]
GENERATE_SPS_PACKAGES_MINUTES = MINUTES[10]

ARTICLE_REGISTRATION_MINUTES = MINUTES[10]

JOURNAL_PUBLICATION_MINUTES = MINUTES[10]
ISSUE_PUBLICATION_MINUTES = MINUTES[10]
ARTICLE_PUBLICATION_MINUTES = MINUTES[10]

SINCHRONIZE_TO_PID_PROVIDER_MINUTES = MINUTES[10]

TITLE_DB_MIGRATION_PRIORITY = 0
ISSUE_DB_MIGRATION_PRIORITY = 0
ARTICLE_DB_MIGRATION_PRIORITY = 4

JOURNAL_REGISTRATION_PRIORITY = 1
ISSUE_REGISTRATION_PRIORITY = 2
ARTICLE_REGISTRATION_PRIORITY = 3

JOURNAL_PUBLICATION_PRIORITY = 2
ISSUE_PUBLICATION_PRIORITY = 3
ARTICLE_PUBLICATION_PRIORITY = 4

IMPORT_ARTICLE_RECORDS_PRIORITY = 6
IMPORT_ARTICLE_FILES_PRIORITY = 7
HTML_TO_XMLS_PRIORITY = 9
GENERATE_SPS_PACKAGES_PRIORITY = 8

SINCHRONIZE_TO_PID_PROVIDER_PRIORITY = 5

MIGRATION_PRIORITY = ISSUE_DB_MIGRATION_PRIORITY + 1


def delete_migration_tasks():
    delete_tasks(
        [
            "create_or_update_articles",
            "create_or_update_issues",
            "create_or_update_journals",
            "generate_sps_packages",
            "get_xmls",
            "migrate_article_databases",
            "migrate_issue_databases",
            "migrate_journal_document_records",
            "migrate_title_databases",
            "task_migrate_document_files",
            "task_migrate_document_records",
            "migrate_and_publish",
        ]
    )


def schedule_migration_subtasks(username):
    enabled = False
    _schedule_task_check_article_availability(username, enabled)
    _schedule_migrate_and_publish_articles(username, enabled)
    _schedule_migrate_and_publish_issues(username, enabled)
    _schedule_migrate_and_publish_journals(username, enabled)
    # _schedule_migration_and_publication(username, enabled)
    _schedule_create_procs_from_pid_list(username, enabled)

def schedule_publication_subtasks(username):
    _schedule_publish_articles(username)
    _schedule_publish_issues(username)
    _schedule_publish_journals(username)


def _schedule_task_check_article_availability(username, enabled):
    schedule_task(
        task="publication.tasks.task_check_article_availability",
        name="task_check_article_availability",
        kwargs=dict(
            username=username,
            collection_acron=None,
            issn_print=None,
            issn_electronic=None,
            publication_year=None,
            article_pid_v3=None,
            purpose=None,
        ),
        description=_("Check the article availability"),
        priority=MIGRATION_PRIORITY,
        enabled=enabled,
        run_once=False,
        day_of_week="*",
        hour="*",
        minute=MIGRATION_MINUTES,
    )


def _schedule_create_procs_from_pid_list(username, enabled):
    """
    Agenda a tarefa de migrar os registros da base de dados TITLE
    Deixa a tarefa desabilitada
    """
    schedule_task(
        task="proc.tasks.task_create_procs_from_pid_list",
        name="create_procs_from_pid_list",
        kwargs=dict(
            username=username,
            collection_acron=None,
            force_update=False,
        ),
        description=_("Create Journal, Issue e Article Processing items"),
        priority=MIGRATION_PRIORITY,
        enabled=enabled,
        run_once=False,
        day_of_week="*",
        hour="*",
        minute=MIGRATION_MINUTES,
    )


def _schedule_migration_and_publication(username, enabled):
    """
    Agenda a tarefa de migrar os registros da base de dados TITLE
    Deixa a tarefa desabilitada
    """
    schedule_task(
        task="proc.tasks.task_migrate_and_publish",
        name="migrate_and_publish",
        kwargs=dict(
            username=username,
            collection_acron=None,
            publication_year=None,
            force_update=False,
            force_import_acron_id_file=False,
            force_migrate_document_records=False,
        ),
        description=_("Migra e publica"),
        priority=MIGRATION_PRIORITY,
        enabled=enabled,
        run_once=False,
        day_of_week="*",
        hour="*",
        minute=MIGRATION_MINUTES,
    )


def _schedule_migrate_and_publish_journals(username, enabled):
    """
    Agenda a tarefa de migrar os registros da base de dados TITLE
    Deixa a tarefa desabilitada
    """
    schedule_task(
        task="proc.tasks.task_migrate_and_publish_journals",
        name="migrate_and_publish_journals",
        kwargs=dict(
            username=username,
            collection_acron=None,
            journal_acron=None,
            force_update=False,
            status=["REPROC", "TODO", "DOING", "DONE", "PENDING", "BLOCKED"],
        ),
        description=_("Migra e publica os periódicos"),
        priority=TITLE_DB_MIGRATION_PRIORITY,
        enabled=enabled,
        run_once=False,
        day_of_week="*",
        hour="*",
        minute=TITLE_DB_MIGRATION_MINUTES,
    )


def _schedule_migrate_and_publish_issues(username, enabled):
    """
    Agenda a tarefa de migrar os registros da base de dados ISSUE
    Deixa a tarefa abilitada
    """
    schedule_task(
        task="proc.tasks.task_migrate_and_publish_issues",
        name="migrate_and_publish_issues",
        kwargs=dict(
            username=None,
            collection_acron=None,
            journal_acron=None,
            publication_year=None,
            issue_folder=None,
            status=["REPROC", "TODO", "DOING", "DONE", "PENDING", "BLOCKED"],
            force_update=False,
        ),
        description=_("Migra e publica os fascículos"),
        priority=ISSUE_DB_MIGRATION_PRIORITY,
        enabled=enabled,
        run_once=False,
        day_of_week="*",
        hour="*",
        minute=ISSUE_DB_MIGRATION_MINUTES,
    )


def _schedule_migrate_and_publish_articles(username, enabled):
    schedule_task(
        task="proc.tasks.task_migrate_and_publish_articles",
        name="migrate_and_publish_articles",
        kwargs=dict(
            username=None,
            collection_acron=None,
            journal_acron=None,
            publication_year=None,
            issue_folder=None,
            status=["REPROC", "TODO", "DOING", "DONE", "PENDING", "BLOCKED"],
            force_update=False,
            force_import_acron_id_file=False,
            force_migrate_document_records=False,
            force_migrate_document_files=False,
        ),
        description=_("Migra e publica artigos"),
        priority=ARTICLE_DB_MIGRATION_PRIORITY,
        enabled=enabled,
        run_once=False,
        day_of_week="*",
        hour="*",
        minute=ARTICLE_DB_MIGRATION_MINUTES,
    )


# def schedule_task_synchronize_to_pid_provider(username, enabled):
#     """
#     Agenda a tarefa de publicar os registros da base de dados TITLE
#     Deixa a tarefa desabilitada
#     """
#     schedule_task(
#         task="proc.tasks.task_synchronize_to_pid_provider",
#         name="task_synchronize_to_pid_provider",
#         kwargs=dict(
#             username=username,
#         ),
#         description=_("Sinchronize to pid provider"),
#         priority=SINCHRONIZE_TO_PID_PROVIDER_PRIORITY,
#         enabled=enabled,
#         run_once=False,
#         day_of_week="*",
#         hour="*",
#         minute=SINCHRONIZE_TO_PID_PROVIDER_MINUTES,
#     )


def _schedule_publish_journals(username, enabled=False):
    """
    Agenda a tarefa de migrar os registros da base de dados TITLE
    Deixa a tarefa desabilitada
    """
    schedule_task(
        task="proc.tasks.task_publish_journals",
        name="publish_journals",
        kwargs=dict(
            username=None,
            collection_acron=None,
            journal_acron=None,
            force_update=False,
        ),
        description=_("Publica periódicos"),
        priority=TITLE_DB_MIGRATION_PRIORITY,
        enabled=enabled,
        run_once=False,
        day_of_week="*",
        hour="*",
        minute=TITLE_DB_MIGRATION_MINUTES,
    )


def _schedule_publish_issues(username, enabled=False):
    """
    Agenda a tarefa de migrar os registros da base de dados ISSUE
    Deixa a tarefa abilitada
    """
    schedule_task(
        task="proc.tasks.task_publish_issues",
        name="publish_issues",
        kwargs=dict(
            username=None,
            collection_acron=None,
            journal_acron=None,
            publication_year=None,
            force_update=False,
        ),
        description=_("Publica fascículos"),
        priority=ISSUE_DB_MIGRATION_PRIORITY,
        enabled=enabled,
        run_once=False,
        day_of_week="*",
        hour="*",
        minute=ISSUE_DB_MIGRATION_MINUTES,
    )


def _schedule_publish_articles(username, enabled=False):
    schedule_task(
        task="proc.tasks.task_publish_articles",
        name="publish_articles",
        kwargs=dict(
            username=None,
            collection_acron=None,
            journal_acron=None,
            publication_year=None,
            force_update=False,
        ),
        description=_("Publica artigos"),
        priority=ARTICLE_DB_MIGRATION_PRIORITY,
        enabled=enabled,
        run_once=False,
        day_of_week="*",
        hour="*",
        minute=ARTICLE_DB_MIGRATION_MINUTES,
    )