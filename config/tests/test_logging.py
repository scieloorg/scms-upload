import logging
from unittest.mock import Mock

from django_tasks import TaskResultStatus
from django_tasks.backends.base import BaseTaskBackend
from django_tasks.signals import log_task_finished, log_task_started


def test_only_reference_index_routine_logs_are_hidden(caplog):
    result = Mock(
        id="logging-test",
        task=Mock(module_path="wagtail.tasks.update_reference_index_task"),
        status=TaskResultStatus.RUNNING,
    )
    with caplog.at_level(logging.INFO):
        log_task_started(sender=BaseTaskBackend, task_result=result)
        result.status = TaskResultStatus.SUCCESSFUL
        log_task_finished(sender=BaseTaskBackend, task_result=result)
        logging.getLogger("django_tasks").warning(
            "Task path=wagtail.tasks.update_reference_index_task warning remains visible"
        )
        try:
            raise RuntimeError("task failure remains visible")
        except RuntimeError:
            result.status = TaskResultStatus.FAILED
            log_task_finished(sender=BaseTaskBackend, task_result=result)
        result.task.module_path = "upload.tasks.example"
        result.status = TaskResultStatus.RUNNING
        log_task_started(sender=BaseTaskBackend, task_result=result)
        result.status = TaskResultStatus.SUCCESSFUL
        log_task_finished(sender=BaseTaskBackend, task_result=result)
        logging.getLogger("upload").info("upload progress remains visible")

    messages = [record.getMessage() for record in caplog.records]
    reference_messages = [
        message
        for message in messages
        if "path=wagtail.tasks.update_reference_index_task" in message
    ]
    assert not any("state=RUNNING" in message for message in reference_messages)
    assert not any("state=SUCCESSFUL" in message for message in reference_messages)
    assert any("warning remains visible" in message for message in reference_messages)
    assert "Task id=logging-test path=upload.tasks.example state=RUNNING" in messages
    assert "Task id=logging-test path=upload.tasks.example state=SUCCESSFUL" in messages
    failure = next(
        record for record in caplog.records if "state=FAILED" in record.getMessage()
    )
    assert failure.levelno == logging.ERROR
    assert failure.exc_info[0] is RuntimeError
    assert "upload progress remains visible" in messages
