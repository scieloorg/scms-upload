from django.db import migrations


SOURCE_TASKS = (
    "pid_provider.tasks.task_load_records_from_counter_dict",
    "pid_provider.tasks.task_load_record_from_xml_url",
    "pid_provider.tasks.task_retry_xml_urls_by_status",
)


def remove_xmlurl_and_source_tasks(apps, schema_editor):
    xmlurl = apps.get_model("pid_provider", "XMLURL")
    alias = schema_editor.connection.alias
    table_exists = xmlurl._meta.db_table in schema_editor.connection.introspection.table_names()
    if table_exists and xmlurl.objects.using(alias).exists():
        raise RuntimeError(
            "XMLURL contém registros legados. Resolva a preservação/exportação "
            "ou o descarte autorizado desses dados antes de remover a tabela."
        )

    periodic_task = apps.get_model("django_celery_beat", "PeriodicTask")
    periodic_task.objects.using(alias).filter(task__in=SOURCE_TASKS).delete()
    if table_exists:
        schema_editor.delete_model(xmlurl)


def restore_xmlurl_table(apps, schema_editor):
    xmlurl = apps.get_model("pid_provider", "XMLURL")
    if xmlurl._meta.db_table not in schema_editor.connection.introspection.table_names():
        schema_editor.create_model(xmlurl)


class Migration(migrations.Migration):
    dependencies = [
        ("pid_provider", "0016_alter_pidproviderxmlregistration_event_status"),
        ("django_celery_beat", "0018_improve_crontab_helptext"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(
                remove_xmlurl_and_source_tasks, restore_xmlurl_table,
            )],
            state_operations=[migrations.DeleteModel(name="XMLURL")],
        ),
    ]
