from unittest import TestCase
from unittest.mock import MagicMock, patch

from proc import tasks


class AvailabilityTaskTests(TestCase):
    def test_check_tasks_forward_force_update_and_timeout(self):
        for task, filters in (
            (
                tasks.task_check_article_webpages,
                {"collection_id": 5, "website_kind": "QA"},
            ),
            (tasks.task_check_migrated_article, {}),
        ):
            with self.subTest(task=task.name), patch.object(
                tasks, "_get_user", return_value="USER"
            ), patch.object(tasks, "ArticleProc") as model, patch.object(
                tasks.UnexpectedEvent, "create"
            ) as unexpected:
                article_proc = MagicMock()
                model.objects.get.return_value = article_proc
                model.objects.select_related.return_value.get.return_value = (
                    article_proc
                )
                article = article_proc.article
                article.available_on_classic_website.return_value = {"valid": False}
                article.available_on_public_website.return_value = {"valid": False}

                task.run(article_proc_id=77, force_update=True, timeout=7, **filters)

                unexpected.assert_not_called()
                article.create_or_update_article_collections.assert_called_once_with(
                    "USER", force_update=True
                )
                expected = {"force_update": True, "timeout": 7}
                if filters:
                    expected.update(collection_id=5, purpose="QA")
                article.check_availability.assert_called_once_with("USER", **expected)
