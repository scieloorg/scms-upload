import json
from importlib import import_module

import pytest
from django.apps import apps
from django_celery_beat.models import IntervalSchedule, PeriodicTask


@pytest.mark.django_db
def test_delete_xml_url_periodic_tasks_keeps_valid_journal_task():
    interval = IntervalSchedule.objects.create(
        every=1,
        period=IntervalSchedule.DAYS,
    )
    PeriodicTask.objects.create(
        name="legacy-xml-url-retry",
        task="pid_provider.tasks.task_retry_xml_urls_by_status",
        kwargs="{}",
        interval=interval,
    )
    PeriodicTask.objects.create(
        name="task_load_records_from_counter_dict",
        task="pid_provider.tasks.task_load_records_from_counter_dict",
        kwargs=json.dumps({"journal_acron": None}),
        interval=interval,
    )
    valid_task = PeriodicTask.objects.create(
        name="load-rsp-from-counter-dict",
        task="pid_provider.tasks.task_load_records_from_counter_dict",
        kwargs=json.dumps({"journal_acron": "rsp"}),
        interval=interval,
    )
    migration = import_module("pid_provider.migrations.0016_delete_xmlurl")

    migration.delete_xml_url_periodic_tasks(apps, None)

    assert PeriodicTask.objects.filter(pk=valid_task.pk).exists()
    assert not PeriodicTask.objects.filter(
        task="pid_provider.tasks.task_retry_xml_urls_by_status"
    ).exists()
    assert not PeriodicTask.objects.filter(
        name="task_load_records_from_counter_dict"
    ).exists()
