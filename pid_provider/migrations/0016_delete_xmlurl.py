import json

from django.db import migrations


def delete_xml_url_periodic_tasks(apps, schema_editor):
    periodic_task = apps.get_model("django_celery_beat", "PeriodicTask")
    periodic_task.objects.filter(
        task="pid_provider.tasks.task_retry_xml_urls_by_status"
    ).delete()
    for task in periodic_task.objects.filter(
        name="task_load_records_from_counter_dict"
    ):
        try:
            kwargs = json.loads(task.kwargs)
        except (TypeError, ValueError):
            kwargs = {}
        if not kwargs.get("journal_acron"):
            task.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("django_celery_beat", "0018_improve_crontab_helptext"),
        ("pid_provider", "0015_pidprovidersetting"),
    ]

    operations = [
        migrations.RunPython(
            delete_xml_url_periodic_tasks,
            migrations.RunPython.noop,
        ),
        migrations.DeleteModel(
            name="XMLURL",
        ),
    ]
