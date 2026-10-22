import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


PREVIOUS = ("pid_provider", "0016_alter_pidproviderxmlregistration_event_status")
CURRENT = ("pid_provider", "0017_remove_xmlurl_and_source_tasks")
SOURCE_TASKS = (
    "pid_provider.tasks.task_load_records_from_counter_dict",
    "pid_provider.tasks.task_load_record_from_xml_url",
    "pid_provider.tasks.task_retry_xml_urls_by_status",
)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("state", ["empty", "populated", "already_removed"])
def test_migration_removes_obsolete_sources_without_discarding_legacy_records(state):
    executor = MigrationExecutor(connection)
    current_targets = executor.loader.graph.leaf_nodes()
    previous_targets = [item for item in current_targets if item[0] != "pid_provider"] + [PREVIOUS]
    executor.migrate(previous_targets)
    apps = executor.loader.project_state(previous_targets).apps
    xmlurl = apps.get_model("pid_provider", "XMLURL")
    task = apps.get_model("django_celery_beat", "PeriodicTask")
    for name in SOURCE_TASKS + ("upload.tasks.task_publish_issue_articles",):
        task.objects.create(name=name, task=name)
    try:
        if state == "populated":
            user = apps.get_model("users", "User").objects.create(username="legacy-source")
            xmlurl.objects.create(creator_id=user.pk, url="https://example.org/legacy.xml")
            with pytest.raises(RuntimeError, match="registros legados"):
                MigrationExecutor(connection).migrate(current_targets)
            assert xmlurl.objects.count() == 1
            assert task.objects.filter(task__in=SOURCE_TASKS).count() == 3
            xmlurl.objects.all().delete()
        elif state == "already_removed":
            with connection.schema_editor() as editor:
                editor.delete_model(xmlurl)

        MigrationExecutor(connection).migrate(current_targets)
        assert xmlurl._meta.db_table not in connection.introspection.table_names()
        assert not task.objects.filter(task__in=SOURCE_TASKS).exists()
        assert task.objects.filter(task="upload.tasks.task_publish_issue_articles").exists()
    finally:
        if xmlurl._meta.db_table in connection.introspection.table_names():
            xmlurl.objects.all().delete()
        MigrationExecutor(connection).migrate(current_targets)
