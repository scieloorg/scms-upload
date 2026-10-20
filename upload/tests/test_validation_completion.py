from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from config import celery_app
from upload import tasks


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("failure", [False, True])
def test_reception_finishes_once_after_all_validation_tasks(monkeypatch, failure):
    monkeypatch.setattr(celery_app.conf, "task_always_eager", True)
    monkeypatch.setattr(celery_app.conf, "task_eager_propagates", True)
    monkeypatch.setattr(celery_app.conf, "result_backend", "cache+memory://")
    package = Mock(pk=1, article=None)
    package.file = SimpleNamespace(path="article.zip")
    xml = SimpleNamespace(
        filename="article.xml", filenames=[], assets=[], renditions=[]
    )
    package.xml_with_pre = xml
    validators = (
        tasks.task_validate_assets,
        tasks.task_validate_renditions,
        tasks.task_validate_xml_structure,
        tasks.task_validate_xml_content,
        tasks.task_validate_renditions_content,
    )
    completed = []

    with ExitStack() as stack:
        stack.enter_context(patch("upload.tasks.User.objects.get"))
        stack.enter_context(
            patch("upload.tasks.Package.objects.get", return_value=package)
        )
        stack.enter_context(
            patch(
                "upload.tasks.receive_package",
                return_value={
                    "journal": SimpleNamespace(id=1),
                    "issue": SimpleNamespace(id=1),
                },
            )
        )
        stack.enter_context(
            patch("upload.tasks.task_optimise_package", return_value="article.zip")
        )
        stack.enter_context(patch("upload.tasks.XMLWithPre.create", return_value=[xml]))
        for validator in validators:

            def validate(_name=validator.name, **kwargs):
                package.finish_reception.assert_not_called()
                if failure and _name == validators[-1].name:
                    raise RuntimeError("validation failed")
                completed.append(_name)

            stack.enter_context(patch.object(validator, "run", side_effect=validate))

        if failure:
            with pytest.raises(RuntimeError, match="validation failed"):
                tasks.task_receive_package.run(user_id=1, pkg_id=1)
            package.finish_reception.assert_not_called()
        else:
            tasks.task_receive_package.run(user_id=1, pkg_id=1)
            assert completed == [validator.name for validator in validators]
            package.finish_reception.assert_called_once_with(
                tasks.task_upload_workflow_publish_article
            )
